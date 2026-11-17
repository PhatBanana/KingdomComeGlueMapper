"""C5 stage: the scenes of one KCD1 quest on a built package.

Order, each step reading what the one before staged:

    people     the NPCs of the quest's state profiles through the person route
               (`build_quest_people_test.build --source-profile`), so they are
               mission placements of the staged level
    horses     the horses of those profiles through `animal_population.place_horses`,
               standing where the source placed them (stand-in: their quest links
               belong to the controller that drives them)
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
LEVEL_FILES = ('objects_mission0.xml', 'leveldata.xml', 'whdata_0', 'whdata_1', 'tables/ai/scheduler.xml', 'waitinglinks.xml')


def stage_people(package, source, target, profiles, output, notify=print):
    """The NPCs of the source profiles as people of a staged level. Returns the person route's report."""
    from build_quest_people_test import build
    build(SimpleNamespace(source=Path(source), target=Path(target), mod=Path(package), output=Path(output), model=None,
                          person=[], source_level=SOURCE_LEVEL, level=LEVEL, source_profile=list(profiles),
                          dialogue_profile=[], dialogue_model=[], quest_path=None, project_path=PROJECT, notify=notify))
    return json.loads((Path(output) / 'report.json').read_text(encoding='utf-8'))


def people_summary(report, profiles):
    """Counts of a person-route report against the actors the profiles place."""
    actors = report['source_profile_actors']
    done = {r['soul_id'] for r in report['converted']} | {r['soul_id'] for r in report['existing']}
    missing = sorted(a['name'] for a in actors if a['soul_id'] not in done)
    return dict(profiles=list(profiles), actors=len(actors), converted=len(report['converted']), existing=len(report['existing']),
                failed=[dict(person=p.get('person'), reason=p.get('reason')) for p in report['pending']], missing=missing)


def profile_horses(source, profiles):
    """(horses, entities): the Horse placements of the profiles' own source layers, as world placements."""
    from animal_population_sources import transform, world
    from upgrade_map import read
    with zipfile.ZipFile(Path(source) / 'Data/Levels' / SOURCE_LEVEL / 'level.pak') as archive:
        entities, _ = world(archive, profiles)
        index = {n.replace('\\', '/').lower(): n for n in archive.namelist()}
        whdata = scenes.source_profiles(read(archive, index['whdata_1']))
        wanted = {}
        for name in profiles:
            for layer in whdata[name]['layers']:
                for entity in ET.fromstring(read(archive, index['layers/' + layer.lower() + '.xml'])).iter('Entity'):
                    if entity.get('EntityClass') == 'Horse':
                        wanted[entity.get('EntityId')] = name
    return [(transform(entities[key], entities), wanted[key], [l.attrib for l in entities[key].findall('EntityLinks/Link')])
            for key in sorted(wanted, key=int)], entities


def stage_horses(files, source, target, profiles):
    """Place the profiles' horses in the level files. Returns (files, records).

    A horse the level already holds is kept. The source links (a controller holder, a navigation path) are
    recorded and not converted: the horse stands at its source placement with the native idle activity.
    """
    from animal_population import native_catalog, place_horses
    from animal_population_sources import ANIMALS
    from campaign_entity_links import native_guid
    from upgrade_map import xml
    horses, entities = profile_horses(source, profiles)
    present = {e.get('EntityGuid') for e in ET.fromstring(files['objects_mission0.xml'])}
    new = [(actor, profile, links) for actor, profile, links in horses
           if native_guid(int(actor.get('EntityGuid'), 16)) not in present]
    records = [dict(name=actor.get('Name'), profile=profile, guid=native_guid(int(actor.get('EntityGuid'), 16)),
                    placed=(actor, profile, links) in new, source_links=links, behaviour='stand-in: native idle at the source placement')
               for actor, profile, links in horses]
    if not new:
        return dict(files), records
    souls, horse_type, native = native_catalog(Path(target))
    files, placed = place_horses(files, [(actor, []) for actor, _, _ in new], entities, native, horse_type)
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
    return files, records


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
    people_report = json.loads((people / 'report.json').read_text(encoding='utf-8'))
    baseline = {name: hashlib.sha256((package / name).read_bytes()).hexdigest() for name in (TRAVEL, ENGLISH_XML)}
    if any(people_report['baseline'].get(str(Path(name))) != digest for name, digest in baseline.items()):
        raise ValueError('The people were staged on another package')
    staged = people / 'package'
    with zipfile.ZipFile(staged / LEVEL_PAK) as archive:
        names = set(archive.namelist())
        files = {name: read(archive, name) for name in LEVEL_FILES if name in names}
    # 2. Horses.
    horse_records = []
    if horses and profiles:
        notify('Place the horses of ' + ', '.join(profiles))
        files, horse_records = stage_horses(files, source, target, profiles)
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
    check = scenes.equivalence(model, result, {}, scenes.media_from_receipts(receipts))
    unregistered = sorted({n for pair in scenes.controller_switches(model) for n in pair if n} - set(result['plan']))
    report = dict(schema=1, converter=scenes.CONVERTER, quest=quest, package_baseline=baseline, requires_controller=True,
                  people=people_summary(people_report, profiles), horses=horse_records, profiles=registered,
                  unregistered_profiles=unregistered, holders=holders, movies=movie_records, subtitles=subtitle_rows,
                  module=dict(name=result['report']['module'], path=module_path, bridge_wires=wired,
                              controller_owned=sorted(r['alias'] for r in result['records'] if r.get('callback_owner') == 'C2'),
                              ports=[p.attrib for p in ET.fromstring(result['module']).iterfind('./Skald/Module/Ports/Port')],
                              passed_through=result['report']['passed_through']),
                  equivalence={k: check[k] for k in ('verdict', 'checked', 'passed', 'failed', 'residue', 'categories', 'media_not_run', 'failures')},
                  ledger=result['ledger'], runtime_verified=False)
    (output / 'report.json').write_text(json.dumps(report, indent=1, sort_keys=True, default=str) + '\n', encoding='utf-8', newline='\n')
    return report


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
    args = parser.parse_args(argv)
    if args.people_only:
        report = stage_people(args.package, args.kcd1, args.kcd2, PEOPLE_PROFILES[args.quest], args.output)
        print(json.dumps(people_summary(report, PEOPLE_PROFILES[args.quest]), indent=1))
        return 0
    report = stage(args.package, args.kcd1, args.kcd2, args.quest, args.media, args.output, people=args.people,
                   horses=not args.no_horses, write_movies=not args.no_movies)
    print(json.dumps({k: report[k] for k in ('people', 'profiles', 'unregistered_profiles', 'subtitles', 'equivalence')}, indent=1, default=str))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
