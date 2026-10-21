"""Stage selected source introductions through native sitting and speech systems."""
import copy
import json
from pathlib import Path
from types import SimpleNamespace
import uuid
import xml.etree.ElementTree as E
import zipfile

from campaign_intro_activity import plan, emit
from campaign_quest_start_placement import load, unique
from campaign_entity_links import native_guid, append_links, guid_value
from campaign_quest_graph import xml, edge, constant, all_of
from upgrade_map import read

SELECTIONS = (('q_tutorial_swordOne', 'vanek_idle'),)
RECORD = 'quest-introductions.json'


def repair_destinations(mission, scheduler, report, *, create=False):
    """Repair only this introduction's source-linked seat in older packages."""
    from campaign_behavior_schedule import destination
    guid = native_guid(int(report['placement']['source_place_guid'], 16))
    seat = unique((e for e in mission if e.get('EntityGuid') == guid), 'intro sitting destination')
    stem = 'gm_intro_'+report['placement']['quest']+'_'+report['source_plan']['tree']
    if seat.get('Name') != 'gm_schedule_'+stem+'_seat':
        raise ValueError('Introduction sitting destination identity differs')
    return destination(scheduler, seat, create=create)


def validate_package(package):
    """Validate the executable activity, not just the stage receipt."""
    report = json.loads((package/RECORD).read_text(encoding='utf-8'))
    p, placement = report['source_plan'], report['placement']
    if (placement['quest'],p['tree']) not in SELECTIONS:
        raise ValueError('Unexpected introduction selection')
    if not p.get('initialization'):
        raise ValueError('Missing source introduction initialization; upgrade this package')
    stem = 'gm_intro_'+placement['quest']+'_'+p['tree']
    with zipfile.ZipFile(package/'Data/gluemappertravel.pak') as z:
        for name, blob in emit(stem,p).items():
            if read(z,name) != blob: raise ValueError('Introduction worker differs: '+name)
        from setup_gameplay import ENTRY
        entry = E.fromstring(read(z,ENTRY))
        from setup_gameplay import PROJECT
        project = E.fromstring(read(z,PROJECT)).find('Skald/Project')
        from campaign_intro_factions import attach
        attach(entry, stem, p, validate=True)
        from character_factions import PATH
        faction = p['temporary_faction']['native_faction']
        if not any(n.get('Name') == faction for n in E.fromstring(read(z,PATH)).iter('Faction')):
            raise ValueError('Introductory temporary faction is not registered')
        if entry.find(".//EnableBehavior[@Name='"+stem+"_enable']") is None:
            raise ValueError('Introduction is not activated by the quest')
        if not any(p['alias'].encode() in read(z,n) for n in z.namelist()
                   if n.startswith('Quests/') and n.endswith('.xml')):
            raise ValueError('Introduction bark is not registered')
    with zipfile.ZipFile(package/'Data/Levels/kcd1_travel/level.pak') as z:
        mission = E.fromstring(read(z,'objects_mission0.xml'))
        host = unique((e for e in mission if e.get('Name') == stem+'_host'),'intro host')
        scheduler = E.fromstring(read(z,'tables/ai/scheduler.xml'))
        repair_destinations(mission, scheduler, report)
        if p.get('initialization'):
            from campaign_intro_initialization import bind
            entity = unique((e for e in mission if e.get('Name') == project.get('Name')), 'intro project entity')
            bind(mission,project,entity,entry.find('Skald/Level'),[],stem,p['initialization']['placement'],validate=True)
        actor = scheduler.find("Schedulers/C_SmartHub[@EntityGuid='"+str(guid_value(placement['actor_guid']))+"']")
        if actor is None or not any(n.get('TargetGuid') == str(guid_value(host.get('EntityGuid')))
                                    and n.find('Parameters').get('BehaviorName') == 'intro'
                                    for n in actor.findall('Links/S_ActivityLink')):
            raise ValueError('Introduction lacks its compiled actor schedule')
    return report


def upgrade(package, source, target):
    """Idempotent bounded migration on the caller's private package."""
    if (package/RECORD).exists():
        from setup_package_upgrade import rewrite
        from setup_campaign import digest
        from setup_gameplay import ENTRY
        from campaign_intro_factions import resolve, attach
        report = json.loads((package/RECORD).read_text(encoding='utf-8'))
        p = report['source_plan']
        # Re-read the selected source on migration; old receipts did not carry
        # the worker's first-entry initializer at all.
        if 'initialization' not in p:
            if source is None: raise ValueError('KCD1 is required for introductory initialization')
            from campaign_sources import RetailSourceReader
            with RetailSourceReader(source) as reader:
                blob = reader(source, {'intro':('Scripts.pak','Libs/AI/quests/'+report['placement']['quest']+'.xml')})['intro']['data']
            p['initialization'] = plan(blob,p['tree'])['initialization']
            if p['initialization']:
                p['initialization']['placement'] = load(source,'rataje',[(report['placement']['quest'],p['actor_role'],p['initialization']['arrival_role'])])[0]
        travel = 'Data/gluemappertravel.pak'
        with zipfile.ZipFile(package/travel) as z:
            entry = E.fromstring(read(z,ENTRY))
            if 'temporary_faction' not in p:
                if source is None or target is None:
                    raise ValueError('Both installed games are required for introductory factions')
                p['temporary_faction'] = resolve(Path(source),Path(target),z,p,report['placement']['quest'])
        stem = 'gm_intro_'+report['placement']['quest']+'_'+p['tree']
        changed = {}
        if attach(entry,stem,p):
            rewrite(package,travel,{ENTRY:xml(entry)})
            changed[travel] = digest(package/travel)
            report['runtime_verified'] = False
            (package/RECORD).write_text(json.dumps(report,indent=2),encoding='utf-8')
            changed[RECORD] = digest(package/RECORD)
        level = 'Data/Levels/kcd1_travel/level.pak'
        with zipfile.ZipFile(package/level) as z:
            mission = E.fromstring(read(z,'objects_mission0.xml'))
            scheduler = E.fromstring(read(z,'tables/ai/scheduler.xml'))
            waiting = read(z,'waitinglinks.xml')
        if p.get('initialization'):
            from campaign_intro_initialization import bind
            from setup_gameplay import PROJECT
            with zipfile.ZipFile(package/travel) as z:
                project_root = E.fromstring(read(z,PROJECT))
                existing = {n:read(z,n) for n in emit(stem,p)}
            project = project_root.find('Skald/Project')
            entity = unique((e for e in mission if e.get('Name') == project.get('Name')), 'intro project entity')
            additions = []
            bound = bind(mission,project,entity,entry.find('Skald/Level'),additions,stem,p['initialization']['placement'])
            workers = emit(stem,p)
            if bound or workers != existing:
                from campaign_combat_work import validate
                if target is None: raise ValueError('KCD2 is required to validate introductory initialization')
                validate(workers,Path(target))
                rewrite(package,travel,dict(workers,**{PROJECT:xml(project_root),ENTRY:xml(entry)}))
                rewrite(package,level,{'objects_mission0.xml':xml(mission),'waitinglinks.xml':append_links(waiting,additions)})
                changed[travel]=digest(package/travel); changed[level]=digest(package/level)
                report['runtime_verified']=False
                (package/RECORD).write_text(json.dumps(report,indent=2),encoding='utf-8')
                changed[RECORD]=digest(package/RECORD)
        if repair_destinations(mission, scheduler, report, create=True):
            rewrite(package, level, {'tables/ai/scheduler.xml':xml(scheduler)})
            changed[level] = digest(package/level)
        return changed, validate_package(package)
    if source is None or target is None:
        raise ValueError('Both installed games are required for quest introductions')
    import tempfile
    from build_recipe import apply_overlay
    with tempfile.TemporaryDirectory(prefix='intro-',dir=package.parent) as work:
        output = Path(work)/'stage'
        build(Path(source),Path(target),package,output)
        changed = apply_overlay(package,output/'package',consume=True)
    return changed, validate_package(package)


def convert(files, level_files, source_plan, placement, stem, target, project_path, entry_path):
    from campaign_behavior_schedule import connect, validate_compiled, destination
    from character_person_world import native_wait_activity
    from character_person_activity import validate_scheduler_targets
    from campaign_combat_work import validate
    from seating_animations import install, HELPERS, ANIMATIONS
    changes = emit(stem, source_plan)
    validate(changes, target)
    with zipfile.ZipFile(target/'Data/Tables.pak') as z:
        types = E.fromstring(read(z,'Libs/Tables/ai/ai_types.xml'))
        message = unique(types.findall(".//Type[@Name='dialog']/Type[@Name='monologRequest']"),'native monologue request')
        members = {m.get('Name'):m.get('Type') for m in message.findall('Member')}
        if any(members.get(k) != v for k,v in {'alias':'string','lookAtId':'wuid','priority':'int'}.items()):
            raise ValueError('Native monologue request ABI changed')
    objects = E.fromstring(level_files['objects_mission0.xml'])
    scheduler = E.fromstring(level_files['tables/ai/scheduler.xml'])
    project_root, entry_root = E.fromstring(files[project_path]), E.fromstring(files[entry_path])
    project, entry = project_root.find('Skald/Project'), entry_root.find('Skald/Level')
    nodes = entry.find('Nodes')
    if nodes.find("*[@Name='" + stem + "_enable']") is not None:
        raise ValueError('Introduction is already installed; rebuild from its preceding recipe stage')
    quest = unique((n for n in nodes if n.tag == source_plan['parent_quest']), 'intro parent quest')
    parent_blob = unique((b for p,b in files.items() if p.startswith('Quests/')
                         and E.fromstring(b).find("Skald/Quest[@Name='" + source_plan['parent_quest'] + "']") is not None), 'parent quest definition')
    port = source_plan['objective'] + '_Started'
    if E.fromstring(parent_blob).find(".//Ports/Port[@Name='" + port + "']") is None:
        raise ValueError('Intro activation objective has not been converted')
    actor = unique((e for e in objects if e.get('EntityGuid') == placement['actor_guid']), 'placed intro actor')
    project_entity = unique((e for e in objects if e.get('Name') == project.get('Name')), 'project entity')
    with zipfile.ZipFile(target/'Data/Levels/trosecko/level.pak') as z:
        native = E.fromstring(read(z, 'objects_mission0.xml'))
    seat = next(e for e in native if e.get('EntityClass') == 'SmartObjectHolder'
                and e.find('Properties/Script') is not None
                and e.find('Properties/Script').get('Misc') == 'isGroundPlace:true')
    def add(name, guid, props):
        if any(e.get('EntityGuid') == guid for e in objects):
            raise ValueError('Introduction entity identity collision: ' + name)
        e = E.SubElement(objects, 'Entity', Name=name, EntityClass='SmartObjectHolder', EntityGuid=guid,
                         EntityId=str(max(int(n.get('EntityId', '0')) for n in objects)+1), **placement['placement'])
        e.append(copy.deepcopy(props))
        return e
    spot = add('gm_schedule_' + stem + '_seat', native_guid(int(placement['source_place_guid'],16)), seat.find('Properties'))
    destination(scheduler, spot, create=True)
    tid = str(uuid.uuid5(uuid.NAMESPACE_URL, stem + '/template'))
    host = add(stem + '_host', native_guid(uuid.uuid5(uuid.NAMESPACE_URL, stem + '/host').int & ((1<<64)-1)),
               E.Element('Properties', guidSmartObjectType=tid, bSaved_by_game='0'))
    additions = []
    def asset(kind, name, entity):
        if project.find("Assets/*[@Name='" + name + "']") is not None:
            raise ValueError('Intro asset collision')
        E.SubElement(project.find('Assets'), kind, Name=name)
        links = project_entity.find('EntityLinks')
        if links is None: links = E.SubElement(project_entity, 'EntityLinks')
        label = "asset['" + name + "']"
        E.SubElement(links, 'Link', Name=label, TargetId=entity.get('EntityId'), TargetGuid=entity.get('EntityGuid'))
        additions.append((project_entity.get('EntityGuid'), entity.get('EntityGuid'), label))
        return name
    assets = {k:asset(kind, stem+'_'+k, entity) for k,kind,entity in
              [('actor','SoulAsset',actor), ('place','SmartObjectAsset',spot), ('host','SmartObjectAsset',host)]}
    activity, _ = native_wait_activity(target)
    anchor = connect(objects, additions, actor, host, 'intro', source_plan['priority'], source_plan['speed'], stem,
                     scheduler, activity)
    anchor.attrib.update(placement['placement'])
    table = E.Element('database', name='barbora')
    template = E.SubElement(E.SubElement(table,'SmartEntitys',version='1'), 'SmartEntityTemplate',
                            DatabaseId=tid, Name=stem, UpdatePriority='false')
    b = E.SubElement(E.SubElement(template,'BehaviorTemplates'), 'SmartBehaviorTemplate',
                     Name='intro', InitialState='Disabled', MaxInstances='1')
    E.SubElement(b, 'TreeLocation', FileName=stem+'.xml', TreeName='intro')
    changes['Libs/Tables/ai/smartEntity/SmartEntity__'+stem+'.xml'] = xml(table)
    ended = E.SubElement(nodes, 'State', Name=stem+'_ended', TypeT='bool')
    constant(ended,'DefaultValue','false')
    inv = E.SubElement(nodes,'Function',Name=stem+'_pending',MethodName='math::boolean::Not',DeclaringType='math::boolean')
    edge(inv,stem+'_ended.State','Value')
    active = all_of(nodes, stem+'_active', [quest.get('Name')+'.started', quest.get('Name')+'.'+port, stem+'_pending.bool'])
    enable = E.SubElement(nodes,'EnableBehavior',Name=stem+'_enable',Signature=stem,EventSet='resultNotification')
    constant(enable,'Behavior','intro'); constant(enable,'ForceKick','true')
    for name,key in [('NPC','actor'),('SmartEntity','host'),('workPlace','place')]:
        E.SubElement(enable,'Asset',Name=name,Alias=assets[key])
    edge(enable,active,'IsActive')
    # A once-only source request must not restart indefinitely after failure.
    for event in ('Success','Fail'): edge(ended,stem+'_enable.'+event,'SetTrue')
    from campaign_intro_factions import attach
    attach(entry_root,stem,source_plan)
    if source_plan.get('initialization'):
        from campaign_intro_initialization import bind
        bind(objects,project,project_entity,entry,additions,stem,source_plan['initialization']['placement'])
    changes[project_path], changes[entry_path] = xml(project_root), xml(entry_root)
    validate_compiled(objects,scheduler,additions)
    validate_scheduler_targets(scheduler)
    level_changes = dict(level_files, **{'objects_mission0.xml':xml(objects),
        'tables/ai/scheduler.xml':xml(scheduler), 'waitinglinks.xml':append_links(level_files['waitinglinks.xml'],additions)})
    with zipfile.ZipFile(target/'Data/Levels/trosecko/level.pak') as native:
        level_changes, _ = install(level_changes,native)
    for name in (HELPERS,ANIMATIONS):
        changes['Mods/kingdomcomegluemapper/Data/Levels/kcd1_travel/'+name] = level_changes[name]
    return changes, level_changes


def build(source, target, package, output, selections=SELECTIONS):
    from campaign_sources import RetailSourceReader
    from campaign_intro_activity import normalized
    from campaign_dialogue import load_many
    from build_actor_dialogues_test import build as dialogues
    from build_horse_trader_test import rewrite, digest
    from setup_gameplay import PROJECT, ENTRY, LEVEL, quest_model
    if len(selections) != 1:
        raise ValueError('Stage one selected introduction at a time')
    quest, tree = selections[0]
    with RetailSourceReader(source) as reader:
        blob = reader(source, {'intro':('Scripts.pak','Libs/AI/quests/'+quest+'.xml')})['intro']['data']
    p = plan(blob,tree)
    if p.get('initialization'):
        p['initialization']['placement'] = load(source,'rataje',[(quest,p['actor_role'],p['initialization']['arrival_role'])])[0]
    document = normalized(blob)
    gate = unique((g for g in document.iter('QuestObjectiveGate') if g.get('objectiveState') == 'Started'
                   and any(n.tag == 'SetQuest' and n.get('function') == 'StartQuest' for n in g.iter())), 'intro parent activation')
    variable = gate.get('questName','').lstrip('$')
    var = unique(document.findall("BehaviorTree[@name='onUpdate']/Variables/Variable[@name='"+variable+"']"),'parent quest variable')
    p.update(parent_quest=var.get('values').strip("'"), objective=gate.get('objectiveName'))
    from campaign_intro_factions import resolve
    with zipfile.ZipFile(package/'Data/gluemappertravel.pak') as z:
        p['temporary_faction'] = resolve(source,target,z,p,quest)
    placement = load(source,'rataje',[(quest,p['actor_role'],p['place_role'])])[0]
    with zipfile.ZipFile(source/'Data/Levels/rataje/level.pak') as z:
        original = None
        for name in z.namelist():
            if name.lower() == 'objects_mission0.xml' or name.lower().startswith('layers/') and name.lower().endswith('.xml'):
                original = next((e for e in E.fromstring(read(z,name)).iter('Entity')
                                 if e.get('EntityGuid') == placement['source_place_guid']),original)
        if original is None or original.find('Properties').get('soclasses_SmartObjectHelpers') != 'sitGround':
            raise ValueError('Intro seat requires a native helper adapter')
    stem = 'gm_intro_'+quest+'_'+tree
    # The source quest model supplies the bark's conditions; no dialogue text or
    # recorded audio is synthesized by this adapter.
    output.mkdir(parents=True,exist_ok=False)
    quest_model(source,output/'inputs',p['parent_quest'])
    topics = [m['start_topic'] for m in load_many(source,[(p['alias'],None)])]
    dialogues(SimpleNamespace(source=source,target=target,mod=package,output=output/'speech',
        quest_ir=[output/'inputs/quest-ir.json'],start_topic=topics,namespace=stem+'_speech',
        kind='Dialog',container=ENTRY.removeprefix('Quests/'),container_name=LEVEL,
        activation=p['parent_quest']+'.'+p['objective']+'_Started',skill_upgrade=[],participant_asset=[]))
    staged = output/'speech/package'
    with zipfile.ZipFile(staged/'Data/gluemappertravel.pak') as z:
        files = {n:read(z,n) for n in z.namelist() if n.startswith('Quests/') and n.endswith('.xml')}
    level = package/'Data/Levels'/LEVEL/'level.pak'
    with zipfile.ZipFile(level) as z:
        level_files = {n:read(z,n) for n in ('objects_mission0.xml','waitinglinks.xml','tables/ai/scheduler.xml',
                                           'smartobjecthelpersetanimations.xml','tables/ai/smartobjectanimations.xml')}
    changes, level_changes = convert(files,level_files,p,placement,stem,target,PROJECT,ENTRY)
    destination = output/'package'
    staged.rename(destination)
    rewritten = output/'travel.pak'
    rewrite(destination/'Data/gluemappertravel.pak',rewritten,changes)
    rewritten.replace(destination/'Data/gluemappertravel.pak')
    rewrite(level,destination/'Data/Levels'/LEVEL/'level.pak',level_changes)
    report = dict(source_plan=p,placement=placement, runtime_verified=False,
                  scope='Introductory sitting and proximity bark; invitation and lesson are separate stages')
    (destination/RECORD).write_text(json.dumps(report,indent=2),encoding='utf-8')
    for path in destination.rglob('*.pak'):
        with zipfile.ZipFile(path) as z:
            if len(z.namelist()) != len(set(n.lower() for n in z.namelist())) or z.testzip():
                raise ValueError('Invalid intro package archive: '+str(path))
    report['files'] = {p.relative_to(destination).as_posix():digest(p) for p in destination.rglob('*') if p.is_file()}
    (output/'report.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    return report
