"""Select KCD1 town residents in bulk and report the residue.

Every NPC placed in KCD1's base world (objects_mission0.xml) inside a selected
town is planned through the same converters the resident stage uses. A person
is selected when the stage can give them their KCD1 work today: a source home,
only home-time intervals unlinked, and every linked activity supported by a
native work adapter. QUEST_PEOPLE are selected without work (native wait at
their KCD1 spot) because quests need them placed. Everyone else is residue,
with the reason, so blockers can be fixed in bulk rather than person by person.

Towns are areas (centre and radius in KCD1 metres), never name prefixes.

Usage:
  python resident_census.py --source KCD1 --town rattay [--town sasau ...] [--package PKG]
                            [--actor-report stage/actors/report.json ...] [--out resident_selection.json]

Resumable: each planned person is appended to <out>.progress.jsonl and skipped
on a rerun. --actor-report moves people whose appearance conversion failed in a
dry run into the residue.
"""
import argparse
from collections import Counter, defaultdict
import json
from pathlib import Path
import xml.etree.ElementTree as E
import zipfile

# Town centres and radii in KCD1 metres. The first six match the gate's
# world_survey table; the rest are the median position of each town's KCD1
# base-world NPCs. First match wins, so the monastery comes before Sasau.
TOWNS = {
    'monastery': ((937.0, 1687.0), 120.0),
    'uzhitz': ((3113.0, 3322.0), 350.0),
    'merhojed': ((1677.0, 2603.0), 250.0),
    'samopesh': ((1146.0, 2305.0), 250.0),
    'skalitz': ((788.0, 3396.0), 192.0),
    'rattay': ((2578.0, 605.0), 427.0),
    'talmberg': ((2331.0, 2771.0), 234.0),
    'neuhof': ((3521.0, 1456.0), 238.0),
    'sasau': ((918.0, 1283.0), 557.0),
    'ledetchko': ((2036.0, 1316.0), 308.0),
}
# Souls a quest branch registers itself (feat/kcd1-quests-1).
RESERVED = frozenset({'rat_refugee_ales'})
# Placed people the KCD1 main quests up to the hunt need, with or without work
# (feat/kcd1-quests-1, 2026-11-14).
QUEST_PEOPLE = frozenset({'rat_bernard', 'rat_bailiff', 'rat_hanus', 'rat_racek_kobyla', 'rat_ptacek',
                          'rat_guardJanik', 'rat_refugee_jana', 'rat_refugee_beggar', 'rat_parson',
                          # q_escapeToTalmberk (Talmberg session, 2026-11-14).
                          'tal_borek', 'tal_divis', 'tal_stepanka', 'tal_castlemaid1', 'prib_kolik'})
GARRISON = 'final/sa_garrison.xml:Guard'


def town_of(pos):
    if pos is None:
        return None
    for name, ((cx, cy), r) in TOWNS.items():
        if (pos[0] - cx) ** 2 + (pos[1] - cy) ** 2 <= r * r:
            return name
    return None


def position(entity):
    try:
        x, y, *_ = (float(v) for v in entity.get('Pos', '').split(','))
        return x, y
    except ValueError:
        return None


def bucket(row):
    """Selection decision for one planned person: ('selected'|'residue', reason)."""
    if row.get('error'):
        return 'residue', 'source data: ' + row['error']
    if row['soul_rows'] != 1:
        return 'residue', f"soul name has {row['soul_rows']} soul rows (select by soul id)"
    if row['keeper']:
        return 'residue', 'shop keeper: shop route (setup_merchant_upgrade)'
    if row['reserved']:
        return 'residue', 'registered by a quest branch'
    if row.get('brain_error'):
        return 'residue', 'native brain or social class: ' + row['brain_error']
    if row['quest']:
        return 'selected', 'quest person'
    if not row['home']:
        return 'residue', 'no KCD1 home'
    if row['blocking']:
        return 'residue', 'unlinked work: ' + ', '.join(sorted(set(row['blocking'])))
    if not row['trees']:
        return 'residue', 'no linked work'
    unsupported = sorted({t for t, ok in row['trees'] if not ok})
    if unsupported:
        return 'residue', 'work adapter missing: ' + ', '.join(unsupported)
    if any(t == GARRISON for t, _ in row['trees']) and not row['forced_workplace']:
        return 'residue', 'town guard: garrison allocator missing'
    return 'selected', 'work: ' + ', '.join(sorted({t.split('/')[-1] for t, _ in row['trees']}))


def native_contracts(target):
    """KCD2 brain and social class tables the actor stage maps every soul onto."""
    from character_person import native_xml
    from upgrade_map import read
    with zipfile.ZipFile(Path(target)/'Data/Tables.pak') as archive:
        return (native_xml(read(archive, 'Libs/Tables/ai/brain.xml')),
                native_xml(read(archive, 'Libs/Tables/rpg/social_class.xml')))


def plan_people(source, names, tables, progress_path, native=None):
    from build_profile_systems import source_world
    from campaign_profile_actors import select
    from character_person_ai import capture_person_ai, index_person_links, native_brain_and_class
    from character_schedule import plan, blocking_pending, has_home
    from character_schedule_jobs import population_work_supports
    from setup_merchant_upgrade import MERCHANTS
    from upgrade_map import read
    done = {}
    if progress_path.exists():
        for line in progress_path.read_text(encoding='utf-8').splitlines():
            row = json.loads(line); done[row['person']] = row
    todo = [n for n in names if n not in done]
    if not todo:
        return done
    soul_rows = Counter(r['soul_name'] for r in tables.get('rpg/soul')['rows'])
    keeper_ids = {r['keeper_id'] for r in tables.get('shop/shopkeeper')['rows']}
    merchant_names = {person for person, _ in MERCHANTS}
    with zipfile.ZipFile(source/'Data/Levels/rataje/level.pak') as z:
        documents, entities = source_world(z)
        souls = E.fromstring(read(z, 'whdata_0')); profiles = E.fromstring(read(z, 'whdata_1'))
    by_guid = {e.get('EntityGuid'): e for e in entities if e.get('EntityGuid')}
    instances = {s.findtext('Guid'): s for s in souls.findall('SoulList/Souls/Soul')}
    links = index_person_links(entities)
    with progress_path.open('a', encoding='utf-8') as out:
        for index, name in enumerate(todo, 1):
            row = dict(person=name, soul_rows=soul_rows[name], reserved=name in RESERVED, quest=name in QUEST_PEOPLE,
                       keeper=name in merchant_names, home=False, blocking=[], trees=[], forced_workplace=False)
            try:
                record = select(profiles, souls, documents, [name])[0]
                soul = tables.row('rpg/soul', 'soul_id', record['soul_id'])
                row['keeper'] = row['keeper'] or record['soul_id'] in keeper_ids
                person = dict(name=name, soul=soul, actor=by_guid[record['entity_guid']],
                              instance=instances[record['instance_id']], source_level='rataje')
                person['ai'] = capture_person_ai(tables, soul, person['actor'], person['instance'], entities, links)
                if native is not None:
                    try:
                        native_brain_and_class(person['ai'], *native)
                    except ValueError as error:
                        row['brain_error'] = (f"{error} (brain {person['ai']['source_brain'].get('brain_name')}, "
                                              f"class {person['ai']['source_social_class'].get('social_class_name')})")
                schedule = plan(person, tables)
                row['home'] = has_home(person)
                row['blocking'] = [p.get('activity', '?') for p in blocking_pending(schedule, person, True)]
                row['trees'] = [(e['behavior']['tree_file'].replace('\\', '/').lower() + ':' + e['behavior']['tree_name'],
                                 bool(population_work_supports(e))) for e in schedule['resolved']]
                row['forced_workplace'] = any(l['label'] == 'garrison_forcedWorkplace' for l in person['ai']['links'])
            except Exception as error:   # source data the converters reject is residue, not a crash
                row['error'] = f'{type(error).__name__}: {error}'[:300]
            out.write(json.dumps(row) + '\n'); out.flush()
            done[name] = row
            print(f'{index}/{len(todo)} {name}', flush=True)
    return done


def census(source, towns, package=None, actor_reports=(), progress_path=None, target=None):
    from campaign_sources import RetailSourceReader
    from campaign_dependency_adapters import SourceTables
    from upgrade_map import read
    unknown = set(towns) - set(TOWNS)
    if unknown:
        raise ValueError('Unknown town: ' + ', '.join(sorted(unknown)))
    with zipfile.ZipFile(source/'Data/Levels/rataje/level.pak') as z:
        souls = E.fromstring(read(z, 'whdata_0'))
        mission = E.fromstring(read(z, 'objects_mission0.xml'))
    names_by_guid = {int(s.findtext('EntityGuid')): s.findtext('Name')
                     for s in souls.findall('SoulList/Souls/Soul') if s.findtext('EntityGuid')}
    placed = {}
    for e in mission.iter('Entity'):
        if e.get('EntityClass') not in ('NPC', 'NPC_Female') or not e.get('EntityGuid'):
            continue
        name = names_by_guid.get(int(e.get('EntityGuid'), 16))
        town = town_of(position(e))
        if name and town in towns:
            placed[name] = town
    converted = set()
    if package is not None:
        with zipfile.ZipFile(Path(package)/'Data/Levels/kcd1_travel/level.pak') as z:
            converted = {e.get('Name') for e in E.fromstring(read(z, 'objects_mission0.xml')).iter('Entity')
                         if e.get('EntityClass') in ('NPC', 'NPC_Female')}
    failed = {}
    for report in actor_reports:
        for row in json.loads(Path(report).read_text(encoding='utf-8')).get('pending', []):
            if row.get('person'):
                failed[row['person']] = row.get('reason', 'appearance conversion failed')
    names = sorted(n for n in placed if n not in converted)
    with RetailSourceReader(source) as reader:
        rows = plan_people(source, names, SourceTables(source, reader), progress_path,
                           native_contracts(target) if target is not None else None)
    selected, residue, counts = [], [], defaultdict(Counter)
    for name in names:
        kind, reason = bucket(rows[name])
        if kind == 'selected' and name in failed:
            kind, reason = 'residue', 'appearance: ' + failed[name]
        entry = dict(person=name, town=placed[name])
        if kind == 'selected':
            selected.append(dict(entry, work=reason))
        else:
            residue.append(dict(entry, reason=reason.split(':')[0], detail=reason))
        counts[placed[name]][reason.split(':')[0] if kind == 'residue' else 'selected'] += 1
    for name in sorted(n for n in placed if n in converted):
        counts[placed[name]]['already converted'] += 1
    return dict(version=1, source_level='rataje', towns={t: TOWNS[t] for t in towns},
                selected=selected, residue=residue, counts={t: dict(c) for t, c in sorted(counts.items())})


def selection_module(result):
    """Source of tools/resident_selection.py: the selected people per town, residue counts as comments."""
    lines = ['"""Generated by resident_census.py; do not edit by hand. Rerun the census to change it.', '',
             'Selected KCD1 town residents per town. Residue (people not selected) by reason:']
    for town, counts in result['counts'].items():
        lines.append(f'  {town}: ' + ', '.join(f'{k} {v}' for k, v in sorted(counts.items(), key=lambda kv: -kv[1])))
    lines += ['"""', '', 'RESIDENTS = {']
    by_town = defaultdict(list)
    for row in result['selected']:
        by_town[row['town']].append(row['person'])
    for town in sorted(by_town):
        lines.append(f'    {town!r}: (')
        names = sorted(by_town[town])
        for i in range(0, len(names), 6):
            lines.append('        ' + ' '.join(f'{n!r},' for n in names[i:i + 6]))
        lines.append('    ),')
    lines.append('}')
    return '\n'.join(lines) + '\n'


def main(argv=None):
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('--source', type=Path, required=True)
    p.add_argument('--town', action='append', required=True)
    p.add_argument('--package', type=Path)
    p.add_argument('--target', type=Path, help='KCD2 install: check each soul maps to a native brain and social class')
    p.add_argument('--actor-report', action='append', default=[])
    p.add_argument('--out', type=Path, required=True, help='full JSON report: selection, residue and counts')
    p.add_argument('--module', type=Path, help='also write the generated selection module (tools/resident_selection.py)')
    a = p.parse_args(argv)
    result = census(a.source, a.town, a.package, a.actor_report, a.out.with_name(a.out.name + '.progress.jsonl'), a.target)
    a.out.write_text(json.dumps(result, indent=1) + '\n', encoding='utf-8')
    if a.module is not None:
        a.module.write_text(selection_module(result), encoding='utf-8')
    for town, c in result['counts'].items():
        print(town, dict(c))
    print(f"selected {len(result['selected'])}, residue {len(result['residue'])} -> {a.out}")


if __name__ == '__main__':
    main()
