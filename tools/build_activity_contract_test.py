"""Stage animation and shop-routing repairs into the current combined test mod."""
import argparse
import copy
import json
from pathlib import Path
import xml.etree.ElementTree as ET
import zipfile

from build_horse_trader_test import digest, rewrite
from campaign_entity_links import guid_value
from character_person_shop import route_idle_through_work
from seating_animations import install, HELPERS, ANIMATIONS
from upgrade_map import read, xml
from character_person_activity import source_lean_point
from lean_alignment import native_placement


def build(source, target, mod, output):
    if output.exists(): raise FileExistsError('Choose a fresh staging directory')
    level = mod/'Data/Levels/kcd1_travel/level.pak'
    travel = mod/'Data/gluemappertravel.pak'
    scheduler_path = 'tables/ai/scheduler.xml'
    with zipfile.ZipFile(level) as archive:
        files = {n: read(archive, n) for n in ('objects_mission0.xml', HELPERS, ANIMATIONS, scheduler_path)}
    mission = ET.fromstring(files['objects_mission0.xml'])
    # Reconstruct the source contract so repeated staging never accumulates offsets.
    with zipfile.ZipFile(source/'Data/Levels/rataje/level.pak') as archive:
        original = list(ET.fromstring(read(archive, 'objects_mission0.xml')).iter('Entity'))
    actor = next(e for e in original if e.get('Name') == 'rato_innkeeper1')
    work_id = next(l.get('TargetId') for l in actor.findall('EntityLinks/Link') if l.get('Name', '').startswith('Work['))
    area = next(e for e in original if e.get('EntityId') == work_id)
    point, family = source_lean_point(source, dict(actor=actor, source_level='rataje'), area)
    point = native_placement(point, source, target, family)
    lean = next(e for e in mission.iter('Entity') if e.get('Name') == 'gmtravel_rattay_lean')
    npc = next(e for e in mission.iter('Entity') if e.get('Name') == actor.get('Name'))
    for entity, placement in ((lean, point), (npc, actor)):
        entity.set('Pos', placement.get('Pos'))
        entity.set('Rotate', placement.get('Rotate', '1,0,0,0'))
    files['objects_mission0.xml'] = xml(mission)
    entities = {str(guid_value(e.get('EntityGuid'))): e for e in mission.iter('Entity') if e.get('EntityGuid')}
    work = next(e for e in entities.values() if e.get('Name') == 'gm_neuhof_stable_work')
    hub_id = str(guid_value(work.get('EntityGuid')))
    land = next(e for e in entities.values() if e.get('Name') == 'sa_land')
    scheduler = ET.fromstring(files[scheduler_path]); rows = scheduler.find('Schedulers')
    repaired = 0
    for row in list(rows):
        for link in row.findall('Links/S_ActivityLink'):
            params = link.find('Parameters')
            if link.get('TargetGuid') != hub_id or params is None or params.get('BehaviorName') != 'schedulerWait': continue
            old_hub = next(r for r in rows if r.get('EntityGuid') == hub_id)
            if old_hub.find('Links') is not None: raise ValueError('Unexpected existing work hub activities')
            effects = copy.deepcopy(old_hub.find('PostSearchData'))
            role = params.attrib.pop('ProvidedRole', None)
            link.set('TargetGuid', str(guid_value(land.get('EntityGuid'))))
            rows.remove(old_hub)
            route_idle_through_work(scheduler, entities[row.get('EntityGuid')], work)
            if role: params.set('ProvidedRole', role)
            new_hub = next(r for r in rows if r.get('EntityGuid') == hub_id)
            if effects is not None: new_hub.append(effects)
            repaired += 1
    files[scheduler_path] = xml(scheduler)
    with zipfile.ZipFile(target/'Data/Levels/trosecko/level.pak') as native:
        files, report = install(files, native, prefixes=('gm_chair_', 'gm_bench_', 'gm_rental_'))
    modid = ET.parse(mod/'mod.manifest').findtext('info/modid')
    resources = {f'Mods/{modid}/Data/Levels/kcd1_travel/{n}': files[n] for n in (scheduler_path, ANIMATIONS)}
    report.update(repaired_shop_routes=repaired, baseline={str(p.relative_to(mod)): digest(p) for p in (level, travel)})
    rewrite(level, output/'Data/Levels/kcd1_travel/level.pak', files)
    rewrite(travel, output/'Data/gluemappertravel.pak', resources)
    (output/'activity-report.json').write_text(json.dumps(report, indent=2)+'\n', encoding='utf-8')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('source', 'target', 'mod', 'output'): parser.add_argument('--'+name, type=Path, required=True)
    build(**vars(parser.parse_args()))
