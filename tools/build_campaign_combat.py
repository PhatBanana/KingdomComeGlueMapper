"""Stage source-derived quest combat and dialogue handoffs in existing packages."""
import argparse
import copy
import json
import posixpath
import re
import uuid
import xml.etree.ElementTree as ET
from pathlib import Path
import zipfile

from campaign_behavior_requests import target
from campaign_combat_plan import plan, walk, attrs, one
from campaign_combat_runtime import emit
from campaign_bindings import build_bindings
from campaign_linker import link_entities
from campaign_entity_links import append_links, native_guid
from campaign_quest_graph import xml, edge, constant, all_of
from build_horse_trader_test import rewrite, digest
from upgrade_map import read


def source_binding(model, level):
    with zipfile.ZipFile(level) as pak:
        documents = {n: read(pak, n) for n in pak.namelist() if n.lower() == 'objects_mission0.xml'
                     or n.lower().startswith('layers/') and n.lower().endswith('.xml')}
        souls = ET.fromstring(read(pak, 'whdata_0'))
    world = link_entities(documents, model['tables']['quest']['rows'][0].get('smart_object') or model['quest'])
    result = build_bindings(model, world, souls)
    result['_world'] = world
    return result


def request_site(model, tag):
    matches = []
    def visit(n, ancestors):
        selected = re.search(r"(?:^|,)\s*behaviorName\('?(\w+)'?\)", attrs(n).get('values', ''))
        r = target(n) if selected and selected[1] == tag else None
        if r and r['tree'] == tag:
            for parent in reversed(ancestors):
                a = attrs(parent)
                expression = a.get('condition', '')
                m = re.fullmatch(r"\(\$(\w+)\.ObjectiveName == '([\w]+)'\)\s*&\s*\(\$\1\.State == \$enum:ObjectiveState\.Started\)", expression)
                if m:
                    matches.append((n, m[2]))
                    break
        for c in n['children']: visit(c, ancestors + [n])
    for document in model['behavior_documents'].values():
        for tree in document['trees'].values(): visit(tree['root'], [])
    return one(matches, 'Expected one objective-start dispatch for selected combat tag')


def convert(files, level_files, bindings, model, tag, project_path, entry_path, native_game):
    """Pure conversion shared by campaign assembly and package refresh builds.

    Inputs are snapshots; errors never publish a partially connected fight.
    """
    request, objective = request_site(model, tag)
    source_plan = plan(model, request)
    available_aliases = {n.get('Alias') for p, b in files.items() if p.startswith('Quests/')
                         for n in ET.fromstring(b).iter('Decision')}
    required_barks = {o['aftermath']['bark']['alias'] for o in source_plan['outcomes'].values() if o.get('aftermath')}
    if required_barks - available_aliases:
        raise ValueError('Combat speech dependencies require dialogue/audio import: ' + ', '.join(sorted(required_barks - available_aliases)))
    by_name = {b['name']: b for b in bindings['bindings']}
    roles = {}
    for role in [source_plan['actor_role']] + source_plan['partners']:
        key = "t_actors['" + role + "']"
        names = bindings['references'].get(key, [])
        record = by_name[one(names, 'Missing source role binding: ' + role)]
        if record['asset_type'] != 'SoulAsset': raise ValueError('Fight role is not a placed soul')
        roles[role] = record
    objects_blob = level_files['objects_mission0.xml']
    waiting_blob = level_files['waitinglinks.xml']
    compiled_scheduler = ET.fromstring(level_files['tables/ai/scheduler.xml'])
    from character_person_world import native_wait_activity
    from character_person_activity import validate_scheduler_targets
    activity_template, _ = native_wait_activity(native_game)
    validate_scheduler_targets(compiled_scheduler)
    root, entry = ET.fromstring(files[project_path]), ET.fromstring(files[entry_path])
    project = root.find('./Skald/Project')
    host = entry.find('./Skald/Level')
    if host is None and project_path == entry_path:
        host = project
        entry = root
    if project is None or host is None: raise ValueError('Expected existing Project/Level scopes')
    if not any(n.get('Name') == 'player' for scope in (project, host) for n in scope.findall('Assets/SoulAsset')):
        raise ValueError('Campaign player soul binding has not been registered')
    nodes = host.find('Nodes')
    quest = one((n for n in nodes if n.tag == model['quest']), 'Missing native quest instance')
    quest_path = one((p for p, b in files.items() if ET.fromstring(b).find('./Skald/Quest[@Name="' + model['quest'] + '"]') is not None), 'Missing quest definition')
    quest_root = ET.fromstring(files[quest_path]); quest_host = quest_root.find('./Skald/Quest')
    quest_ports = {p.get('Name') for p in quest_host.findall('Ports/Port')}
    stem = 'gm_combat_' + model['quest'] + '_' + tag
    if any(n.get('Name') == stem for n in nodes): raise ValueError('Combat already installed')
    objects = ET.fromstring(objects_blob)
    entities = {n.get('EntityGuid'): n for n in objects.findall('Entity')}
    project_entity = one((n for n in entities.values() if n.get('Name') == project.get('Name')), 'Missing project entity')
    actor_entity = entities[roles[source_plan['actor_role']]['registration']['guid']]
    home_link = one((n for n in actor_entity.findall('EntityLinks/Link') if n.get('Name') == 'home'), 'Missing converted actor Home link')
    home = entities[home_link.get('TargetGuid')]
    # Resolve the existing scheduler through the actor's installed idle anchor.
    wait_link = one((n for n in actor_entity.findall('EntityLinks/Link') if n.get('Name') == '_,schedulerWait'), 'Missing native actor scheduler link')
    anchor = entities[wait_link.get('TargetGuid')]
    delegate = one(anchor.findall('EntityLinks/Link[@Name="^delegate"]'), 'Missing scheduler delegate')
    scheduler = entities[delegate.get('TargetGuid')]
    if scheduler.get('EntityClass') != 'SmartAreaShape': raise ValueError('Unsupported combat scheduler type')
    template_id = scheduler.find('Properties').get('guidSmartAreaTemplate')
    with zipfile.ZipFile(native_game / 'Data/Tables.pak') as tables:
        templates = [e for path in tables.namelist()
            if path.lower().startswith('libs/tables/ai/smartentity/') and path.lower().endswith('.xml')
            for e in ET.fromstring(read(tables, path)).iter('SmartEntityTemplate')
            if e.get('DatabaseId') == template_id]
    template = one(templates, 'Missing native scheduler template')
    native_fight = template.find("BehaviorTemplates/SmartBehaviorTemplate[@Name='fightRepeated_template']/TreeLocation")
    if native_fight is None: raise ValueError('Scheduler does not register the native fight behavior')
    additions = []
    def asset(kind, name, entity=None, **attributes):
        if project.find('Assets/*[@Name="' + name + '"]') is not None: raise ValueError('Asset alias collision')
        ET.SubElement(project.find('Assets'), kind, Name=name, **attributes)
        if entity is not None:
            links = project_entity.find('EntityLinks')
            if links is None: links = ET.SubElement(project_entity, 'EntityLinks')
            label = "asset['" + name + "']"
            ET.SubElement(links, 'Link', Name=label, TargetId=entity.get('EntityId'), TargetGuid=entity.get('EntityGuid'))
            additions.append((project_entity.get('EntityGuid'), entity.get('EntityGuid'), label))
        return name
    role_assets = {r: asset('SoulAsset', stem + '_role_' + r,
                          SharedSoulGuids=b['attributes']['SharedSoulGuids']) for r, b in roles.items()}
    # A distance reference is spatial, not a behavior request. Export a native
    # point at the resolved Home hub rather than substituting the actor spawn.
    home_guid = native_guid(uuid.uuid5(uuid.NAMESPACE_URL, stem + ':' + home.get('EntityGuid')).int & ((1 << 64) - 1))
    if home_guid in entities: raise ValueError('Combat home reference GUID collision')
    home_point = ET.SubElement(objects, 'Entity', Name=stem + '_home', EntityClass='TagPoint',
        EntityGuid=home_guid, EntityId=str(max(int(n.get('EntityId', '0')) for n in entities.values()) + 1), Pos=home.get('Pos'))
    ET.SubElement(home_point, 'Properties', bSaved_by_game='0')
    home_asset = asset('TagPointAsset', stem + '_home', home_point)
    from campaign_combat_work_bindings import bind as bind_work
    from campaign_combat_work import emit as emit_work, validate as validate_work
    from campaign_combat_work_graph import wire as wire_work, after_privacy, after_dialogue
    work_assets, work_files = bind_work(stem, source_plan, bindings, roles, objects, home, native_game, asset, additions,
                                      compiled_scheduler, activity_template)
    # The local SmartObject host already owns the preparation/aftermath
    # phases. Register the shipped combat behavior there too, so the module
    # and compiled actor activity bind to the same validated host instead of
    # a second, world-area asset which failed resolution at runtime.
    scheduler_asset = work_assets['host']
    host_link = one(project_entity.findall('EntityLinks/Link[@Name="asset[\'' + scheduler_asset + '\']"]'),
                    'Missing local combat host link')
    scheduler = one((e for e in objects if e.get('EntityGuid') == host_link.get('TargetGuid')),
                    'Missing local combat host entity')
    table_path = one((p for p in work_files if '/smartEntity/' in p), 'Missing local behavior template')
    host_table = ET.fromstring(work_files[table_path])
    behavior_templates = host_table.find('.//SmartEntityTemplate/BehaviorTemplates')
    behavior_templates.append(copy.deepcopy(template.find("BehaviorTemplates/SmartBehaviorTemplate[@Name='fightRepeated_template']")))
    work_files[table_path] = xml(host_table)
    from campaign_behavior_schedule import connect as connect_schedule
    for role, record in roles.items():
        # Availability alone cannot make an actor select a native fight.
        # Include supporting fighters as well as the primary quest actor.
        connect_schedule(objects, additions, entities[record['registration']['guid']], scheduler,
                         'fightRepeated_template', 159, 'Fast', stem + '_fight_' + role,
                         compiled_scheduler, activity_template)
    work_files.update(emit_work(stem, source_plan['outcomes']['won']['aftermath']))
    validate_work(work_files, native_game)
    module_path = posixpath.dirname(entry_path) + '/' + stem + '.xml'
    changes = {module_path: emit(stem, source_plan), **work_files}
    with zipfile.ZipFile(native_game / 'Data/Scripts.pak') as scripts:
        # A local definition imports the native helper without depending on
        # Barbora's parent namespace being instantiated in the converted level.
        helper = read(scripts, 'Quests/Final/Barbora/utils/combat/fightstop.xml')
        if ET.fromstring(helper).find('./Skald/Module[@Name="fightstop"]') is None:
            raise ValueError('Native combat-stop helper changed')
        changes[module_path.removesuffix('.xml') + '/fightstop.xml'] = helper
        from campaign_combat_contracts import native_fight_effect
        helper, evidence = native_fight_effect(scripts)
        changes[module_path.removesuffix('.xml') + '/fighteffect.xml'] = helper
        source_plan['native_fight_reference'] = evidence
        native_tree = ET.fromstring(read(scripts, 'AI/' + native_fight.get('FileName')))
        if native_tree.find("BehaviorTree[@name='" + native_fight.get('TreeName') + "']/Root") is None:
            raise ValueError('Registered native combat tree is unavailable')
    ET.SubElement(host.find('Definitions'), 'Definition', File=posixpath.relpath(module_path, posixpath.dirname(entry_path)))
    fight = ET.SubElement(nodes, stem, Name=stem)
    for port, alias in [('actor', role_assets[source_plan['actor_role']]), ('player', 'player'),
                        ('scheduler', scheduler_asset), ('home', home_asset)]:
        ET.SubElement(fight, 'Asset', Name=port, Alias=alias)
    for i, role in enumerate(source_plan['partners']):
        ET.SubElement(fight, 'Asset', Name='partner_' + str(i), Alias=role_assets[role])
    from campaign_combat_contracts import validate_assets, validate_buffs
    combat_module = ET.fromstring(changes[module_path])
    source_plan['native_contracts'] = dict(
        assets=validate_assets(combat_module, fight, list(project.find('Assets')) + list(host.find('Assets'))),
        buffs=validate_buffs(combat_module, native_game, source_plan['buffs'] + [source_plan['wake_buff']]))
    edge(fight, quest.get('Name') + '.' + source_plan['party_objective'] + '_Completed', 'party_ready')
    objective_row = one((r for r in model['tables']['quest_objective']['rows'] if r['objective_name'] == objective), 'Missing dispatch objective')
    start_port = 'combat_start_' + objective
    if quest_host.find('Ports/Port[@Name="' + start_port + '"]') is None:
        ET.SubElement(quest_host.find('Ports'), 'Port', Name=start_port, Type='trigger', Direction='Out')
        edge(quest_host.find('Nodes/Output'), 'objective_' + objective_row['objective_id'] + '.OnStarted', start_port)
    edge(fight, quest.get('Name') + '.' + start_port, 'request')
    cancel_events = []
    for state in ('Done', 'Failed'):
        port = 'combat_cancel_' + state.lower()
        if quest_host.find('Ports/Port[@Name="' + port + '"]') is None:
            ET.SubElement(quest_host.find('Ports'), 'Port', Name=port, Type='trigger', Direction='Out')
            edge(quest_host.find('Nodes/Output'), 'quest_progress.On' + state, port)
        edge(fight, quest.get('Name') + '.' + port, 'cancel')
        cancel_events.append(quest.get('Name') + '.' + port)
    work_phases = wire_work(nodes, stem, source_plan, work_assets,
                           role_assets[source_plan['actor_role']], quest.get('Name'), fight, cancel_events)
    # Keep dialogue occupancy per instance so one finishing conversation cannot
    # clear a different active conversation. The last AfterPlay releases pending combat.
    busy = []
    definitions = {list(ET.fromstring(b).find('Skald'))[0].get('Name'): (p, list(ET.fromstring(b).find('Skald'))[0])
                   for p, b in files.items() if ET.fromstring(b).find('Skald') is not None and len(ET.fromstring(b).find('Skald'))}
    for n in list(nodes):
        if n.tag not in definitions or definitions[n.tag][1].tag not in ('FaderDialog', 'ForcedDialog'): continue
        from campaign_dialogue_activity import expose as expose_activity
        path, _ = definitions[n.tag]
        activity_root = ET.fromstring(changes.get(path, files[path]))
        activity_port = expose_activity(list(activity_root.find('Skald'))[0])
        changes[path] = xml(activity_root)
        s = ET.SubElement(nodes, 'State', Name=stem + '_busy_' + n.get('Name'), TypeT='bool')
        constant(s, 'DefaultValue', 'false'); edge(s, n.get('Name') + '.BeforePlay', 'SetTrue')
        edge(s, n.get('Name') + '.' + activity_port, 'SetTrue')
        waiter = ET.SubElement(nodes, 'SceneFinishedWaiter', Name=s.get('Name') + '_released')
        edge(waiter, n.get('Name') + '.AfterPlay', 'Enqueue')
        seq = ET.SubElement(nodes, 'TriggerSequence', Name=s.get('Name') + '_finished')
        edge(seq, waiter.get('Name') + '.OnFinished', 'Exec'); edge(s, seq.get('Name') + '.A', 'SetFalse')
        edge(fight, seq.get('Name') + '.B', 'dialogue_finished'); busy.append(s.get('Name') + '.State')
        from campaign_dialogue_activity import bind_scene_release
        bind_scene_release(nodes, s, n.get('Name'), activity_port)
    from campaign_quest_graph import any_of
    edge(fight, any_of(nodes, stem + '_talking', busy), 'dialogue_busy')
    def actions(actions, event, suffix):
        for i, action in enumerate(actions):
            name = stem + '_' + suffix + '_' + str(i)
            seq = ET.SubElement(nodes, 'TriggerSequence', Name=name); edge(seq, event, 'Exec')
            trigger = name + '.A'
            guards = []
            for j, g in enumerate(action['guards']):
                status = g['function'].removeprefix('IsObjective')
                if status not in ('Started', 'Completed', 'Canceled', 'Failed', 'Unchanged'): raise ValueError('Unknown objective guard')
                value = quest.get('Name') + '.' + g['objective'] + '_' + status
                if g['negate']:
                    inv = ET.SubElement(nodes, 'Function', Name=name + '_not_' + str(j), MethodName='math::boolean::Not', DeclaringType='math::boolean')
                    edge(inv, value, 'Value'); value = inv.get('Name') + '.bool'
                guards.append(value)
            if guards:
                gate = ET.SubElement(nodes, 'If', Name=name + '_guard')
                edge(gate, trigger, 'Exec'); edge(gate, all_of(nodes, name + '_and', guards), 'Condition'); trigger = gate.get('Name') + '.True'
            operation = {'StartObjective': 'start', 'CompleteObjective': 'complete', 'CancelObjective': 'cancel'}[action['operation']]
            port = operation + '_' + action['objective']
            if port not in quest_ports: raise ValueError('Unconverted combat objective effect: ' + port)
            edge(quest, trigger, port); event = name + '.B'
        return event
    for result in ('won', 'lost'):
        outcome = source_plan['outcomes'][result]
        ops = (source_plan['victory_actions'] if result == 'won' else []) + outcome['actions']
        source_event = stem + '.' + result
        if result == 'lost':
            merge = ET.SubElement(nodes, 'TriggerSequence', Name=stem + '_loss_events')
            edge(merge, stem + '.lost', 'Exec'); edge(merge, stem + '.distance_lost', 'Exec')
            source_event = merge.get('Name') + '.A'
        event = actions(ops, source_event, result)
        if outcome.get('aftermath'):
            event = after_privacy(nodes, stem, outcome['aftermath'], quest.get('Name'), event, work_phases)
        aliases = outcome['dialogue_aliases']
        if len(aliases) == 1: conversations = [(aliases[0], event)]
        else:
            # Follow the authored distance-condition branch rather than naming
            # a particular conversation in the conversion code.
            distance_aliases = [a for n in walk(outcome['schedule_source']) if n['op'] == 'DistanceCondition'
                for c in walk(n) if c['op'] == 'Expression'
                for a in re.findall(r"\.alias\s*=\s*'([^']+)'", attrs(c)['expressions'])]
            distance_alias = one(distance_aliases, 'Ambiguous distance-loss dialogue')
            normal_alias = one((a for a in aliases if a != distance_alias), 'Ambiguous loss dialogue')
            condition = attrs(one((n for n in walk(outcome['schedule_source']) if n['op'] == 'DistanceCondition'), 'Ambiguous follow-up distance test'))
            homes = [attrs(n)['Child'] for n in walk(outcome['schedule_source'])
                     if n['op'] == 'LinkTagFilter' and attrs(n)['tag'] == 'Home']
            if (condition['Origin'] not in ('', 'this.id') or condition['Negation'] != 'true'
                    or condition.get('ValueOnMiddle') != 'false' or condition['ReferencePt'] not in homes):
                raise ValueError('Unsupported follow-up distance reference')
            distance = ET.SubElement(nodes, 'Function', Name=stem + '_followup_distance',
                MethodName='wh::xgenaimodule::GetDistance', DeclaringType='wh::xgenaimodule')
            ET.SubElement(distance, 'Asset', Name='Origin', Alias=role_assets[source_plan['actor_role']])
            ET.SubElement(distance, 'Asset', Name='Target', Alias=home_asset)
            choose = ET.SubElement(nodes, 'IfFunction', Name=stem + '_choose_followup',
                MethodName='Control::Compare', DeclaringType='Control', TypeT='float')
            constant(choose, 'Op', 'Greater'); constant(choose, 'ValueB', float(condition['High']))
            edge(choose, distance.get('Name') + '.Distance', 'ValueA'); edge(choose, event, 'Exec')
            conversations = [(distance_alias, choose.get('Name') + '.True'), (normal_alias, choose.get('Name') + '.False')]
        for index, (alias, conversation_event) in enumerate(conversations):
            path, dialog = one(((p, d) for p, d in definitions.values() if d.find('.//Decision[@Alias="' + alias + '"]') is not None), 'Missing post-fight dialogue: ' + alias)
            dialog_root = ET.fromstring(changes.get(path, files[path])); dialog_host = list(dialog_root.find('Skald'))[0]
            dialog_host.tag = 'ForcedDialog'
            dialog_host.find('Dialogue').set('Initiator', 'NonPlayer')
            dialog_host.find('Dialogue').set('AllowGreeting', 'false')
            dialog_host.find('Dialogue').attrib.pop('Priority', None)
            changes[path] = xml(dialog_root)
            instance = one((n for n in nodes if n.tag == dialog_host.get('Name')), 'Missing dialogue instance')
            edge(instance, conversation_event, 'EnqueueDialogue')
            params_name = stem + '_' + result + '_' + str(index) + '_dialog_params'
            params = ET.SubElement(nodes, 'Function', Name=params_name, MethodName='wh::dialogmodule::CreateDialogParams', DeclaringType='wh::dialogmodule')
            ET.SubElement(params, 'Asset', Name='Participants', Alias=role_assets[source_plan['actor_role']])
            edge(instance, params_name + '.DialogParams', 'DialogParams')
            if outcome.get('aftermath'):
                after_dialogue(nodes, stem, instance, work_phases)
    changes[project_path], changes[entry_path], changes[quest_path] = xml(root), xml(entry), xml(quest_root)
    # Reject dangling graph references before writing a distributable package.
    for path in (module_path, entry_path, quest_path):
        h = list(ET.fromstring(changes[path]).find('Skald'))[0]
        names = [n.get('Name') for n in h.findall('Nodes/*')]
        if len(set(names)) != len(names): raise ValueError('Duplicate node name: ' + path)
        inputs = {n.get('Name') for n in h.findall('Ports/*') if n.get('Direction') == 'In'}
        inherited_edges = set()
        if path in files:
            inherited_edges = {e.get('From') for e in ET.fromstring(files[path]).findall('./Skald/*/Nodes/*/Edge')}
        for e in h.findall('Nodes/*/Edge'):
            source = e.get('From')
            if source not in inherited_edges and source.split('.')[0] not in set(names) | inputs:
                raise ValueError('Unresolved graph edge: ' + path + ':' + source)
    validate_scheduler_targets(compiled_scheduler)
    from campaign_behavior_schedule import validate_compiled
    validate_compiled(objects, compiled_scheduler, additions)
    level_changes = {'objects_mission0.xml': xml(objects), 'waitinglinks.xml': append_links(waiting_blob, additions),
                     'tables/ai/scheduler.xml': xml(compiled_scheduler)}
    return changes, level_changes, source_plan


def build(archive, level, source_level, output, model, tag, project_path, entry_path, native_game, mod=None):
    if output.exists(): raise FileExistsError('Choose a fresh combat output directory')
    output.parent.mkdir(parents=True, exist_ok=True)
    original_archive = archive
    speech_stage = output.parent / (output.name + '-speech')
    request, _ = request_site(model, tag)
    source_plan = plan(model, request)
    with zipfile.ZipFile(archive) as pak:
        available = {d.get('Alias') for n in pak.namelist() if n.startswith('Quests/') and n.endswith('.xml')
                     for d in ET.fromstring(pak.read(n)).iter('Decision')}
    missing = sorted({o['aftermath']['bark']['alias'] for o in source_plan['outcomes'].values() if o.get('aftermath')} - available)
    if missing:
        if mod is None:
            raise ValueError('Provide --mod to import missing bark recordings and localization: ' + ', '.join(missing))
        from campaign_dialogue import load_many
        from build_actor_dialogues_test import build as import_dialogues
        from types import SimpleNamespace
        source_game = source_level.parents[3]
        topics = [m['start_topic'] for m in load_many(source_game, [(alias, None) for alias in missing])]
        model_file = output.parent / (output.name + '-quest.json')
        model_file.write_text(json.dumps(model), encoding='utf-8')
        with zipfile.ZipFile(archive) as pak:
            container = list(ET.fromstring(pak.read(entry_path)).find('Skald'))[0]
            quest = one((n for n in container.find('Nodes') if n.tag == model['quest']), 'Missing quest instance')
        import_dialogues(SimpleNamespace(source=source_game, target=native_game, mod=mod, archive=archive,
            output=speech_stage, quest_ir=[model_file], start_topic=topics, namespace='gm_combat_' + model['quest'] + '_' + tag + '_speech',
            kind='Dialog', container=entry_path.removeprefix('Quests/'), container_name=container.get('Name'),
            activation=quest.get('Name') + '.started', skill_upgrade=[], participant_asset=[]))
        archive = speech_stage / 'package/Data/gluemappertravel.pak'
    bindings = source_binding(model, source_level)
    with zipfile.ZipFile(archive) as pak:
        files = {n: pak.read(n) for n in pak.namelist() if n.startswith('Quests/') and n.endswith('.xml')}
    with zipfile.ZipFile(level) as pak:
        level_files = {n: read(pak, n) for n in ('objects_mission0.xml', 'waitinglinks.xml', 'tables/ai/scheduler.xml')}
    changes, level_changes, source_plan = convert(files, level_files, bindings, model, tag,
                                                project_path, entry_path, native_game)
    output.mkdir(parents=True, exist_ok=False)
    rewrite(archive, output / archive.name, changes)
    rewrite(level, output / level.name, level_changes)
    if missing:
        import shutil
        for path in (speech_stage / 'package').rglob('*.pak'):
            if path == archive: continue
            target = output / path.relative_to(speech_stage / 'package')
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(path, target)
    for path in output.rglob('*.pak'):
        with zipfile.ZipFile(path) as pak:
            if len(pak.namelist()) != len(set(n.lower() for n in pak.namelist())) or pak.testzip():
                raise ValueError('Invalid package archive: ' + str(path))
    report = dict(plan=source_plan, changed_quest_files=list(changes), changed_level_files=list(level_changes),
        before={str(p): digest(p) for p in (original_archive, level)},
        packages={p.relative_to(output).as_posix(): digest(p) for p in output.rglob('*.pak')}, runtime_verified=False,
        remaining_schedule_conversion=['Verify source daycycle priority and interruption policy against native EnableBehavior scheduling'],
        upgrades=['Source instant tool manipulation uses acknowledged native hand-item actions'],
        imported_barks=missing, speech_report=str(speech_stage / 'report.json') if missing else None,
        validation_required=['Native work scheduling and action acknowledgements', 'Save/load during work and combat'])
    (output / 'report.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    return report


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    for n in ('archive', 'level', 'source-level', 'output', 'model', 'native-game'):
        p.add_argument('--' + n, type=Path, required=True)
    for n in ('tag', 'project-path', 'entry-path'):
        p.add_argument('--' + n, required=True)
    p.add_argument('--mod', type=Path, help='Existing mod supplies audio/localization baselines for missing source barks')
    args = vars(p.parse_args()); args['model'] = json.loads(args['model'].read_text(encoding='utf-8'))
    result = build(**args)
    print(json.dumps({k: v for k, v in result.items() if k != 'plan'}, indent=2))
