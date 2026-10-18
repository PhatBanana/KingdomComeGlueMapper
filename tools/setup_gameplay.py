"""Rebuild the bounded working campaign through the existing source adapters.

Selections below describe the shipped slice, not replacement quest logic. Each
adapter reads the original games and consumes the preceding staged package.
No development installation or backup is an input to this recipe.
"""
import json
from pathlib import Path
from types import SimpleNamespace
import xml.etree.ElementTree as ET
import zipfile

from build_horse_trader_test import rewrite
from upgrade_map import read, xml

LEVEL = 'kcd1_travel'
PROJECT = 'Quests/GlueTravel/GlueTravel_kcd1.xml'
ENTRY = 'Quests/GlueTravel/entry/kcd1_travel.xml'
QUEST = 'q_skalitz'
QUEST_PATH = 'Quests/GlueTravel/gm_imported_scene/q_skalitz.xml'
OPENING = 'gm_kcd1_character_creation'
PEOPLE = ('ska_motherOfHenry', 'ska_fatherOfHenry', 'ska_blanka', 'ska_fricek',
          'ska_kunes', 'ska_matus', 'ska_matej', 'ska_sarka', 'ska_woman5',
          'ska_guard2', 'vra_vanek')
SCENE_PEOPLE = {'rat_guardJanek': 'janek', 'rat_guardJaroslav': 'jaroslav'}
# Source branch IDs are explicit slice selection. Conditions, effects, recordings
# and combat transitions are compiled by the shared importers, never copied here.
DIALOGUES = (
    ('gm_parent_interaction', 'FaderDialog', ('9073', '9422', '14857', '14913', '9193')),
    ('gm_approach', 'Dialog', ('9072', '26993')),
    ('gm_debt_interaction', 'FaderDialog', ('7059',)),
    ('gm_debt_results', 'FaderDialog', ('7116', '26675', '26676')),
    ('gm_guard_interaction', 'FaderDialog', ('7691', '14861')),
)
STAGE_IDS = ('opening', 'actors', 'initial-state', 'initial-loadout', 'quest-items',
             'schedules', 'actor-systems', 'character-props', 'dialogue-areas',
             *(group[0] for group in DIALOGUES), 'combat', 'facials')


def publish_flat(output, mapping):
    """Normalize historical builder outputs to the recipe overlay contract."""
    output = Path(output)
    for original, destination in mapping.items():
        source = output / original
        if not source.is_file():
            raise ValueError('Builder omitted required output: ' + str(source))
        target = output / 'package' / destination
        target.parent.mkdir(parents=True, exist_ok=True)
        source.replace(target)


def quest_model(source, output):
    from quest_import import import_quest
    from campaign_sources import RetailSourceReader
    from campaign_ai_registration import controller_definition
    from campaign_dependency_adapters import SourceTables
    with RetailSourceReader(source) as reader:
        tables = SourceTables(source, reader)
        definition = controller_definition(tables, tables.row('quest/quest', 'quest_name', QUEST))
        bootstrap = sorted({p['file'] for p in definition['entry_points']}) if definition else []
        model, _ = import_quest(source, QUEST, bootstrap=bootstrap, source_reader=reader)
        model['controller_registration'] = definition
        behavior = reader(source, {'controller': ('Scripts.pak', 'Libs/AI/quests/' + QUEST + '.xml')})['controller']['data']
    output.mkdir(parents=True)
    (output / 'quest-ir.json').write_text(json.dumps(model, indent=2), encoding='utf-8')
    (output / 'behavior.xml').write_bytes(behavior)
    return model


def opening(source, target, package, output):
    from campaign_dialogue import load, emit, voices, camera_assets
    from campaign_dialogue_runtime import bind_recordings, voice_namespace
    from campaign_dialogue_selection import SelectionCompiler, load_contract
    from character_person import resolve_person
    from character_person_appearance import build_appearance
    from campaign_scene_test import build as scene
    model = quest_model(source, output / 'inputs')
    dialogue = output / 'dialogue'; dialogue.mkdir()
    runtime = output / 'runtime'
    original = load(source, 'q_skalitz_characterCreation')
    contract = load_contract(source, target, {})
    contract['preserve_reputation_caps'] = True
    selection = SelectionCompiler(**contract)
    blob, conversion = emit(original, OPENING, [model], kind='ForcedDialog',
        convert_presentation=True, selection_compiler=selection, scene_bound=True)
    media, conversion['voices'] = voices(source, original, OPENING)
    with zipfile.ZipFile(target / 'Data/Tables.pak') as z:
        native_voices = read(z, 'Libs/Tables/skald/voice.xml')
    with zipfile.ZipFile(package/'Data/gluemappertravel.pak') as z:
        graphs = {n.removeprefix('Quests/'): read(z, n) for n in z.namelist()
                  if n.startswith('Quests/') and n.endswith('.xml')}
    blob, media, binding = bind_recordings(blob, original, media, native_voices,
        parent_namespace=voice_namespace(graphs, PROJECT.removeprefix('Quests/')))
    cameras, conversion['cameras'] = camera_assets(original, source / 'Data/Levels/rataje/level.pak')
    (dialogue / 'camera-entities.xml').write_bytes(cameras)
    (dialogue / 'dialogue-ir.json').write_text(json.dumps(original), encoding='utf-8')
    (dialogue / 'conversion.json').write_text(json.dumps(conversion), encoding='utf-8')
    files = {'Data/Quests/' + OPENING + '.xml': blob,
             'runtime-binding.json': json.dumps(binding).encode(),
             'Localization/English_xml/text_ui_dialog.xml': strings(original['strings'])}
    files.update({'Localization/English/' + n: b for n, b in media.items()})
    for name, data in files.items():
        path = runtime / name; path.parent.mkdir(parents=True, exist_ok=True); path.write_bytes(data)
    appearance = output / 'appearance'
    person = resolve_person(source, PEOPLE[0], 'rataje')
    character = build_appearance(source, target, person, 'gm_ska_mother', appearance)
    (appearance/'appearance-result.json').write_text(json.dumps(character, indent=2), encoding='utf-8')
    scene(SimpleNamespace(source=source, target=target, mod=package,
        dialogue=dialogue, runtime=runtime, appearance=appearance,
        quest_model=output/'inputs/quest-ir.json', behavior=output/'inputs/behavior.xml',
        output=output/'scene', person=PEOPLE[0], role='JINDRICHOVA_MATKA', namespace='gm_ska_mother',
        dialogue_name=OPENING, actor_alias='mother', scene_alias='stribrna_skalice',
        completion_input='complete_objectiveStart', source_level='rataje', level=LEVEL,
        project_path=PROJECT, player_asset='travel_player', allow_missing_gestures=True))
    (output/'scene/package').rename(output/'package')


def strings(values):
    table = ET.Element('Table')
    for key, value in sorted(values.items()):
        row = ET.SubElement(table, 'Row')
        for text in (key, value, value): ET.SubElement(row, 'Cell').text = text
    return xml(table)


def source_player(source, level='rataje'):
    """Resolve the player through its shared soul, not the NPC-only adapter."""
    from campaign_sources import RetailSourceReader
    from campaign_dependency_adapters import SourceTables
    with RetailSourceReader(source) as reader:
        soul = SourceTables(source, reader).row('rpg/soul', 'soul_name', 'dude')
    with zipfile.ZipFile(source/'Data/Levels'/level/'level.pak') as z:
        instances = [s for s in ET.fromstring(read(z, 'whdata_0')).findall('SoulList/Souls/Soul')
                     if s.findtext('SharedSoulGuid') == soul['soul_id']]
    if len(instances) != 1: raise ValueError('Missing or ambiguous source player instance')
    return dict(soul=soul, instance=instances[0])


def actors(source, target, package, output):
    from build_quest_people_test import build
    from campaign_scene_test import source_scene_positions
    spots = source_scene_positions(source, 'rataje', QUEST, 'stribrna_skalice')
    placements = {name: spots[alias] for name, alias in SCENE_PEOPLE.items()}
    build(SimpleNamespace(source=source, target=target, mod=package, output=output,
        placements=placements, model=None, person=list(PEOPLE) + list(SCENE_PEOPLE), source_level='rataje', level=LEVEL,
        source_profile=[], dialogue_profile=[], dialogue_model=[], quest_path=None,
        project_path=PROJECT))
    report = json.loads((output/'report.json').read_text())
    actual = {p['person'] for group in ('converted', 'existing') for p in report[group]}
    if report['pending'] or actual != set(PEOPLE) | set(SCENE_PEOPLE):
        raise ValueError('Campaign actors incomplete; see ' + str(output/'report.json'))


def initialization(source, target, package, output):
    from build_campaign_initial_state import build
    person = source_player(source)
    controller = 'Libs/AI/quests/' + QUEST + '.xml'
    # attach_scene supplies the registered, placed participants and persisted
    # initialization latch before this chain is reached.
    binding = dict(source_soul=person['soul']['soul_id'], source_controller=controller,
        satisfied_readiness_locks=['assetsLoaded'],
        unassigned_skill_level=1, graph=PROJECT, soul_asset='travel_player', namespace='gm_source',
        baseline=dict(destination=LEVEL, input=QUEST+'__start', event=OPENING+'_initialize.B'),
        quest_start=dict(destination=OPENING, input='EnqueueDialogue', event=OPENING+'_initialize.C'))
    build(source, target, package/'Data/gluemappertravel.pak', output, binding)
    publish_flat(output, {'gluemappertravel.pak': 'Data/gluemappertravel.pak'})


def loadout(source, target, package, output):
    from build_campaign_initial_loadout import build
    person = source_player(source)
    build(source, target, package, output, dict(source_level='rataje',
        source_instance=person['instance'].findtext('Guid'), graph=PROJECT,
        soul_asset='travel_player', destination='gm_source_baseline_stat_agility',
        input_port='Exec', source_event=OPENING+'_initialize.B', namespace='gm_source_initial_loadout'))
    publish_flat(output, {'gluemappertravel.pak': 'Data/gluemappertravel.pak',
        'gluemapper_initial_loadout.pak': 'Data/gluemapper_initial_loadout.pak',
        'English_xml.pak': 'Localization/English_xml.pak'})


def quest_items(source, target, package, output, model_path):
    from build_quest_items_test import build
    build(source, target, package, model_path, QUEST_PATH, 'travel_player', output)
    report = json.loads((output/'report.json').read_text())
    validate_quest_items(report, json.loads(model_path.read_text()))
    publish_flat(output, {'gluemappertravel.pak': 'Data/gluemappertravel.pak',
        'gluemapper_quest_items.pak': 'Data/gluemapper_quest_items.pak',
        'English_xml.pak': 'Localization/English_xml.pak'})


def validate_quest_items(report, model):
    """The inventory adapter also reports objectives belonging to other systems."""
    items = model['tables']['quest_item']['rows']
    required = {r['item_id'] for r in items if r.get('item_id')}
    if required - set(report['item_map']):
        raise ValueError('Unconverted source quest item registrations')
    assets = {r['quest_asset_id'] for r in items}
    tracked = {r['objective_id'] for r in model['tables']['quest_tracked_asset']['rows']
               if r['quest_asset_id'] in assets}
    if any(r['objective_id'] in tracked for r in report['pending']):
        raise ValueError('Unconverted item-tracking objectives')


def dialogues(source, target, package, output, model_path, group):
    from build_actor_dialogues_test import build
    namespace, kind, topics = group
    activation = QUEST + '.started'
    return build(SimpleNamespace(source=source, target=target, mod=package, output=output,
        quest_ir=[model_path], start_topic=list(topics), namespace=namespace, kind=kind,
        container=ENTRY.removeprefix('Quests/'), container_name=LEVEL,
        activation=activation, skill_upgrade=['threaten=might'],
        participant_asset=['Dude=player'], area_asset=[],
        level_archive=package/'Data/Levels'/LEVEL/'level.pak'))


def dialogue_areas(source, package, output):
    from campaign_dialogue import load_many
    from campaign_dialogue_world import area_references, merge_areas
    topics = sorted({t for _, _, values in DIALOGUES for t in values})
    names = area_references(load_many(source, [(None, t) for t in topics]))
    level = package/'Data/Levels'/LEVEL/'level.pak'
    with zipfile.ZipFile(source/'Data/Levels/rataje/level.pak') as original:
        entities = [e for n in original.namelist()
            if n.lower() == 'objects_mission0.xml' or n.lower().startswith('layers/') and n.lower().endswith('.xml')
            for e in ET.fromstring(read(original,n)).iter('Entity')]
        with zipfile.ZipFile(level) as archive:
            mission, geometry, report = merge_areas(read(archive,'objects_mission0.xml'),
                read(archive,'triggerareas.fubar'), read(original,'triggerareas.fubar'), entities, names)
    rewrite(level, output/'package/Data/Levels'/LEVEL/'level.pak',
        {'objects_mission0.xml':mission, 'triggerareas.fubar':geometry})
    (output/'report.json').write_text(json.dumps(report,indent=2))


def schedules(source, target, package, output):
    from build_person_schedule_test import build
    # These are the accepted work adapters in the bounded reference slice.
    build(SimpleNamespace(source=source, target=target, source_level='rataje', level=LEVEL,
        mod_id='kingdomcomegluemapper', level_pak=package/'Data/Levels'/LEVEL/'level.pak',
        travel_pak=package/'Data/gluemappertravel.pak', output=output,
        person=['ska_motherOfHenry', 'ska_fatherOfHenry', 'ska_woman5', 'ska_guard2'],
        jobs=True, jobs_only=False, routes=True))
    report = json.loads((output/'report.json').read_text())
    if any(not r.get('job') for r in report['jobs']):
        raise ValueError('Required work adapter missing; see ' + str(output/'report.json'))
    publish_flat(output, {'gluemappertravel.pak': 'Data/gluemappertravel.pak',
        'level.pak': 'Data/Levels/'+LEVEL+'/level.pak'})


def props(source, target, package, output):
    from world_character_props import build
    level = package/'Data/Levels'/LEVEL/'level.pak'
    with zipfile.ZipFile(level) as z: mission = read(z, 'objects_mission0.xml')
    mission, report = build(mission, source, output/'conversion')
    destination = output/'package/Data'; destination.mkdir(parents=True, exist_ok=True)
    rewrite(level, destination/'Levels'/LEVEL/'level.pak', {'objects_mission0.xml': mission})
    if report['converted']:
        with zipfile.ZipFile(destination/'gm_character_props.pak', 'x', zipfile.ZIP_STORED) as z:
            for p in (output/'conversion/converted').rglob('*'):
                if p.is_file(): z.write(p, p.relative_to(output/'conversion/converted').as_posix())
    (output/'report.json').write_text(json.dumps(report, indent=2))


def combat(source, target, package, output, model_path):
    from build_campaign_combat import build
    build(package/'Data/gluemappertravel.pak', package/'Data/Levels'/LEVEL/'level.pak',
        source/'Data/Levels/rataje/level.pak', output, json.loads(model_path.read_text()),
        'kunes_battle_fight', PROJECT, ENTRY, target, mod=package)
    publish_flat(output, {'gluemappertravel.pak': 'Data/gluemappertravel.pak',
        'level.pak': 'Data/Levels/'+LEVEL+'/level.pak'})
    # The combat builder may import its source aftermath dialogue on demand.
    for name in ('Data/gluemapper_dialogue_facials.pak', 'Localization/English.pak', 'Localization/English_xml.pak'):
        if (output/name).exists(): publish_flat(output, {name: name})


def facials(source, target, package, output):
    from build_dialogue_facials import build
    existing = package/'Data/gluemapper_dialogue_facials.pak'
    build(source, target, package/'Localization/English.pak', output, existing if existing.exists() else None)
    publish_flat(output, {'gluemapper_dialogue_facials.pak': 'Data/gluemapper_dialogue_facials.pak'})


def systems(source, target, package, output):
    from build_profile_systems import build
    result = build(SimpleNamespace(source=source, target=target, mod=package, output=output,
        source_level='rataje', level=LEVEL, profile=['q_skalitz_normal'],
        person=[p for p in PEOPLE if p != 'vra_vanek'], package=True))
    if result['schedule_errors'] or result['person_contract_errors'] or result['registered_souls'] != len(PEOPLE)-1:
        raise ValueError('Incomplete source actor services: ' + str(output/'systems.json'))


def steps(source, target, package, work):
    """Ordered adapters, with stable IDs for receipts and resume validation."""
    model = work/'opening/inputs/quest-ir.json'
    result = [
        ('opening', 'Original opening scene and mother', lambda out: opening(source, target, package, out)),
        ('actors', 'Source campaign people and equipment', lambda out: actors(source, target, package, out)),
        ('initial-state', 'Once-only source player state', lambda out: initialization(source, target, package, out)),
        ('initial-loadout', 'Source starting clothing and inventory', lambda out: loadout(source, target, package, out)),
        ('quest-items', 'Source quest items and tracking', lambda out: quest_items(source, target, package, out, model)),
        ('schedules', 'Source work arrivals, tools and routes', lambda out: schedules(source, target, package, out)),
        ('actor-systems', 'Source factions, authority and crime districts', lambda out: systems(source, target, package, out)),
        ('character-props', 'Animated world props and wells', lambda out: props(source, target, package, out)),
        ('dialogue-areas', 'Source conversation trigger areas', lambda out: dialogue_areas(source, package, out)),
    ]
    for group in DIALOGUES:
        result.append((group[0], 'Source conversations: '+group[0],
                       lambda out, group=group: dialogues(source, target, package, out, model, group)))
    result += [
        ('combat', 'Native quest combat and aftermath', lambda out: combat(source, target, package, out, model)),
        ('facials', 'Recording-linked facial data', lambda out: facials(source, target, package, out)),
    ]
    return result


def validate(package):
    """Check emitted content, not filenames or success of the last builder."""
    with zipfile.ZipFile(package/'Data/Levels'/LEVEL/'level.pak') as z:
        mission = ET.fromstring(read(z, 'objects_mission0.xml'))
        souls = ET.fromstring(read(z, 'whdata_0'))
        from smart_area_registration import reconcile
        reconcile(read(z, 'whdata_0'), read(z, 'objects_mission0.xml'), validate_only=True)
        from character_person_activity import validate_scheduler_targets
        validate_scheduler_targets(ET.fromstring(read(z, 'tables/ai/scheduler.xml')))
    for name in (*PEOPLE, *SCENE_PEOPLE):
        actors = [e for e in mission.iter('Entity') if e.get('Name') == name]
        if len(actors) != 1: raise ValueError('Setup omitted or duplicated actor: ' + name)
        registered = [s for s in souls.findall('SoulList/Souls/Soul')
                      if s.findtext('EntityGuid') == actors[0].get('EntityGuid')]
        if len(registered) != 1: raise ValueError('Setup omitted actor soul: ' + name)
    with zipfile.ZipFile(package/'Data/gluemappertravel.pak') as z:
        project = ET.fromstring(read(z, PROJECT))
        required = (OPENING, OPENING+'_started', 'gm_source_baseline_stat_agility')
        names = {n.get('Name') for n in project.findall('./Skald/Project/Nodes/*')}
        if set(required)-names: raise ValueError('Setup opening initialization is incomplete')
        from campaign_start_policy import validate_start_policy
        start_policy = validate_start_policy(read(z, PROJECT), OPENING)
        read(z, QUEST_PATH)
        read(z, 'Quests/GlueTravel/entry/gm_combat_q_skalitz_kunes_battle_fight.xml')
    for name in ('Data/gluemapper_initial_loadout.pak', 'Localization/English.pak',
                 'Data/gluemapper_dialogue_facials.pak', 'Data/gluemapper_world_items.pak'):
        if not (package/name).is_file(): raise ValueError('Setup dependency missing: ' + name)
    return dict(actors=len(PEOPLE)+len(SCENE_PEOPLE), opening=True, combat=True, start_policy=start_policy, runtime_verified=False)
