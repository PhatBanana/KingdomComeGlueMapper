"""C5 stage: the scenes of one KCD1 quest on a built package.

Order, each step reading what the one before staged:

    people     the NPCs of the quest's state profiles through the person route
               (`build_quest_people_test.build`), so they are mission placements
               of the staged level. The route converts one source brain; an actor
               with another is never staged with a different brain: it is deferred
               and listed as residue `brain_<source brain>`
    horses     the horses of those profiles that the source leaves idle, through
               `animal_population.place_horses`. A horse with a rider, a path or a
               controller link is driven by source AI: deferred and listed as
               residue `horse_driven_by_source_ai`
    scenes     `campaign_scenes.convert_retail` against the staged level, with the
               profiles the quest's own controller switches planned as well
    profiles   `campaign_scenes.register_profiles`: one layer and one profile per
               source profile, holding the entities the level has
    pictures   one CutsceneHolder per converted video, the cutscene table rows, the
               movies with their subtitles, and the subtitle strings
    module     the scene module beside the level entry; the quest bridge is wired
               when the controller converter's wiring rows are given

The stage writes an overlay folder and a report; it never touches the package.
Registering a profile moves its entities out of the flat level, so they exist only
while somebody streams the profile: apply the overlay only together with the
controller that switches them. Nothing here is runtime-verified.

    python tools/setup_kcd1_scenes.py --package <map> --media <dir> --output <fresh dir> [--people <stage dir>]
"""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
import uuid
import xml.etree.ElementTree as ET
import zipfile

import campaign_scenes as scenes

TRAVEL = 'Data/gluemappertravel.pak'
LEVEL = 'kcd1_travel'
LEVEL_PAK = 'Data/Levels/' + LEVEL + '/level.pak'
ENGLISH_XML = 'Localization/English_xml.pak'
OPENING = 'Data/gluemapper_opening.pak'
ENTRY = 'Quests/GlueTravel/entry/kcd1_travel.xml'
PROJECT = 'Quests/GlueTravel/GlueTravel_kcd1.xml'
TABLE = 'Libs/Tables/ui/cutscene.xml'
SOURCE_LEVEL = 'rataje'
# The state profiles whose population the quest needs before its scenes can switch to them.
PEOPLE_PROFILES = {'q_skalitz': ('q_skalitz_attack',)}
# Source brains whose people are deferred by decision. Without a row here an unconverted brain is deferred too,
# with no decision recorded. Nothing stages such a person with another brain.
DEFERRED_BRAINS = {'npc_fake_pursuit': 'Sean, 2026-11-16: ship the attack state without them, no idle stand-in; deferred '
                                       'until the pursuit AI (Libs/AI/final/fake_pursuit.xml) is converted'}
# Links a horse may have and still be idle, as `animal_population.convert` accepts them.
IDLE_HORSE_LINKS = ('horseHome', 'horsePoint', 'standPoint')
LEVEL_FILES = ('objects_mission0.xml', 'leveldata.xml', 'whdata_0', 'whdata_1', 'tables/ai/scheduler.xml', 'waitinglinks.xml')


def profile_actors(source, profiles):
    """The NPC placements of the source profiles, each with the name of its source brain."""
    from campaign_dependency_adapters import SourceTables
    from campaign_profile_actors import collect
    from campaign_sources import RetailSourceReader
    from upgrade_map import read
    source = Path(source)
    with RetailSourceReader(source) as reader:
        brains = {r['brain_id']: r['brain_name'] for r in SourceTables(source, reader).get('ai/brain')['rows']}
    with zipfile.ZipFile(source / 'Data/Levels' / SOURCE_LEVEL / 'level.pak') as archive:
        documents = {n: read(archive, n) for n in archive.namelist()
                     if n.replace(chr(92), '/').lower().startswith('layers/') and n.lower().endswith('.xml')}
        registry = ET.fromstring(read(archive, 'whdata_0'))
        actors = collect(ET.fromstring(read(archive, 'whdata_1')), registry, documents, profiles)
    brain = {s.findtext('Name'): s.findtext('StaticData/InitialAIData/BrainId') for s in registry.findall('./SoulList/Souls/Soul')}
    return [dict(actor, brain=brains.get(brain.get(actor['name']), brain.get(actor['name']))) for actor in actors]


def split_actors(actors, adapters):
    """(staged, deferred): an actor is staged only when the person route converts its source brain.

    Every other actor is a residue row `brain_<source brain>` with its soul. One soul is staged once; a
    second placement of it is deferred too, as the person route refuses it.
    """
    staged, deferred, souls = [], [], set()
    for actor in actors:
        row = dict(person=actor['name'], soul_id=actor['soul_id'], entity_guid=actor['entity_guid'], layer=actor['layer'])
        if actor['brain'] not in adapters:
            deferred.append(dict(row, kind='brain_' + str(actor['brain']), reason='No native person brain adapter for ' + str(actor['brain']),
                                 decision=DEFERRED_BRAINS.get(actor['brain'])))
        elif actor['soul_id'] in souls:
            deferred.append(dict(row, kind='soul_placed_twice', reason='one source instance per soul', decision=None))
        else:
            souls.add(actor['soul_id'])
            staged.append(actor)
    return staged, deferred


def stage_people(package, source, target, profiles, output, notify=print):
    """The NPCs of the source profiles as people of a staged level. Returns the summary (`people.json`).

    Only actors whose source brain the person route converts (`character_person_ai.BRAIN_ADAPTERS`) are
    staged; the rest are deferred and listed, never staged with another brain.
    """
    import character_person_ai
    from build_quest_people_test import build
    output = Path(output)
    staged, deferred = split_actors(profile_actors(source, profiles), character_person_ai.BRAIN_ADAPTERS)
    build(SimpleNamespace(source=Path(source), target=Path(target), mod=Path(package), output=output, model=None,
                          person=[a['name'] for a in staged], source_level=SOURCE_LEVEL, level=LEVEL, source_profile=[],
                          dialogue_profile=[], dialogue_model=[], quest_path=None, project_path=PROJECT, notify=notify))
    summary = people_summary(json.loads((output / 'report.json').read_text(encoding='utf-8')), profiles, staged, deferred)
    (output / 'people.json').write_text(json.dumps(summary, indent=1, sort_keys=True) + '\n', encoding='utf-8', newline='\n')
    return summary


def people_summary(report, profiles, staged, deferred):
    """Counts of a person-route report against the actors the profiles place: every actor is counted once."""
    converted = {r['soul_id']: r for r in report['converted']}
    existing = {r['soul_id'] for r in report['existing']}
    failed = [dict(person=p.get('person'), reason=p.get('reason')) for p in report['pending']]
    known = {f['person'] for f in failed}
    failed += [dict(person=a['name'], reason='not in the person route report') for a in staged
               if a['soul_id'] not in converted and a['soul_id'] not in existing and a['name'] not in known]
    summary = dict(profiles=list(profiles), actors=len(staged) + len(deferred),
                   converted=sum(a['soul_id'] in converted for a in staged), existing=sum(a['soul_id'] in existing for a in staged),
                   failed=failed, deferred=list(deferred), deferred_by_kind=dict(sorted(Counter(d['kind'] for d in deferred).items())),
                   brains=dict(sorted(Counter(str(a['brain']) for a in staged).items())),
                   archives=sorted(r['namespace'] for r in converted.values()), baseline=report['baseline'])
    if summary['converted'] + summary['existing'] + len(failed) + len(deferred) != summary['actors']:
        raise ValueError('A profile actor is neither staged, failed nor deferred')
    return summary


def profile_horses(source, profiles):
    """(horses, entities): the Horse placements of the profiles' own source layers, as world placements.

    Each horse: (placement, profile, its links, the names of the NPCs that link to it).
    """
    from animal_population_sources import transform, world
    from upgrade_map import read
    with zipfile.ZipFile(Path(source) / 'Data/Levels' / SOURCE_LEVEL / 'level.pak') as archive:
        entities, _ = world(archive, profiles)
        index = {n.replace(chr(92), '/').lower(): n for n in archive.namelist()}
        whdata = scenes.source_profiles(read(archive, index['whdata_1']))
        wanted = {}
        for name in profiles:
            for layer in whdata[name]['layers']:
                for entity in ET.fromstring(read(archive, index['layers/' + layer.lower() + '.xml'])).iter('Entity'):
                    if entity.get('EntityClass') == 'Horse':
                        wanted[entity.get('EntityId')] = name
    riders = {}
    for entity in entities.values():
        if entity.get('EntityClass') in ('NPC', 'NPC_Female'):
            for link in entity.findall('EntityLinks/Link'):
                if link.get('TargetId') in wanted:
                    riders.setdefault(link.get('TargetId'), []).append(entity.get('Name'))
    return [(transform(entities[key], entities), wanted[key], [dict(l.attrib) for l in entities[key].findall('EntityLinks/Link')],
             sorted(riders.get(key, []))) for key in sorted(wanted, key=int)], entities


def split_horses(horses, entities):
    """(idle, deferred rows): a horse is idle when nothing in the source drives it.

    Idle: every link is a home or standing point and no NPC links to the horse. A rider, a navigation
    path or a link to a controller holder means source AI moves it: residue `horse_driven_by_source_ai`.
    """
    idle, deferred = [], []
    for actor, profile, links, riders in horses:
        target = lambda link: entities.get(link.get('TargetId'))
        field = lambda link, name: target(link).get(name) if target(link) is not None else None
        driven = [dict(link=l.get('Name', ''), target=field(l, 'Name'), target_class=field(l, 'EntityClass'))
                  for l in links if l.get('Name') not in IDLE_HORSE_LINKS]
        if driven or riders:
            deferred.append(dict(kind='horse_driven_by_source_ai', horse=actor.get('Name'), profile=profile,
                                 entity_guid=actor.get('EntityGuid'), links=driven, riders=riders,
                                 reason='ridden, on a navigation path or linked to a controller in the source'))
        else:
            idle.append((actor, profile, links, riders))
    return idle, deferred


def stage_horses(files, source, target, profiles):
    """Place the profiles' idle horses in the level files. Returns (files, placed records, deferred rows).

    A horse the level already holds is kept. A horse the source AI drives is not placed.
    """
    from animal_population import native_catalog, place_horses
    from animal_population_sources import ANIMALS
    from campaign_entity_links import native_guid
    from upgrade_map import xml
    horses, entities = profile_horses(source, profiles)
    idle, deferred = split_horses(horses, entities)
    present = {e.get('EntityGuid') for e in ET.fromstring(files['objects_mission0.xml'])}
    new = [horse for horse in idle if native_guid(int(horse[0].get('EntityGuid'), 16)) not in present]
    records = [dict(name=horse[0].get('Name'), profile=horse[1], guid=native_guid(int(horse[0].get('EntityGuid'), 16)),
                    placed=horse in new, behaviour='idle in the source: native idle at the source placement') for horse in idle]
    if not new:
        return dict(files), records, deferred
    souls, horse_type, native = native_catalog(Path(target))
    files, placed = place_horses(files, [(horse[0], []) for horse in new], entities, native, horse_type)
    registry = ET.fromstring(files['whdata_0'])
    rows = registry.find('SoulList/Souls')
    for actor in placed:
        guid = native_guid(int(actor['guid'], 16))
        if any(s.findtext('EntityGuid') == guid or s.findtext('Name') == actor['name'] for s in rows):
            raise ValueError('Animal soul already registered: ' + actor['name'])
        row = ET.SubElement(rows, 'Soul', version='8')
        for key, value in dict(Name=actor['name'], SharedSoulGuid=souls[ANIMALS['Horse']],
                               Guid=str(uuid.uuid5(uuid.NAMESPACE_URL, 'gluemapper/animal/' + actor['guid'])),
                               EntityGuid=guid).items():
            ET.SubElement(row, key).text = value
    files['whdata_0'] = xml(registry)
    return files, records, deferred


def deferred_in_level(deferred, guids):
    """Names of deferred actors that the level holds all the same."""
    from campaign_entity_links import native_guid
    return sorted(str(row.get('person') or row.get('horse')) for row in deferred
                  if native_guid(int(row['entity_guid'], 16)) in guids)


def place_holders(files, project_blob, requirements):
    """One CutsceneHolder per converted video, bound to its alias through the project holder.

    Returns (files, project blob, records). Idempotent on an identical holder; a different one is refused.
    """
    from campaign_entity_links import append_links, native_guid
    from upgrade_map import xml
    mission = ET.fromstring(files['objects_mission0.xml'])
    project = ET.fromstring(project_blob)
    host = project.find('Skald/Project')
    owners = [e for e in mission if e.get('Name') == host.get('Name') and e.get('EntityClass') == 'SmartObjectHolder']
    if len(owners) != 1:
        raise ValueError('Level has no single project holder: ' + str(host.get('Name')))
    owner, assets = owners[0], host.find('Assets')
    links = owner.find('EntityLinks')
    if links is None: links = ET.SubElement(owner, 'EntityLinks')
    next_id = max(int(e.get('EntityId', '0')) for e in mission) + 1
    waiting, records = [], []
    for requirement in requirements:
        alias, cutscene = requirement['alias'], requirement['cutscene']
        guid = native_guid(int.from_bytes(hashlib.sha256(alias.encode()).digest()[:8], 'little'))
        label = "asset['" + alias + "']"
        existing = [e for e in mission if e.get('Name') == alias or e.get('EntityGuid') == guid]
        declared = assets.findall("*[@Name='" + alias + "']")
        if existing or declared:
            if (len(existing) != 1 or existing[0].get('EntityClass') != 'CutsceneHolder' or existing[0].get('EntityGuid') != guid
                    or existing[0].find("Properties[@esCutsceneName='" + cutscene + "']") is None
                    or [d.tag for d in declared] != ['CutsceneHolderAsset']):
                raise ValueError('Scene holder conflict: ' + alias)
            records.append(dict(alias=alias, cutscene=cutscene, guid=guid, placed=False))
            continue
        holder = ET.SubElement(mission, 'Entity', Name=alias, EntityGuid=guid, EntityId=str(next_id), EntityClass='CutsceneHolder',
                               Pos=owner.get('Pos'))
        next_id += 1
        ET.SubElement(holder, 'Properties', esCutsceneName=cutscene)
        ET.SubElement(assets, 'CutsceneHolderAsset', Name=alias)
        ET.SubElement(links, 'Link', Name=label, TargetId=holder.get('EntityId'), TargetGuid=guid)
        waiting.append((owner.get('EntityGuid'), guid, label))
        records.append(dict(alias=alias, cutscene=cutscene, guid=guid, placed=True))
    result = dict(files)
    result['objects_mission0.xml'] = xml(mission)
    if waiting:
        result['waitinglinks.xml'] = append_links(files['waitinglinks.xml'], waiting)
    return result, xml(project), records


def merge_subtitles(native, tables):
    """Add the movies' subtitle rows to a localization table.

    Two cuts of one scene share lines: an identical row is added once. A key that is already there with
    another text is refused.
    """
    from region_travel_dialogue import merge_localization
    cells = lambda row: tuple(c.text or '' for c in row.findall('Cell'))
    known = {cells(r)[0]: cells(r) for r in ET.fromstring(native).findall('Row') if r.findall('Cell')}
    table, added, shared = ET.Element('Table'), 0, 0
    for blob in tables:
        for row in ET.fromstring(blob).findall('Row'):
            key = cells(row)[0]
            if key in known:
                if known[key] != cells(row):
                    raise ValueError('Subtitle key collision: ' + key)
                shared += 1
                continue
            known[key] = cells(row)
            table.append(row); added += 1
    if not added:
        return native, dict(added=0, shared=shared)
    return merge_localization(native, ET.tostring(table, encoding='utf-8')), dict(added=added, shared=shared)


def seam(report):
    """What the controller converter (C2) needs of this stage, as one small document (`seam.json`).

    C2 fires `play_<alias>`, reads `pending_<alias>` and fires `done_<alias>` on the module; it runs the
    callback tree of every scene listed with callback_owner C2. Profiles are used under their native names.
    """
    ledger = report['ledger']
    ports = {p['Name']: (p['Direction'], p['Type']) for p in report['module']['ports']}
    rows = []
    for record in ledger['scenes']['records']:
        alias = scenes.identifier(record['alias'])
        rows.append(dict(alias=record['alias'], category=record['category'], requests=record['requests'],
                         picture='converted' if record['status'] == 'converted' else 'none: the request ends at once',
                         residue=next((r['kind'] for r in ledger['residue'] if r.get('alias') == record['alias']
                                       and r['kind'] in ('video_not_selected', 'scene_handoff', 'dialogue_scene', 'fader_scene')), None),
                         callback=record['callback'], callback_owner=record.get('callback_owner', 'C5'),
                         ports={kind: kind + '_' + alias for kind in ('play', 'pending', 'done', 'callback', 'finished')
                                if kind + '_' + alias in ports}))
    duties = {kind: sorted(r['duty'] for r in ledger['residue'] if r['kind'] == kind)
              for kind in ('playback_duty_native_player', 'playback_duty_deferred')}
    return dict(schema=1, quest=report['quest'], module=report['module']['name'], definition=report['module']['path'],
                port_types=dict(play='In trigger', pending='Out bool', done='In trigger', callback='Out trigger', finished='Out trigger'),
                bridge_wires=report['module']['bridge_wires'], scenes=rows,
                playback_duties=dict(native_player_for_converted_videos=duties['playback_duty_native_player'],
                                     nobody_yet=duties['playback_duty_deferred'], basis='inference; not runtime-verified'),
                profiles=[dict(source=r['source_profile'], native=r['profile'], layer=r['layer'], entities_in_layer=r['moved'],
                               source_entities=ledger['profiles'][r['source_profile']]['totals']['entities'])
                          for r in report['profiles']],
                requires_controller=report['requires_controller'], runtime_verified=False)


def movie_archive(quest, alias):
    return 'Data/gluemapper_scene_' + scenes.identifier(quest + '_' + alias) + '.pak'


def stage(package, source, target, quest, media, output, people=None, controller_owned=None, wiring=None, bridge=None,
          horses=True, write_movies=True, notify=print):
    """Stage the quest's scenes as an overlay of `package` under `output/overlay`. Returns the report.

    media: folder of `campaign_scenes.encode_video` results, one per converted alias.
    people: an existing `stage_people` output for this package; built into `output/people` when None.
    controller_owned: aliases whose callback the controller converter runs (default: every requested scene).
    wiring, bridge: the controller converter's wiring rows and the bridge instance name; without them the
    module is registered and not wired to a bridge.
    """
    from build_horse_trader_test import rewrite
    from upgrade_map import read, xml
    package, source, target, media, output = map(Path, (package, source, target, media, output))
    if output.exists() and any(output.iterdir()) and (people is None or Path(people) != output / 'people' or (output / 'overlay').exists()):
        raise FileExistsError('Choose a fresh stage folder')
    overlay = output / 'overlay'
    profiles = PEOPLE_PROFILES.get(quest, ())
    # 1. People.
    if people is None:
        people = output / 'people'
        stage_people(package, source, target, profiles, people, notify)
    people = Path(people)
    people_report = json.loads((people / 'people.json').read_text(encoding='utf-8'))
    baseline = {name: hashlib.sha256((package / name).read_bytes()).hexdigest() for name in (TRAVEL, ENGLISH_XML)}
    if any(people_report['baseline'].get(str(Path(name))) != digest for name, digest in baseline.items()):
        raise ValueError('The people were staged on another package')
    staged = people / 'package'
    with zipfile.ZipFile(staged / LEVEL_PAK) as archive:
        names = set(archive.namelist())
        files = {name: read(archive, name) for name in LEVEL_FILES if name in names}
    # 2. Horses.
    if people_report['failed']:
        raise ValueError('Profile people failed in the person route: ' + json.dumps(people_report['failed']))
    horse_records, deferred = [], list(people_report['deferred'])
    if horses and profiles:
        notify('Place the horses of ' + ', '.join(profiles))
        files, horse_records, horse_residue = stage_horses(files, source, target, profiles)
        deferred += horse_residue
    held = deferred_in_level(deferred, {e.get('EntityGuid') for e in ET.fromstring(files['objects_mission0.xml']).iter('Entity')})
    if held:
        raise ValueError('Deferred actors are in the level: ' + ', '.join(held))
    # 3. Scenes, against the staged level.
    with zipfile.ZipFile(staged / TRAVEL) as archive:
        entry, project = read(archive, ENTRY), read(archive, PROJECT)
        manifest = ET.parse(package / 'mod.manifest').findtext('info/modid')
    base_table = None
    if (package / OPENING).is_file():
        with zipfile.ZipFile(package / OPENING) as archive:
            base_table = read(archive, TABLE)
    receipts = []
    for alias in scenes.MAIN_PATH[quest]:
        receipts.append(json.loads((media / alias / 'receipt.json').read_text(encoding='utf-8')))
    movies, strings, subtitled = scenes.package_media(quest, receipts, media)
    owned = tuple(controller_owned) if controller_owned is not None else scenes.EVERY
    guids = {e.get('EntityGuid') for e in ET.fromstring(files['objects_mission0.xml']).iter('Entity')}
    notify('Convert the scenes of ' + quest)
    result = scenes.convert_retail(source, target, quest, controller_owned=owned, guids=guids, controller_profiles=True,
                                   cutscenes=base_table, subtitled=subtitled)
    if result['report']['wiring']:
        raise ValueError('The stage wires no objective actions: let the controller converter own the callbacks')
    # 4. Profiles.
    files, registered = scenes.register_profiles(files, result['plan'])
    # 5. Pictures.
    files, project, holders = place_holders(files, project, result['report']['world_requirements'])
    module_path = ENTRY.rsplit('/', 1)[0] + '/' + result['report']['module'] + '.xml'
    entry = scenes.attach(entry, result['module'], module_path.rsplit('/', 1)[1], result['report'], {})
    wired = 0
    if wiring is not None:
        entry, wired = scenes.wire_bridge(entry, bridge, wiring, result['report']['module'], result['module'])
    with zipfile.ZipFile(staged / ENGLISH_XML) as archive:
        dialog, subtitle_rows = merge_subtitles(read(archive, 'text_ui_dialog.xml'), strings)
    # 6. The overlay.
    resources = {ENTRY: entry, PROJECT: project, module_path: result['module']}
    resources.update({'Mods/' + manifest + '/Data/Levels/' + LEVEL + '/' + path: blob for path, blob in files.items()
                      if path.startswith('tables/')})
    rewrite(staged / TRAVEL, overlay / TRAVEL, resources)
    rewrite(staged / LEVEL_PAK, overlay / LEVEL_PAK, files)
    rewrite(staged / ENGLISH_XML, overlay / ENGLISH_XML, {'text_ui_dialog.xml': dialog})
    table_files = {TABLE: result['table']}
    table_files.update({path: Path(file).read_bytes() for path, file in movies.items() if not path.endswith('.bk2')})
    (overlay / 'Data').mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(overlay / 'Data/gluemapper_scenes.pak', 'x', zipfile.ZIP_STORED) as archive:
        for path, blob in sorted(table_files.items()):
            archive.writestr(path, blob)
    if base_table is not None:
        # Two archives would each carry a whole cutscene table: both get the same one.
        rewrite(package / OPENING, overlay / OPENING, {TABLE: result['table']})
    movie_records = []
    for receipt in receipts:
        path = scenes.ROOT + quest + '/' + receipt['alias'] + '/cinematic.bk2'
        name = movie_archive(quest, receipt['alias'])
        if write_movies:
            with zipfile.ZipFile(overlay / name, 'x', zipfile.ZIP_STORED, allowZip64=True) as archive:
                archive.write(movies[path], path)
        movie_records.append(dict(alias=receipt['alias'], archive=name, entry=path, bytes=receipt['bytes'], sha256=receipt['sha256'],
                                  signature=receipt['encoded']['signature'], written=bool(write_movies)))
    if write_movies:
        for pak in sorted((staged / 'Data').glob('*.pak')):
            if pak.name != 'gluemappertravel.pak':
                pak.replace(overlay / 'Data' / pak.name)
    model = result['model']
    # The deferred actors are residue of the conversion like any other row: none is dropped.
    ledger = dict(result['ledger'], residue=[*result['ledger']['residue'], *deferred])
    ledger['residue_by_kind'] = dict(sorted(Counter(r['kind'] for r in ledger['residue']).items()))
    result = dict(result, ledger=ledger)
    check = scenes.equivalence(model, result, {}, scenes.media_from_receipts(receipts))
    unregistered = sorted({n for pair in scenes.controller_switches(model) for n in pair if n} - set(result['plan']))
    report = dict(schema=1, converter=scenes.CONVERTER, quest=quest, package_baseline=baseline, requires_controller=True,
                  people={k: v for k, v in people_report.items() if k != 'baseline'}, horses=horse_records,
                  deferred=deferred, deferred_by_kind=dict(sorted(Counter(d['kind'] for d in deferred).items())),
                  decisions=dict(DEFERRED_BRAINS), profiles=registered,
                  unregistered_profiles=unregistered, holders=holders, movies=movie_records, subtitles=subtitle_rows,
                  module=dict(name=result['report']['module'], path=module_path, bridge_wires=wired,
                              controller_owned=sorted(r['alias'] for r in result['records'] if r.get('callback_owner') == 'C2'),
                              ports=[p.attrib for p in ET.fromstring(result['module']).iterfind('./Skald/Module/Ports/Port')],
                              passed_through=result['report']['passed_through']),
                  equivalence={k: check[k] for k in ('verdict', 'checked', 'passed', 'failed', 'residue', 'categories', 'media_not_run', 'failures')},
                  ledger=result['ledger'], runtime_verified=False)
    (output / 'report.json').write_text(json.dumps(report, indent=1, sort_keys=True, default=str) + '\n', encoding='utf-8', newline='\n')
    (output / 'seam.json').write_text(json.dumps(seam(report), indent=1, sort_keys=True) + '\n', encoding='utf-8', newline='\n')
    return report


def check_overlay(package, source, quest, output):
    """Layer 1 for the stage: compare a staged overlay with KCD1 and with the package it was staged on.

    Reads the archives again and derives every expectation from the source level, not from the report.
    """
    from animal_population_sources import transform, world
    from campaign_entity_links import native_guid
    from upgrade_map import read
    package, source, output = Path(package), Path(source), Path(output)
    overlay = output / 'overlay'
    failures, checked = [], Counter()

    def check(category, condition, message):
        checked[category] += 1
        if not condition:
            failures.append(dict(category=category, message=message))

    with zipfile.ZipFile(package / LEVEL_PAK) as archive:
        before = {e.get('EntityGuid'): e for e in ET.fromstring(read(archive, 'objects_mission0.xml'))}
    with zipfile.ZipFile(overlay / LEVEL_PAK) as archive:
        names = set(archive.namelist())
        mission = ET.fromstring(read(archive, 'objects_mission0.xml'))
        flat = {e.get('EntityGuid'): e for e in mission}
        manager = ET.fromstring(read(archive, 'whdata_1'))
        souls = {s.findtext('EntityGuid') for s in ET.fromstring(read(archive, 'whdata_0')).findall('./SoulList/Souls/Soul')}
        declared = {l.get('Name') for l in ET.fromstring(read(archive, 'leveldata.xml')).find('Layers')}
        registered = {p.findtext('Name'): p.findtext('GameLayers/GameLayer') for p in manager.iter('GameProfile')}
        layers = {name: ET.fromstring(read(archive, 'layers/' + layer + '.xml')) for name, layer in registered.items()
                  if 'layers/' + layer + '.xml' in names and name.startswith('gm_' + quest)}
    with zipfile.ZipFile(source / 'Data/Levels' / SOURCE_LEVEL / 'level.pak') as archive:
        index = {n.replace(chr(92), '/').lower(): n for n in archive.namelist()}
        profiles = scenes.source_profiles(read(archive, index['whdata_1']))
        entities, _ = world(archive, PEOPLE_PROFILES.get(quest, ()))
        own = {}
        for name in PEOPLE_PROFILES.get(quest, ()):
            partners = {layer for other, record in profiles.items() if other != name for layer in record['layers']}
            for layer in profiles[name]['layers']:
                if layer in partners:
                    continue
                for entity in ET.fromstring(read(archive, index['layers/' + layer.lower() + '.xml'])).iter('Entity'):
                    if entity.get('EntityClass') in ('NPC', 'NPC_Female', 'Horse'):
                        own.setdefault(name, []).append(entity)
    import character_person_ai
    converts = {a['entity_guid'].lower(): a['brain'] in character_person_ai.BRAIN_ADAPTERS
                for a in profile_actors(source, PEOPLE_PROFILES.get(quest, ()))}
    idle, driven = split_horses(*profile_horses(source, PEOPLE_PROFILES.get(quest, ())))
    converts.update({h[0].get('EntityGuid').lower(): True for h in idle})
    converts.update({row['entity_guid'].lower(): False for row in driven})
    listed = {str(row.get('person') or row.get('horse')): row for row in
              json.loads((output / 'report.json').read_text(encoding='utf-8'))['deferred']}
    everywhere = set(flat) | {e.get('EntityGuid') for layer in layers.values() for e in layer}
    moved = set()
    for name, layer in layers.items():
        check('profiles', registered[name] in declared, 'layer of ' + name + ' is not declared in the level')
        for entity in layer:
            guid = entity.get('EntityGuid')
            check('moved', guid not in flat and guid not in moved and entity.get('Layer') == registered[name],
                  'entity is in two places or has the wrong layer: ' + str(entity.get('Name')))
            moved.add(guid)
            if guid in before:
                was = dict(before[guid].attrib)
                now = {k: v for k, v in entity.attrib.items() if k != 'Layer'}
                check('moved', now == {k: v for k, v in was.items() if k != 'Layer'}, 'a moved entity changed: ' + str(entity.get('Name')))
    for name, placed in own.items():
        layer = {e.get('EntityGuid'): e for e in layers.get(scenes.profile_name(name), ())}
        expected = 0
        for original in placed:
            actor = transform(original, entities) if original.get('ParentId') else original     # world placement
            found = layer.get(native_guid(int(actor.get('EntityGuid'), 16)))
            label = name + ': ' + str(actor.get('Name'))
            if not converts[original.get('EntityGuid').lower()]:
                row = listed.get(actor.get('Name'))
                check('deferred', native_guid(int(actor.get('EntityGuid'), 16)) not in everywhere and native_guid(int(actor.get('EntityGuid'), 16)) not in souls,
                      'a deferred source actor is in the level: ' + label)
                check('deferred', row is not None and row['kind'].startswith(('brain_', 'horse_')) and row['entity_guid'].lower() == original.get('EntityGuid').lower(),
                      'a deferred source actor is not listed as residue: ' + label)
                continue
            expected += 1
            check('actors', found is not None, 'source actor is not in the profile layer: ' + label)
            if found is None:
                continue
            numbers = lambda entity, field: [round(float(v), 3) for v in entity.get(field).split(',')] if entity.get(field) else None
            same = lambda field: numbers(found, field) == numbers(actor, field)
            check('actors', found.get('Name') == actor.get('Name') and found.get('EntityClass') == actor.get('EntityClass')
                  and same('Pos') and (actor.get('Rotate') is None or same('Rotate')), 'name, class or placement differs: ' + label)
            check('actors', found.get('EntityGuid') in souls, 'actor has no soul record: ' + label)
        check('actors', len(layer) == expected, 'layer of ' + name + ' holds ' + str(len(layer)) + ' entities for ' + str(expected) + ' staged source actors')
    check('deferred', len(listed) == sum(not v for v in converts.values()), 'the residue lists ' + str(len(listed)) + ' deferred actors, the source has '
          + str(sum(not v for v in converts.values())))
    check('level', set(before) - set(flat) <= moved, 'an entity left the flat level without entering a profile layer')
    added = Counter(e.get('EntityClass') for guid, e in flat.items() if guid not in before)
    with zipfile.ZipFile(overlay / 'Data/gluemapper_scenes.pak') as archive:
        table = ET.fromstring(archive.read(TABLE))
        packed = set(archive.namelist())
    with zipfile.ZipFile(overlay / ENGLISH_XML) as archive:
        strings = {r.findtext('Cell') for r in ET.fromstring(read(archive, 'text_ui_dialog.xml')).findall('Row')}
    with zipfile.ZipFile(package / ENGLISH_XML) as archive:
        old_strings = [r.findtext('Cell') for r in ET.fromstring(read(archive, 'text_ui_dialog.xml')).findall('Row')]
    check('subtitles', set(old_strings) <= strings, 'a localization row of the package was lost')
    with zipfile.ZipFile(overlay / TRAVEL) as archive:
        entry = ET.fromstring(read(archive, ENTRY))
        project = ET.fromstring(read(archive, PROJECT))
        module_name = scenes.identifier('gm_' + quest + '_scenes')
        module = ET.fromstring(read(archive, ENTRY.rsplit('/', 1)[0] + '/' + module_name + '.xml'))
        helper = ENTRY.rsplit('/', 1)[0] + '/' + next(d.get('File') for d in module.iterfind('./Skald/Module/Definitions/Definition'))
        check('module', helper in archive.namelist(), 'the module names a helper definition the package does not hold')
    check('module', len(entry.findall("./Skald/Level/Nodes/" + module_name)) == 1
          and len(entry.findall("./Skald/Level/Definitions/Definition[@File='" + module_name + ".xml']")) == 1, 'module is not registered once')
    for alias in scenes.MAIN_PATH[quest]:
        holder, row = scenes.holder_alias(quest, alias), scenes.cutscene_name(quest, alias)
        found = [e for e in mission if e.get('Name') == holder and e.get('EntityClass') == 'CutsceneHolder']
        check('pictures', len(found) == 1 and found[0].find("Properties[@esCutsceneName='" + row + "']") is not None, 'holder of ' + alias)
        check('pictures', len(project.findall(".//Assets/CutsceneHolderAsset[@Name='" + holder + "']")) == 1
              and len(module.findall(".//CutsceneHandler/Asset[@Alias='" + holder + "']")) == 1, 'holder alias of ' + alias)
        rows = table.findall("./Cutscenes/RenderedCutscene[@Name='" + row + "']")
        root = scenes.ROOT + quest + '/' + alias
        check('pictures', len(rows) == 1 and rows[0].get('Root') == root and rows[0].get('Subtitles') == 'cinematic'
              and rows[0].find('Profiles/Profile').get('FileName') == 'cinematic', 'cutscene row of ' + alias)
        check('subtitles', root + '/cinematic.srt' in packed, 'subtitle file of ' + alias)
        if root + '/cinematic.srt' in packed:
            with zipfile.ZipFile(overlay / 'Data/gluemapper_scenes.pak') as archive:
                keys = [l.strip() for l in archive.read(root + '/cinematic.srt').decode('utf-8-sig').splitlines() if l.startswith('gm_cin_')]
            check('subtitles', keys and set(keys) <= strings, 'a subtitle cue of ' + alias + ' has no localization row')
    return dict(verdict='PASS' if not failures else 'FAIL', checked=sum(checked.values()), failed=len(failures),
                categories=dict(sorted(checked.items())), added_to_the_flat_level=dict(sorted(added.items())),
                in_profile_layers={name: len(layer) for name, layer in sorted(layers.items())}, failures=failures[:40])


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--kcd1', type=Path, default=Path('D:/SteamLibrary/steamapps/common/KingdomComeDeliverance'))
    parser.add_argument('--kcd2', type=Path, default=Path('D:/SteamLibrary/steamapps/common/KingdomComeDeliverance2'))
    parser.add_argument('--quest', default='q_skalitz')
    parser.add_argument('--package', type=Path, required=True)
    parser.add_argument('--media', type=Path, help='folder of encoded videos, one per alias')
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--people', type=Path, help='an existing people stage of this package')
    parser.add_argument('--people-only', action='store_true', help='stage the profile people and stop')
    parser.add_argument('--no-movies', action='store_true', help='record the movie and person archives without writing them')
    parser.add_argument('--no-horses', action='store_true')
    parser.add_argument('--check', action='store_true', help='compare an existing stage output with KCD1 and the package, and stop')
    args = parser.parse_args(argv)
    if args.check:
        result = check_overlay(args.package, args.kcd1, args.quest, args.output)
        (args.output / 'overlay-check.json').write_text(json.dumps(result, indent=1, sort_keys=True) + '\n', encoding='utf-8', newline='\n')
        print(json.dumps(result, indent=1))
        return 0 if result['verdict'] == 'PASS' else 1
    if args.people_only:
        summary = stage_people(args.package, args.kcd1, args.kcd2, PEOPLE_PROFILES[args.quest], args.output)
        print(json.dumps({k: summary[k] for k in ('actors', 'converted', 'existing', 'brains', 'deferred_by_kind')}, indent=1), len(summary['failed']), 'failed')
        return 0
    report = stage(args.package, args.kcd1, args.kcd2, args.quest, args.media, args.output, people=args.people,
                   horses=not args.no_horses, write_movies=not args.no_movies)
    report['people'] = {k: v for k, v in report['people'].items() if k != 'deferred'}
    print(json.dumps({k: report[k] for k in ('people', 'deferred_by_kind', 'profiles', 'unregistered_profiles', 'subtitles', 'equivalence')}, indent=1, default=str))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
