"""Converter C5: cutscene policy by category, callback programs and profile switching.

A KCD1 quest controller asks for a scene with a `cutscene` message and owns a
callback tree `cutscene_<alias>` that holds what the scene changes. The picture
and the changes are separate:

    category   computed, never chosen: the alias has a prerendered .usm -> video;
               a source profile `<quest>_cutscene_<alias>` exists -> in_engine;
               the request carries dialogFadeIn(true) -> dialogue; else fader
    picture    video: one RenderedCutscene row and one Bink file per alias, played
               by a native CutsceneHandler. Other categories are residue here.
    callback   runs once when the handler finishes, which is how a cutscene ends
               whether it played through or was skipped

This module lowers, of a callback tree, exactly what C5 owns: objective actions
(through the quest's own input ports, so nothing bypasses the quest), profile
switches (`EnableProfile` -> the retail `streamprofileshandling` helper) and
their acknowledgement (`ProfileLoadedGate` -> the helper's `onloaded`). Every
other operation is listed as a typed residue row for the controller converter
(C2) or the Lua converter (C4); none is dropped. An owned operation that
follows a deferred operation which can block is not lowered either.

Profiles: each source profile is accounted layer by layer and entity by entity
(`profile_plan`). Layers shared with the profile it replaces stay in the flat
level. Entities of its own layers that the level already holds can be moved
into a `gm_<profile>` layer (`register_profiles`); the rest is residue.

Nothing here is runtime-verified. Developer tooling; never imported by Setup.
"""
from collections import Counter
import copy
import hashlib
import re
import xml.etree.ElementTree as ET

from campaign_quest_bridge import OBJECTIVE_ACTIONS
from campaign_quest_graph import constant, definition, edge, identifier, objective_identifier, xml
from quest_import import literal

CONVERTER = 'C5'
VIDEO = re.compile(r'videos/([^/]+)/cin_(\d+)_(.+)\.usm\Z', re.I)
FIELD = re.compile(r"(\w+)\s*\(\s*((?:'[^']*'|[^()])*?)\s*\)")
ROOT = 'Videos/gluemapper/'
SEND = ('InstantSendMessageToNPC', 'SendMessageToNPC')
TRANSPARENT = ('Root', 'Behavior', 'Sequence')
# Deferred operations that return at once, by reading their source shape: messages, buffs, variable and
# reference bookkeeping. **Guess:** GraphSearch finishes in the tick that starts it.
INSTANT = {'InstantSendMessageToNPC', 'RemoveBuffs', 'AddBuff', 'ExecuteLua', 'Expression', 'VarOperation', 'For',
           'VariableExistsGate', 'Then', 'Else', 'AtomicDecorator', 'GraphSearch', 'LinkTagFilter', 'EvaLLyzer',
           'Success', 'Sequence', 'SetQuestObjective', 'EnableProfile'}
OWNERS = {'ExecuteLua': 'C4'}
STREAMING = 'streamprofileshandling'


class Unsupported(ValueError):
    pass


# ---------------------------------------------------------------- source side

def video_sources(names_by_archive):
    """{quest: {alias: dict(archive, entry, id)}} from the source video archives' entry names."""
    found = {}
    for archive, names in sorted(names_by_archive.items()):
        for name in names:
            match = VIDEO.fullmatch(name.replace('\\', '/'))
            if not match:
                continue
            quest, alias = match.group(1).lower(), match.group(3)
            if alias in found.setdefault(quest, {}):
                raise Unsupported('Two source videos for one scene: ' + alias)
            found[quest][alias] = dict(archive=archive, entry=name, id=match.group(2))
    return found


def own_document(model):
    return (model.get('behavior_documents') or {}).get('libs/ai/quests/' + model['quest'].lower() + '.xml', dict(trees={}))


def fields(values):
    """{field: argument text} of a message's `values`, in source spelling."""
    return {name: argument.strip().strip("'") for name, argument in FIELD.findall(values or '')}


def requests(model):
    """Every `cutscene` message the quest's own controller sends, in tree order."""
    found = []

    def visit(node, tree, path):
        attributes = node.get('attributes', {})
        if node['op'] in SEND and literal(attributes.get('type', '')) == 'cutscene':
            sent = fields(literal(attributes.get('values', '')))
            alias = sent.get('alias') or sent.get('name')
            found.append(dict(tree=tree, path=path, alias=alias, fields=sent, target=literal(attributes.get('target', ''))))
        for index, child in enumerate(node.get('children', [])):
            visit(child, tree, path + '/' + str(index))
    for name, tree in own_document(model)['trees'].items():
        visit(tree['root'], name, 'Root')
    return found


def categorise(alias, sent, videos, profiles, quest):
    if alias in videos:
        return 'video'
    if (quest + '_cutscene_' + alias).lower() in {p.lower() for p in profiles}:
        return 'in_engine'
    if any(f.get('dialogFadeIn') == 'true' for f in sent):
        return 'dialogue'
    return 'fader'


def scenes(model, videos, profiles, selection):
    """One record per requested alias: category, callback tree, and whether C5 converts it."""
    grouped = {}
    for request in requests(model):
        if not request['alias']:
            raise Unsupported('Scene request without an alias in ' + request['tree'])
        grouped.setdefault(request['alias'], []).append(request)
    trees = own_document(model)['trees']
    records = []
    for alias, sent in grouped.items():
        category = categorise(alias, [r['fields'] for r in sent], videos, profiles, model['quest'])
        record = dict(alias=alias, category=category, requests=[dict(tree=r['tree'], path=r['path'], fields=r['fields'])
                                                                 for r in sent],
                      callback='cutscene_' + alias if 'cutscene_' + alias in trees else None,
                      video=videos.get(alias))
        if category == 'video' and alias in selection:
            record['status'] = 'converted'
        else:
            record['status'] = 'residue'
            record['residue'] = dict(video='video_not_selected', in_engine='scene_handoff', dialogue='dialogue_scene',
                                     fader='fader_scene')[category]
        records.append(record)
    unknown = sorted(set(selection) - {r['alias'] for r in records if r['category'] == 'video'})
    if unknown:
        raise Unsupported('Selected scenes are not requested videos: ' + ', '.join(unknown))
    return records


# ---------------------------------------------------------------- callback programs

def _instant(node, library):
    """Whether a deferred subtree returns at once: only known instant operations, includes resolved."""
    if node['op'] == 'IncludeTree':
        target = library.get(literal(node['attributes'].get('Name', '')))
        return target is not None and _instant(target['root'], library)
    if node['op'] not in INSTANT and node['op'] not in TRANSPARENT:
        return False
    return all(_instant(child, library) for child in node.get('children', []))


def program(model, alias, library=None):
    """The callback tree as ordered steps.

    Steps: dict(kind='objective', verb, objective) | dict(kind='profile', enable, disable) |
    dict(kind='await', profile, steps=[...]) | dict(kind='deferred', op, path, owner, blocking).
    Returns dict(steps, counts) or None when the quest has no such tree.
    """
    tree = own_document(model)['trees'].get('cutscene_' + alias)
    if tree is None:
        return None
    library = library if library is not None else {name: body for document in (model.get('behavior_documents') or {}).values()
                                                   for name, body in document['trees'].items()}
    objectives = {r['objective_name'] for r in model['tables']['quest_objective']['rows']}
    blocked = [False]

    def deferred(node, path, reason=None):
        blocking = not _instant(node, library)
        step = dict(kind='deferred', op=node['op'], path=path, owner=OWNERS.get(node['op'], 'C2'), blocking=blocking,
                    operations=sum(1 for n in (node, *_descendants(node)) if n['op'] not in TRANSPARENT))
        if reason:
            step['reason'] = reason
        if blocking:
            blocked[0] = True
        return step

    def walk(node, path):
        op, attributes = node['op'], {k: literal(v) for k, v in node.get('attributes', {}).items()}
        children = node.get('children', [])
        if op in TRANSPARENT:
            return [step for index, child in enumerate(children) for step in walk(child, path + '/' + str(index))]
        if blocked[0] and op in ('SetQuestObjective', 'EnableProfile', 'ProfileLoadedGate'):
            return [deferred(node, path, 'follows a deferred operation that can block')]
        if op == 'SetQuestObjective':
            quest, function = attributes.get('quest', ''), attributes.get('function', '')
            if quest not in ('', model['quest']) or function not in OBJECTIVE_ACTIONS or attributes.get('objective') not in objectives \
                    or children or set(attributes) - {'quest', 'objective', 'function', 'saveVersion'}:
                return [deferred(node, path, 'not a plain objective action of this quest')]
            return [dict(kind='objective', verb=OBJECTIVE_ACTIONS[function], objective=attributes['objective'], path=path)]
        if op == 'EnableProfile':
            enable, disable = attributes.get('profileEnable', ''), attributes.get('profileDisable', '')
            if children or set(attributes) - {'profileEnable', 'profileDisable', 'saveVersion'} or not (enable or disable) or enable == disable:
                return [deferred(node, path, 'not a plain profile switch')]
            for name in (enable, disable):
                if name: identifier(name)
            return [dict(kind='profile', enable=enable or None, disable=disable or None, path=path)]
        if op == 'ProfileLoadedGate':
            if attributes.get('NegateTo') != 'false' or attributes.get('RunLogic') != 'KeepRunning' or not attributes.get('LayerName') \
                    or set(attributes) - {'LayerName', 'NegateTo', 'RunLogic', 'saveVersion'}:
                return [deferred(node, path, 'not a plain wait for a loaded profile')]
            inner = [step for index, child in enumerate(children) for step in walk(child, path + '/' + str(index))]
            return [dict(kind='await', profile=identifier(attributes['LayerName']), steps=inner, path=path)]
        return [deferred(node, path)]

    steps = walk(tree['root'], 'Root')
    flat = list(_flat(steps))
    return dict(alias=alias, tree='cutscene_' + alias, steps=steps,
                counts=dict(Counter(s['kind'] for s in flat)),
                source_operations=sum(1 for _ in _descendants(tree['root']) if _['op'] not in TRANSPARENT),
                deferred_operations=sum(s['operations'] for s in flat if s['kind'] == 'deferred'))


def _descendants(node):
    for child in node.get('children', []):
        yield child
        yield from _descendants(child)


def _flat(steps):
    for step in steps:
        yield step
        if step['kind'] == 'await':
            yield from _flat(step['steps'])


def program_profiles(programs):
    names = []
    for found in programs:
        for step in _flat(found['steps']):
            for name in ([step.get('enable'), step.get('disable')] if step['kind'] == 'profile' else
                         [step['profile']] if step['kind'] == 'await' else []):
                if name and name not in names:
                    names.append(name)
    return names


# ---------------------------------------------------------------- Skald emission

def cutscene_name(quest, alias):
    return identifier('gm_' + quest + '_' + alias)


def holder_alias(quest, alias):
    return identifier('gm_' + quest + '_scene_' + alias)


def profile_name(source):
    return 'gm_' + source


def emit(model, records, programs, streaming_path):
    """(module blob, report): the scene module of one quest.

    Ports: In trigger `play_<alias>`; Out trigger `callback_<alias>` (the scene ended; fires once per
    request, before anything else) and `finished_<alias>` (the lowered part of the callback is done);
    Out trigger `<verb>_<objective>` for every objective action, to be wired to the quest's own input.
    """
    quest = model['quest']
    name = identifier('gm_' + quest + '_scenes')
    root, module = definition('Module', name)
    ET.SubElement(ET.SubElement(module, 'Definitions'), 'Definition', File=streaming_path)
    ports, nodes = ET.SubElement(module, 'Ports'), ET.SubElement(module, 'Nodes')
    assets = ET.SubElement(module, 'Assets')
    output = ET.SubElement(nodes, 'Output', Name='Output')
    by_alias = {p['alias']: p for p in programs}
    wiring, world = [], []
    profiles = {}

    def port(port_name, direction, source=None):
        if not any(p.get('Name') == port_name for p in ports):
            ET.SubElement(ports, 'Port', Name=port_name, Direction=direction, Type='trigger')
        if source is not None:
            edge(output, source, port_name)

    def profile(source):
        if source not in profiles:
            instance = identifier('profile_' + source)
            ET.SubElement(assets, 'ProfileAsset', Name=instance + '_asset', AssetProfiles=profile_name(source))
            ET.SubElement(ET.SubElement(nodes, STREAMING, Name=instance), 'Asset', Name='profiles', Alias=instance + '_asset')
            state = ET.SubElement(nodes, 'State', Name=instance + '_loaded', TypeT='bool')
            constant(state, 'DefaultValue', 'false')
            edge(state, instance + '.onloaded', 'SetTrue'); edge(state, instance + '.onunloaded', 'SetFalse')
            profiles[source] = instance
        return profiles[source]

    class Chain:
        """Ordered triggers: each use takes the next output of a TriggerSequence, chaining when one is full."""
        def __init__(self, stem, source):
            self.stem, self.count, self.index = stem, 0, 0
            self.node = self._new(source)

        def _new(self, source):
            node = ET.SubElement(nodes, 'TriggerSequence', Name=self.stem + '_' + str(self.count))
            edge(node, source, 'Exec')
            self.count += 1; self.index = 0
            return node

        def next(self):
            if self.index == 25:
                self.node = self._new(self.node.get('Name') + '.Z')
            self.index += 1
            return self.node.get('Name') + '.' + 'ABCDEFGHIJKLMNOPQRSTUVWXYZ'[self.index - 1]

    def lower(steps, chain, stem):
        for step in steps:
            if step['kind'] == 'objective':
                out = step['verb'] + '_' + objective_identifier(step['objective'])
                port(out, 'Out', chain.next())
                if dict(port=out, quest=quest, input=out) not in wiring:
                    wiring.append(dict(port=out, quest=quest, input=out))
            elif step['kind'] == 'profile':
                # Source attribute order: enable, then disable.
                if step['enable']:
                    edge(nodes.find(STREAMING + "[@Name='" + profile(step['enable']) + "']"), chain.next(), 'streamprofiles')
                if step['disable']:
                    edge(nodes.find(STREAMING + "[@Name='" + profile(step['disable']) + "']"), chain.next(), 'unstreamprofiles')
            elif step['kind'] == 'await':
                instance = profile(step['profile'])
                wait = identifier(stem + '_wait_' + str(len(nodes.findall('State'))))
                waiting = ET.SubElement(nodes, 'State', Name=wait, TypeT='bool')
                constant(waiting, 'DefaultValue', 'false')
                edge(waiting, chain.next(), 'SetTrue')
                now = ET.SubElement(nodes, 'If', Name=wait + '_now')
                edge(now, chain.next(), 'Exec'); edge(now, instance + '_loaded.State', 'Condition')
                later = ET.SubElement(nodes, 'If', Name=wait + '_later')
                edge(later, instance + '.onloaded', 'Exec'); edge(later, wait + '.State', 'Condition')
                # Loaded already or loaded later: either way the rest runs once, behind the acknowledgement.
                chain = Chain(wait + '_then', wait + '_now.True')
                edge(chain.node, wait + '_later.True', 'Exec')
                edge(waiting, chain.next(), 'SetFalse')
                chain = lower(step['steps'], chain, stem)
        return chain

    emitted = []
    for record in records:
        if record['status'] != 'converted':
            continue
        alias = identifier(record['alias'])
        stem = 'scene_' + alias
        port('play_' + alias, 'In')
        pending = ET.SubElement(nodes, 'State', Name=stem + '_pending', TypeT='bool')
        constant(pending, 'DefaultValue', 'false')
        edge(pending, 'play_' + alias, 'SetTrue')
        handler = ET.SubElement(nodes, 'CutsceneHandler', Name=stem + '_play')
        ET.SubElement(handler, 'Asset', Name='CutsceneHolder', Alias=holder_alias(quest, alias))
        ET.SubElement(assets, 'CutsceneHolderAsset', Name=holder_alias(quest, alias))
        edge(handler, 'play_' + alias, 'EnqueueCutscene')
        # A cutscene ends once, played through or skipped: the callback follows the end, not the picture.
        ended = ET.SubElement(nodes, 'If', Name=stem + '_ended')
        edge(ended, stem + '_play.OnFinished', 'Exec'); edge(ended, stem + '_pending.State', 'Condition')
        chain = Chain(stem + '_callback', stem + '_ended.True')
        edge(pending, chain.next(), 'SetFalse')
        port('callback_' + alias, 'Out', chain.next())
        found = by_alias.get(record['alias'])
        if found is not None:
            chain = lower(found['steps'], chain, stem)
        port('finished_' + alias, 'Out', chain.next())
        world.append(dict(kind='CutsceneHolder', alias=holder_alias(quest, alias), cutscene=cutscene_name(quest, alias)))
        emitted.append(record['alias'])
    report = dict(module=name, scenes=emitted, wiring=wiring, world_requirements=world,
                  profiles={source: dict(instance=instance, asset=instance + '_asset', native=profile_name(source))
                            for source, instance in profiles.items()},
                  runtime_verified=False)
    return xml(root), report


def attach(entry_blob, module_blob, definition_path, report, quest_ports):
    """Instantiate the scene module beside the quest and wire its objective outputs to the quest's inputs."""
    root = ET.fromstring(entry_blob)
    hosts = list(root.find('Skald'))
    if len(hosts) != 1 or hosts[0].tag not in ('Level', 'Project'):
        raise ValueError('Expected one Level or Project container')
    host = hosts[0]
    definitions, nodes = host.find('Definitions'), host.find('Nodes')
    name = report['module']
    if any(n.get('Name') == name for n in nodes) or any(d.get('File') == definition_path for d in definitions):
        raise ValueError('Scene module already registered: ' + name)
    declared = {p.get('Name'): (p.get('Direction'), p.get('Type'))
                for p in ET.fromstring(module_blob).iterfind('./Skald/Module/Ports/Port')}
    for wire in report['wiring']:
        quest = [n for n in nodes if n.get('Name') == wire['quest']]
        if len(quest) != 1 or quest_ports.get(wire['input']) != ('In', 'trigger') or declared.get(wire['port']) != ('Out', 'trigger'):
            raise ValueError('Quest does not take the scene action ' + wire['input'])
        edge(quest[0], name + '.' + wire['port'], wire['input'])
    ET.SubElement(definitions, 'Definition', File=definition_path)
    ET.SubElement(nodes, name, Name=name)
    return xml(root)


# ---------------------------------------------------------------- movies

def movie_rows(native_xml, records, quest):
    """KCD2 cutscene table with one RenderedCutscene row per converted video; returns (blob, rows)."""
    root = ET.fromstring(native_xml)
    table = root.find('./Cutscenes')
    if table is None:
        raise ValueError('Native cutscene table format changed')
    existing = {e.get('Name') for e in table}
    rows = []
    for record in records:
        if record['status'] != 'converted':
            continue
        name = cutscene_name(quest, record['alias'])
        if name in existing:
            raise ValueError('Cutscene already registered: ' + name)
        row = ET.SubElement(table, 'RenderedCutscene', Name=name, Root=ROOT + quest + '/' + record['alias'])
        ET.SubElement(ET.SubElement(row, 'Profiles'), 'Profile', Type='Default', FileName='cinematic')
        rows.append(dict(name=name, root=row.get('Root'), file=row.get('Root') + '/cinematic.bk2',
                         source=record['video']))
    return ET.tostring(root, encoding='utf-8', xml_declaration=True), rows


def media_expectation(streams, frames):
    """What an encoded movie must equal, from the demuxed source's probe."""
    video = next(s for s in streams if s['codec_type'] == 'video')
    return dict(width=video['width'], height=video['height'], r_frame_rate=video['r_frame_rate'], nb_frames=str(frames))


# ---------------------------------------------------------------- profiles

def source_profiles(whdata):
    """{name: dict(id, layers, navigation, grouped)} of a source level's profile manager."""
    root = whdata if isinstance(whdata, ET.Element) else ET.fromstring(whdata)
    grouped = {p.text for p in root.iterfind('.//GameProfileGroups//Profiles/Profile')}
    found = {}
    for profile in root.iter('GameProfile'):
        name = profile.findtext('Name')
        if name in found:
            raise Unsupported('Duplicate source profile: ' + name)
        found[name] = dict(id=profile.findtext('Id'), layers=[l.text.strip() for l in profile.findall('GameLayers/GameLayer')],
                           navigation=profile.findtext('HasNavigation') == '1',
                           svo=profile.findtext('NeedsSVORebuild') == '1', grouped=profile.findtext('Id') in grouped)
    return found


def profile_plan(switches, profiles, layer_entities, level_guids, native_guid):
    """Account every layer and entity of the profiles a quest's scenes switch.

    switches: [(enable, disable)] in source order. layer_entities: {layer: [dict(guid, kind, name)]}.
    level_guids: native GUIDs the converted level holds. A layer that the enabled profile shares with the
    one it replaces stays flat. Returns {profile: record}.
    """
    names = [n for pair in switches for n in pair if n]
    missing = sorted({n for n in names if n not in profiles})
    if missing:
        raise Unsupported('Unknown source profiles: ' + ', '.join(missing))
    partner = {}
    for enable, disable in switches:
        if enable and disable:
            partner.setdefault(enable, set()).add(disable); partner.setdefault(disable, set()).add(enable)
    plan = {}
    for name in dict.fromkeys(names):
        source = profiles[name]
        shared = {l for other in partner.get(name, ()) for l in profiles[other]['layers']} & set(source['layers'])
        layers, residue = [], []
        for layer in source['layers']:
            if layer not in layer_entities:
                raise Unsupported('Source layer file is missing: ' + layer)
            entities = layer_entities[layer]
            if layer in shared:
                layers.append(dict(layer=layer, status='shared', entities=len(entities)))
                continue
            present, absent = [], []
            for entity in entities:
                guid = entity.get('guid')
                native = native_guid(guid) if guid else None
                (present if native is not None and native in level_guids else absent).append(dict(entity, native=native))
            layers.append(dict(layer=layer, status='own', entities=len(entities), in_level=len(present),
                               kinds=dict(sorted(Counter(e['kind'] for e in entities).items())),
                               missing_kinds=dict(sorted(Counter(e['kind'] for e in absent).items())),
                               move=sorted(e['native'] for e in present)))
            if absent:
                residue.append(dict(kind='profile_layer_unconverted', layer=layer, entities=len(absent),
                                    kinds=dict(sorted(Counter(e['kind'] for e in absent).items()))))
        if source['navigation']:
            residue.append(dict(kind='profile_nav_variant', reason='the static navigation of the flat level stays in use'))
        if source['grouped']:
            residue.append(dict(kind='profile_group_conflict', reason='member of a mutually exclusive source group'))
        plan[name] = dict(source=name, source_id=source['id'], native=profile_name(name), layers=layers, residue=residue,
                          layer_name=identifier(profile_name(name) + '_layer'),
                          totals=dict(layers=len(layers), shared=sum(l['status'] == 'shared' for l in layers),
                                      entities=sum(l['entities'] for l in layers if l['status'] == 'own'),
                                      in_level=sum(l.get('in_level', 0) for l in layers),
                                      unconverted=sum(r.get('entities', 0) for r in residue)))
    return plan


def register_profiles(files, plan):
    """Move the planned entities out of the flat mission into one layer per profile and register the profiles.

    files: 'objects_mission0.xml', 'leveldata.xml' and optionally 'whdata_1' of a converted level. Only an
    entity's place changes: the same element, GUID and transform, now in `layers/<layer>.xml`.
    Returns (files, report).
    """
    result = dict(files)
    mission = ET.fromstring(files['objects_mission0.xml'])
    level = ET.fromstring(files['leveldata.xml'])
    layers = level.find('Layers')
    if layers is None: layers = ET.SubElement(level, 'Layers')
    manager = ET.fromstring(files.get('whdata_1', b'<Root/>'))
    profiles = manager.find('GameProfileManager')
    if profiles is None: profiles = ET.SubElement(manager, 'GameProfileManager')
    records = profiles.find('GameProfiles')
    if records is None: records = ET.SubElement(profiles, 'GameProfiles')
    if profiles.find('GameProfileGroups') is None: ET.SubElement(profiles, 'GameProfileGroups')
    next_layer = max((int(e.get('Id')) for e in layers), default=0) + 1
    next_profile = max((int(e.findtext('Id')) for e in records), default=0) + 1
    names, layer_names = {e.findtext('Name') for e in records}, {e.get('Name') for e in layers}
    by_guid = {}
    for entity in mission.iter('Entity'):
        by_guid.setdefault(entity.get('EntityGuid'), []).append(entity)
    parents = {child: parent for parent in mission.iter() for child in parent}
    wanted = [guid for record in plan.values() for layer in record['layers'] for guid in layer.get('move', ())]
    if len(set(wanted)) != len(wanted):
        raise ValueError('An entity is planned into two profiles')
    report = []
    for record in plan.values():
        name, layer = record['native'], record['layer_name']
        if name in names or layer in layer_names or 'layers/' + layer + '.xml' in result:
            raise ValueError('Profile already registered: ' + name)
        if next_layer > 65535:
            raise ValueError('Layer ID exceeds the native range')
        root = ET.Element('Objects')
        moved = []
        for source in record['layers']:
            for guid in source.get('move', ()):
                found = by_guid.get(guid, [])
                if len(found) != 1:
                    raise ValueError('Planned entity is missing or ambiguous in the level: ' + str(guid))
                entity = found[0]
                parents[entity].remove(entity)
                entity.set('Layer', layer)
                root.append(entity)
                moved.append(guid)
        profile = ET.SubElement(records, 'GameProfile')
        ET.SubElement(profile, 'Name').text = name
        ET.SubElement(profile, 'Id').text = str(next_profile)
        # The flat level's navigation stays in use (residue profile_nav_variant).
        for field in ('HasNavigation', 'NeedsSVORebuild', 'DoesPrepareSOAnimData', 'AllowRuntimeAnimValidationFallback'):
            ET.SubElement(profile, field).text = '0'
        ET.SubElement(ET.SubElement(profile, 'GameLayers'), 'GameLayer').text = layer
        ET.SubElement(layers, 'Layer', Name=layer, Id=str(next_layer), Specs='-1', Physics='0')
        result['layers/' + layer + '.xml'] = xml(root)
        report.append(dict(source_profile=record['source'], profile=name, profile_id=next_profile, layer=layer,
                           layer_id=next_layer, moved=len(moved), runtime_verified=False))
        names.add(name); layer_names.add(layer); next_layer += 1; next_profile += 1
    result['objects_mission0.xml'] = xml(mission)
    result['leveldata.xml'] = xml(level)
    result['whdata_1'] = xml(manager)
    return result, report


# ---------------------------------------------------------------- ledger

def ledger(model, records, programs, plan, emitted, rows):
    """scenes + profiles ledger of one quest: every request, operation, layer and entity is counted once."""
    residue = []
    for record in records:
        if record['status'] != 'converted':
            residue.append(dict(kind=record['residue'], alias=record['alias'], category=record['category'],
                                requests=len(record['requests'])))
        for request in record['requests']:
            for field in ('saveGameQuest', 'saveGameObjective'):
                if field in request['fields'] and record['status'] == 'converted':
                    residue.append(dict(kind='request_save_deferred', alias=record['alias'], field=field,
                                        value=request['fields'][field], owner='C2'))
    for found in programs:
        for step in _flat(found['steps']):
            if step['kind'] == 'deferred':
                residue.append(dict(kind='callback_op_deferred', alias=found['alias'], op=step['op'], path=step['path'],
                                    owner=step['owner'], blocking=step['blocking'], operations=step['operations'],
                                    **({'reason': step['reason']} if 'reason' in step else {})))
    for record in plan.values():
        residue.extend(dict(r, profile=record['source']) for r in record['residue'])
    lowered = Counter(s['kind'] for found in programs for s in _flat(found['steps']) if s['kind'] != 'deferred')
    return dict(
        schema=1, converter=CONVERTER, quest=model['quest'],
        scenes=dict(requests=sum(len(r['requests']) for r in records), aliases=len(records),
                    categories=dict(sorted(Counter(r['category'] for r in records).items())),
                    converted=[r['alias'] for r in records if r['status'] == 'converted'],
                    records=[dict(alias=r['alias'], category=r['category'], status=r['status'], callback=r['callback'],
                                  requests=len(r['requests']), video=r['video']) for r in records]),
        callbacks=[dict(alias=p['alias'], tree=p['tree'], source_operations=p['source_operations'],
                        lowered=dict(sorted(Counter(s['kind'] for s in _flat(p['steps']) if s['kind'] != 'deferred').items())),
                        deferred_operations=p['deferred_operations']) for p in programs],
        lowered=dict(sorted(lowered.items())),
        movies=rows,
        profiles={name: dict(native=r['native'], source_id=r['source_id'], totals=r['totals'],
                             layers=[{k: v for k, v in l.items() if k != 'move'} for l in r['layers']])
                  for name, r in plan.items()},
        module=dict(name=emitted['module'], wiring=emitted['wiring'], world_requirements=emitted['world_requirements'],
                    profiles=emitted['profiles']),
        residue=residue,
        residue_by_kind=dict(sorted(Counter(r['kind'] for r in residue).items())),
        runtime_verified=False)


def equivalence(model, result, quest_ports, media=None):
    """Layer 1: compare the conversion with the source, item by item. A mismatch is a failure.

    The expectation is derived here by an independent pass over the source trees, not read from the
    converter's own counts. media maps an alias to (expected, encoded stream facts); without it the
    picture itself is not compared and each converted video counts as `media_not_run`.
    """
    failures, checked = [], Counter()

    def check(category, condition, message):
        checked[category] += 1
        if not condition:
            failures.append(dict(category=category, message=message))

    sent = Counter()
    for tree in own_document(model)['trees'].values():
        stack = [tree['root']]
        while stack:
            node = stack.pop()
            stack.extend(node.get('children', []))
            if node['op'] in SEND and literal(node['attributes'].get('type', '')) == 'cutscene':
                match = re.search(r"(?:alias|name)\s*\(\s*'([^']+)'", literal(node['attributes'].get('values', '')))
                sent[match.group(1) if match else None] += 1
    records = {r['alias']: r for r in result['records']}
    for alias, count in sent.items():
        check('requests', alias in records and len(records[alias]['requests']) == count, 'request count of ' + str(alias))
    check('requests', set(records) == set(sent), 'aliases differ from the requests')
    for alias, record in records.items():
        check('categories', record['category'] in ('video', 'in_engine', 'dialogue', 'fader')
              and (record['status'] == 'converted') != ('residue' in record), 'category or status of ' + alias)
    programs = {p['alias']: p for p in result['programs']}
    for alias, record in records.items():
        if record['status'] != 'converted':
            continue
        check('callbacks', (record['callback'] is None) == (alias not in programs), 'callback tree of ' + alias)
        if alias not in programs:
            continue
        tree = own_document(model)['trees']['cutscene_' + alias]['root']
        operations = Counter(n['op'] for n in _descendants(tree) if n['op'] not in TRANSPARENT)
        flat = list(_flat(programs[alias]['steps']))
        lowered = Counter({'objective': 'SetQuestObjective', 'profile': 'EnableProfile', 'await': 'ProfileLoadedGate'}[s['kind']]
                          for s in flat if s['kind'] != 'deferred')
        check('callbacks', sum(lowered.values()) + sum(s['operations'] for s in flat if s['kind'] == 'deferred') == sum(operations.values()),
              'operations of ' + alias + ' are not all counted once')
        for op, count in lowered.items():
            check('callbacks', count <= operations[op], 'more ' + op + ' lowered than the source has in ' + alias)
        for step in flat:
            if step['kind'] == 'objective':
                port = step['verb'] + '_' + objective_identifier(step['objective'])
                check('objective_ports', quest_ports.get(port) == ('In', 'trigger'), 'quest has no input ' + port)
    module = ET.fromstring(result['module']).find('./Skald/Module')
    outs = {p.get('Name') for p in module.find('Ports') if p.get('Direction') == 'Out'}
    for wire in result['report']['wiring']:
        check('objective_ports', wire['port'] in outs and quest_ports.get(wire['input']) == ('In', 'trigger'), 'wiring of ' + wire['port'])
    typed = [n for n in module.find('Nodes') if n.tag == 'State' and n.get('TypeT') != 'bool']
    check('objective_ports', not typed, 'the scene module holds quest or objective state of its own')
    rows = {r['name']: r for r in result['rows']}
    for alias, record in records.items():
        if record['status'] == 'converted':
            row = rows.get(cutscene_name(model['quest'], alias))
            check('movies', row is not None and row['source'] == record['video'], 'movie row of ' + alias)
    check('movies', len(rows) == sum(r['status'] == 'converted' for r in records.values()), 'movie rows differ from the converted videos')
    not_run = 0
    for alias, record in records.items():
        if record['status'] != 'converted':
            continue
        if media is None or alias not in media:
            not_run += 1
            continue
        expected, encoded = media[alias]
        check('media', all(str(encoded.get(k)) == str(expected.get(k)) for k in ('width', 'height', 'r_frame_rate', 'nb_frames'))
              and encoded.get('audio_streams', 0) >= 1, 'encoded picture of ' + alias + ' differs from the source')
    for name, record in result['plan'].items():
        for layer in record['layers']:
            if layer['status'] == 'own':
                missing = sum(r['entities'] for r in record['residue'] if r.get('layer') == layer['layer'])
                check('profile_entities', layer['in_level'] + missing == layer['entities'] and len(layer['move']) == layer['in_level'],
                      'entities of ' + layer['layer'] + ' are not all accounted')
        check('profile_layers', record['totals']['layers'] == len(record['layers']), 'layers of ' + name)
    passed = sum(checked.values()) - len(failures)
    return dict(verdict='PASS' if not failures else 'FAIL', checked=sum(checked.values()), passed=passed, failed=len(failures),
                residue=len(result['ledger']['residue']), categories=dict(sorted(checked.items())), media_not_run=not_run,
                failures=failures)


def golden(ledger_, module_blob, table_rows):
    return dict(schema=1, quest=ledger_['quest'], converter=CONVERTER,
                module_sha256=hashlib.sha256(module_blob.replace(b'\r\n', b'\n')).hexdigest(),
                scenes=ledger_['scenes'], callbacks=ledger_['callbacks'], lowered=ledger_['lowered'],
                movies=table_rows, profiles=ledger_['profiles'], module=ledger_['module'],
                residue_by_kind=ledger_['residue_by_kind'])


def convert(model, video_names, whdata, layer_entities, level_guids, native_guid, native_cutscenes, selection,
            streaming_path=STREAMING + '.xml'):
    """Run C5 on one quest model. Returns dict(module, table, ledger, records, programs, plan, report)."""
    videos = video_sources(video_names).get(model['quest'].lower(), {})
    profiles = source_profiles(whdata)
    records = scenes(model, videos, profiles, selection)
    programs = [p for p in (program(model, r['alias']) for r in records if r['status'] == 'converted') if p is not None]
    switches = [(s.get('enable'), s.get('disable')) for p in programs for s in _flat(p['steps']) if s['kind'] == 'profile']
    plan = profile_plan(switches, profiles, layer_entities, level_guids, native_guid)
    awaited = {s['profile'] for p in programs for s in _flat(p['steps']) if s['kind'] == 'await'}
    if awaited - plan.keys():
        raise Unsupported('A callback waits for a profile it never switches: ' + ', '.join(sorted(awaited - plan.keys())))
    module, report = emit(model, records, programs, streaming_path)
    table, rows = movie_rows(native_cutscenes, records, model['quest'])
    return dict(module=module, table=table, records=records, programs=programs, plan=plan, report=report,
                ledger=ledger(model, records, programs, plan, report, rows), rows=rows)


# ---------------------------------------------------------------- retail loader and command line

MAIN_PATH = {'q_skalitz': ('kovani_otcem', 'forging_father_insert', 'navsteva_racka')}
SOURCE_LEVEL = 'rataje'


def layer_census(root):
    """[dict(guid, kind, name)] of one source layer file."""
    found = []
    for node in root:
        guid = node.get('EntityGuid', '')
        found.append(dict(guid=int(guid, 16) if len(guid) == 16 and int(guid, 16) else None,
                          kind=node.get('EntityClass') if node.tag == 'Entity' else 'Object:' + str(node.get('Type')),
                          name=node.get('Name')))
    return found


def convert_retail(kcd1, kcd2, quest, selection=None, package=None, model=None):
    """C5 on retail KCD1 (and, for entity accounting, a built package's level). Reads only."""
    from pathlib import Path
    import zipfile
    from campaign_entity_links import native_guid
    from campaign_sources import RetailSourceReader
    from quest_import import import_quest
    from upgrade_map import read
    kcd1, kcd2 = Path(kcd1), Path(kcd2)
    if model is None:
        with RetailSourceReader(kcd1) as reader:
            model = import_quest(kcd1, quest, source_reader=reader)[0]
    names = {}
    for path in sorted((kcd1 / 'Data').glob('*.pak')):
        try:
            with zipfile.ZipFile(path) as archive:
                found = [n for n in archive.namelist() if n.lower().startswith('videos/')]
        except zipfile.BadZipFile:
            continue
        if found:
            names[path.name] = found
    with zipfile.ZipFile(kcd1 / 'Data/Levels' / SOURCE_LEVEL / 'level.pak') as archive:
        index = {n.lower(): n for n in archive.namelist()}
        whdata = ET.fromstring(read(archive, index['whdata_1']))
        wanted = {layer for profile in source_profiles(whdata).values() for layer in profile['layers']}
        layers = {layer: layer_census(ET.fromstring(read(archive, index['layers/' + layer.lower() + '.xml'])))
                  for layer in wanted if 'layers/' + layer.lower() + '.xml' in index}
    guids = set()
    if package is not None:
        with zipfile.ZipFile(Path(package) / 'Data/Levels/kcd1_travel/level.pak') as archive:
            guids = {e.get('EntityGuid') for e in ET.fromstring(read(archive, 'objects_mission0.xml')).iter('Entity')}
    with zipfile.ZipFile(kcd2 / 'Data/Tables.pak') as archive:
        cutscenes = read(archive, 'Libs/Tables/ui/cutscene.xml')
    return dict(convert(model, names, whdata, layers, guids, native_guid, cutscenes,
                        selection if selection is not None else MAIN_PATH[quest]), model=model)


def main(argv=None):
    import argparse
    import json
    from pathlib import Path
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--kcd1', type=Path, required=True)
    parser.add_argument('--kcd2', type=Path, required=True)
    parser.add_argument('--quest', required=True)
    parser.add_argument('--package', type=Path, help='built package map folder, for entity accounting')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args(argv)
    result = convert_retail(args.kcd1, args.kcd2, args.quest, package=args.package)
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / (result['report']['module'] + '.xml')).write_bytes(result['module'])
    for name, payload in (('scenes.json', {k: result['ledger'][k] for k in ('schema', 'converter', 'quest', 'scenes', 'callbacks',
                                                                              'lowered', 'movies', 'module', 'residue', 'residue_by_kind')}),
                          ('profiles.json', dict(quest=args.quest, profiles=result['ledger']['profiles'],
                                                 residue=[r for r in result['ledger']['residue'] if r['kind'].startswith('profile_')]))):
        (args.output / name).write_text(json.dumps(payload, indent=2, sort_keys=True, default=str) + '\n', encoding='utf-8', newline='\n')
    print(json.dumps(dict(scenes=result['ledger']['scenes']['categories'], converted=result['ledger']['scenes']['converted'],
                          lowered=result['ledger']['lowered'], residue=result['ledger']['residue_by_kind'],
                          profiles={n: p['totals'] for n, p in result['ledger']['profiles'].items()}), indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
