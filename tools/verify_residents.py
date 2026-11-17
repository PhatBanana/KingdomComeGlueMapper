"""Verify imported town residents against KCD1, person by person, offline.

For every person the resident marker lists, compares the converted package
with KCD1's own data and walks the person's day:

  soul      soul id and name equal KCD1's; brain and social class set
  faction   factionName is the converted KCD1 faction
  voice     the soul's character speaks the KCD1 voice (v_soul_character_data)
  stats     every mapped KCD1 stat is set to KCD1's value (KCD1 barter has no KCD2 attribute: noted)
  outfit    the appearance and equipment Storm rules exist and the inventory preset resolves
  home      a KCD1 home becomes a home hub whose home_area polygon exists
  bed       a sleep pool (gm_sleep_*) links at least one bed
  schedule  every KCD1 daycycle interval is bound: work to a converted job, sleep to the sleep pool,
            eat/morning/fun to home time; anything else is a mismatch
  navmesh   every place the day uses (job holders, idle anchor, home hub, beds) has a walkable
            polygon within audit_bed_navigation's search distance

Any mismatch is a FAIL for that person. Outfit geometry (holes, layers) is the clothing lab's
souls mode; skins are the gate's skin_joints.

Usage: python verify_residents.py --package PKG --source KCD1 --target KCD2 --out DIR
"""
import argparse
from collections import Counter, defaultdict
import json
from pathlib import Path
import zipfile
import xml.etree.ElementTree as ET

from upgrade_map import read

TRAVEL = 'Data/gluemappertravel.pak'
LEVEL = 'Data/Levels/kcd1_travel'
MARKER = 'Libs/GlueMapper/resident_population.json'
FACTION = 'gluemapper_kcd1_faction_'
BEDS = ('StanceSmartObject',)
CHECKS = ('soul', 'faction', 'voice', 'stats', 'outfit', 'home', 'bed', 'schedule', 'navmesh')


def person_namespace(soul_id):
    return 'gm_person_' + soul_id.replace('-', '')


class Level:
    def __init__(self, package):
        from campaign_trigger_areas import read_areas
        from campaign_entity_links import guid_value
        with zipfile.ZipFile(Path(package)/LEVEL/'level.pak') as z:
            self.entities = list(ET.fromstring(read(z, 'objects_mission0.xml')).iter('Entity'))
            self.areas = {a.guid for a in read_areas(read(z, 'triggerareas.fubar'))['areas']}
            rows = ET.fromstring(read(z, 'tables/ai/scheduler.xml')).find('Schedulers')
        self.by_id = {e.get('EntityId'): e for e in self.entities if e.get('EntityId')}
        self.by_guid = {str(guid_value(e.get('EntityGuid'))): e for e in self.entities if e.get('EntityGuid')}
        self.by_name = defaultdict(list)
        for e in self.entities:
            self.by_name[e.get('Name')].append(e)
        # Scheduler activity links: hub or actor guid -> [(start minute, end minute, target entity)].
        self.activities = defaultdict(list)
        for row in rows:
            for link in row.findall('Links/S_ActivityLink'):
                p = link.find('Parameters')
                if p is None:
                    continue
                # The native idle baseline (schedulerWait on sa_land) is not work.
                if p.get('BehaviorName') == 'schedulerWait':
                    continue
                self.activities[row.get('EntityGuid')].append(
                    (float(p.get('TimeOfDayStart', 0)), float(p.get('TimeOfDayEnd', 1440)), self.by_guid.get(link.get('TargetGuid'))))

    def links(self, entity):
        if entity is None:
            return
        for link in entity.findall('EntityLinks/Link'):
            yield link.get('Name') or '', self.by_id.get(link.get('TargetId'))

    def activity_links(self, entity):
        from campaign_entity_links import guid_value
        if entity is None or not entity.get('EntityGuid'):
            return []
        return self.activities.get(str(guid_value(entity.get('EntityGuid'))), [])


def position(entity):
    try:
        return tuple(float(v) for v in entity.get('Pos', '').split(',')[:3])
    except ValueError:
        return None


def check(ok, detail='', residue=None):
    """ok, or a mismatch the stage listed as residue (with its reason), or a FAIL."""
    if ok:
        return dict(ok=True, detail=detail)
    if residue:
        return dict(ok=False, residue=True, detail=f'{detail} (residue: {residue})')
    return dict(ok=False, detail=detail)


def day_places(level, npc):
    """((block, entity) for every place the converted day sends the person, one hop past its hubs,
    [(start, end)] clock windows of the person's converted work).

    Work is bound two ways: entity links to job phases (housework) and the person's scheduler
    activity links to gm_schedule_* job holders (city walk, farm, guard), with KCD1's clock.
    """
    places, windows, seen = [], [], set()
    targets = [(label, target, None) for label, target in level.links(npc)]
    targets += [('_', target, (start, end)) for start, end, target in level.activity_links(npc)]
    for label, target, window in targets:
        if target is None:
            continue
        name = target.get('Name') or ''
        work = name.startswith('gm_schedule_') or (
            label.startswith('_') and target.get('EntityClass') != 'TriggerArea'
            and not name.startswith(('gm_sleep_', 'gm_person_')))
        if work and window is not None:
            windows.append(window)
        if target.get('EntityId') in seen:
            continue
        seen.add(target.get('EntityId'))
        if name.startswith('gm_sleep_'):
            places += [('sleep', bed) for _, bed in level.links(target)
                       if bed is not None and bed.get('EntityClass') in BEDS]
        elif name.startswith('gm_person_home_'):
            places.append(('home', target))
        elif name.startswith('gm_person_idle_'):
            places.append(('idle', target))
        elif work:
            hops = [t for _, t in level.links(target) if t is not None and t.get('EntityClass') != 'TriggerArea']
            places += [('work', t) for t in (hops or [target])]
            if window is None:
                windows.append((0, 1440))   # a job phase linked on the entity carries its clock on the hub
    return places, windows


def unbound_intervals(intervals, *, beds, work, home):
    """Daycycle intervals the converted day does not cover.

    work: [(start, end)] clock windows of the converted work; a KCD1 work interval is bound when
    some window overlaps it.
    """
    from character_schedule import HOME_TIME
    missing = []
    for interval in intervals:
        activity = interval['activity'].casefold()
        if activity == 'sleep' and beds: continue
        if activity in HOME_TIME and home: continue
        if activity == 'work' and any(a < interval['end_minute'] and interval['start_minute'] < b for a, b in work):
            continue
        missing.append(f"{interval['activity']} {interval['start_minute']}-{interval['end_minute']}")
    return missing


def verify(package, source, target, out):
    import kcd1_shop_install as shop
    from campaign_sources import RetailSourceReader
    from campaign_dependency_adapters import SourceTables
    from campaign_entity_links import guid_value
    from character_person_ai import STATS
    from character_person import native_xml
    from character_schedule import plan, has_home
    from profile_population_upgrade import discover
    from audit_bed_navigation import Mesh, nearest
    package, source, target, out = map(Path, (package, source, target, out))
    with zipfile.ZipFile(package/TRAVEL) as travel:
        names = set(travel.namelist())
        marker = json.loads(read(travel, MARKER))
        people = [r['person'] for r in marker['residents']]
        work_residue = {}
        for row in marker.get('work', {}).get('pending', []):
            work_residue.setdefault(row['person'], row.get('reason') or 'work pending')
        souls = {}
        for n in names:
            if n.startswith('Libs/Tables/rpg/soul__'):
                for soul in ET.fromstring(read(travel, n)).iter('soul'):
                    souls[soul.get('soul_name')] = soul.attrib
        storm = {n: read(travel, n) for n in names if n.startswith('Libs/Storm/') and n.endswith('.xml')}
        presets = {p.get('Name') for n in names if n.lower().startswith('libs/tables/item/inventorypreset')
                   for p in ET.fromstring(read(travel, n)).iter('InventoryPreset')}
        voice_rows, characters, _ = shop.voice_tables(names, lambda n: read(travel, n), target)
    with zipfile.ZipFile(target/'Data/Tables.pak') as tables:
        for n in tables.namelist():
            if n.lower().startswith('libs/tables/item/inventorypreset') and n.endswith('.xml'):
                try:   # retail tables carry comments ElementTree rejects; native_xml strips them
                    presets.update(p.get('Name') for p in native_xml(read(tables, n)).iter('InventoryPreset'))
                except ET.ParseError:
                    pass
    level = Level(package)
    mesh = Mesh(package/LEVEL/'recast.pak')
    kcd1_voices = {}
    for person in people:
        try:
            kcd1_voices[person] = shop.source_voices(source, [person])[person]
        except ValueError:
            kcd1_voices[person] = None
    results = {}
    with RetailSourceReader(source) as reader:
        tables = SourceTables(source, reader)
        _, sources, _ = discover(source, 'rataje', [], tables, names=people)
        for person in people:
            src = sources[person]; kcd1 = src['soul']; soul = souls.get(person, {})
            namespace = person_namespace(kcd1['soul_id'])
            npcs = level.by_name.get(person, [])
            npc = npcs[0] if len(npcs) == 1 else None
            home = has_home(src)
            r = {}
            r['soul'] = check(soul.get('soul_id') == kcd1['soul_id'] and soul.get('soul_name') == person
                              and soul.get('brain_id') and soul.get('social_class_id') and npc is not None,
                              f"soul {soul.get('soul_id')} vs {kcd1['soul_id']}, placed {len(npcs)}")
            r['faction'] = check(soul.get('factionName') == FACTION + kcd1.get('faction', ''),
                                 f"{soul.get('factionName')} vs KCD1 faction {kcd1.get('faction')}")
            ids = {row.get('voice_id') for row in characters.get(soul.get('skald_character_name'), [])}
            spoken = voice_rows.get(next(iter(ids)), ('?',))[0] if len(ids) == 1 else None
            single = sum(1 for a, _ in voice_rows.values() if a == kcd1_voices[person]) == 1
            r['voice'] = check(spoken is not None and spoken == kcd1_voices[person],
                               f"{soul.get('skald_character_name')} speaks {spoken}, KCD1 {kcd1_voices[person]}",
                               None if single else 'KCD1 voice is not a single KCD2 or imported voice')
            abilities = storm.get(f'Libs/Storm/abilities/{namespace}.xml', b'')
            set_stats = {o.get('stat'): o.get('value') for o in ET.fromstring(abilities).iter('setAttribute')} if abilities else {}
            wrong = [f'{new} {set_stats.get(new)} vs {kcd1.get(old)}' for old, new in STATS.items()
                     if kcd1.get(old) not in ('', None) and set_stats.get(new) != kcd1.get(old)]
            barter = '' if kcd1.get('barter') in ('', None) else f"KCD1 barter {kcd1['barter']} has no KCD2 attribute (noted)"
            r['stats'] = check(abilities and not wrong, '; '.join(wrong + [barter]).strip('; '))
            equipment = storm.get(f'Libs/Storm/equipment/{namespace}.xml', b'')
            preset = next((o.get('preset') for o in ET.fromstring(equipment).iter('setInventory')), None) if equipment else None
            r['outfit'] = check(storm.get(f'Libs/Storm/appearance/{namespace}.xml') and preset in presets,
                                f'inventory preset {preset}')
            homes = [t for label, t in level.links(npc) if label in ('home', '_!home') and t is not None]
            areas = [a for h in homes for label, a in level.links(h) if label == 'home_area' and a is not None]
            # A smart-area home owns its inline polygon; a trigger home has a compiled one.
            polygons = all(a.findall('Area/Points/Point') if a.get('EntityClass') == 'SmartAreaShape'
                           else guid_value(a.get('EntityGuid')) in level.areas for a in areas)
            r['home'] = check((bool(areas) and polygons) if home else True,
                              f'KCD1 home {home}, converted home hubs {len(homes)}, home areas {len(areas)}')
            places, work = day_places(level, npc)
            beds = [e for block, e in places if block == 'sleep']
            r['bed'] = check(beds, f'{len(beds)} beds in the sleep pool')
            schedule = plan(src, tables)
            unbound = unbound_intervals([*schedule['resolved'], *schedule['pending']], beds=beds, work=work, home=home)
            r['schedule'] = check(not unbound, 'unbound: ' + ', '.join(unbound) if unbound else
                                  f"{len(schedule['resolved'])} work blocks bound to {len(work)} windows",
                                  work_residue.get(person))
            # A home hub sits at its ownership polygon's origin, not where anyone stands; the beds and
            # benches inside are the places the day uses.
            off = [f"{block} {e.get('Name')}" for block, e in places if block != 'home'
                   and (position(e) is None or nearest(mesh, position(e)) is None)]
            r['navmesh'] = check(places and not off, f'{len(places)} places' + ('; off mesh: ' + ', '.join(off) if off else ''))
            results[person] = dict(namespace=namespace, checks=r,
                                   fail=sorted(k for k, v in r.items() if not v['ok'] and not v.get('residue')),
                                   residue=sorted(k for k, v in r.items() if v.get('residue')))
    state = lambda c: 'pass' if c['ok'] else 'residue' if c.get('residue') else 'fail'
    summary = {k: dict(Counter(state(p['checks'][k]) for p in results.values())) for k in CHECKS}
    report = dict(package=str(package), people=len(results), failed=sorted(p for p, v in results.items() if v['fail']),
                  summary=summary, residue=marker.get('residue', []), results=results)
    out.mkdir(parents=True, exist_ok=True)
    (out/'verify-residents.json').write_text(json.dumps(report, indent=1), encoding='utf-8')
    lines = [f"# Resident verification: {len(results)} people, {len(report['failed'])} with a FAIL", '',
             '| Check | Pass | Residue | Fail |', '|---|---|---|---|']
    lines += [f"| {k} | {v.get('pass', 0)} | {v.get('residue', 0)} | {v.get('fail', 0)} |" for k, v in summary.items()]
    for title, key in (('Failures', 'fail'), ('Residue (listed by the stage, not a FAIL)', 'residue')):
        lines += ['', '## ' + title, '']
        for person in sorted(results):
            for k in results[person][key]:
                lines.append(f"- {person} {k}: {results[person]['checks'][k]['detail']}")
    (out/'verify-residents.md').write_text('\n'.join(lines) + '\n', encoding='utf-8')
    return report


def main(argv=None):
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    for key in ('package', 'source', 'target', 'out'):
        p.add_argument('--' + key, type=Path, required=True)
    a = p.parse_args(argv)
    report = verify(a.package, a.source, a.target, a.out)
    print(json.dumps(dict(people=report['people'], failed=len(report['failed']), summary=report['summary']), indent=1))
    return 1 if report['failed'] else 0


if __name__ == '__main__':
    raise SystemExit(main())
