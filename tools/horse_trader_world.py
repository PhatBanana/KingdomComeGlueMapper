"""Destination-local stable entities, spatial sale eligibility and shop binding."""
import xml.etree.ElementTree as ET

from campaign_entity_links import append_links, guid_value, native_guid
from campaign_trigger_areas import TriggerArea, read_areas, write_areas
from character_person import register_person
from character_person_world import register_person_world
from character_person_shop import register_shop_service, register_shop_activity, route_idle_through_work
from region_travel import guid
from upgrade_map import xml
from merchant_stash import source_stash, apply_stash_placement

STASH_PREFIX = 'objects/gluemapper/neuhof_stash/'


def register(files, resources, person, horses, source, target, entry_path):
    files, resources = dict(files), dict(resources)
    mission = ET.fromstring(files['objects_mission0.xml'])
    wh = ET.fromstring(files['whdata_0'])
    next_id = max(int(e.get('EntityId', '0')) for e in mission) + 1
    links = []

    def add(name, cls, pos, identity=None, rotation=None):
        nonlocal next_id
        identity = identity or guid('horse-sales/'+name)
        if any(e.get('Name') == name or e.get('EntityGuid') == identity for e in mission):
            raise ValueError('Horse trader already registered: '+name)
        e = ET.SubElement(mission, 'Entity', Name=name, EntityClass=cls, Pos=pos,
                          EntityGuid=identity, EntityId=str(next_id), CastShadowMinSpec='1')
        if rotation: e.set('Rotate', rotation)
        next_id += 1
        return e

    def link(a, b, label):
        container = a.find('EntityLinks')
        if container is None: container = ET.SubElement(a, 'EntityLinks')
        ET.SubElement(container, 'Link', Name=label, TargetId=b.get('EntityId'), TargetGuid=b.get('EntityGuid'))
        links.append((a.get('EntityGuid'), b.get('EntityGuid'), label))

    seller = register_person(add, wh, person)
    horse_people = []
    for h in horses:
        actor = h['actor']
        horse = add(h['name'], 'Horse', actor.get('Pos'), native_guid(int(actor.get('EntityGuid'), 16)), actor.get('Rotate'))
        ET.SubElement(horse, 'Properties', bWH_RequiresHome='0')
        soul = ET.SubElement(wh.find('SoulList/Souls'), 'Soul', version='8')
        for key, value in dict(Name=h['name'], SharedSoulGuid=h['soul']['soul_id'],
                               Guid=h['instance'].findtext('Guid'), EntityGuid=horse.get('EntityGuid')).items():
            ET.SubElement(soul, key).text = value
        horse_people.append(dict(name=h['name'], ai=dict(links=[], schedule=[])))
    # Separate shop identity; never steal a Trosky merchant's existing shop.
    pos = person['shop_entity'].get('Pos')
    shop = add('gm_neuhof_horse_shop', 'Shop', pos)
    work = add('gm_neuhof_stable_work', 'SchedulerHub', seller.get('Pos'))
    ET.SubElement(shop, 'Properties', sShopName='gm_neuhof_horse_shop', iShopId='20130', bOwnerIsSpawned='1')
    stash = add('gm_neuhof_horse_stash', 'Stash', pos)
    props = ET.SubElement(stash, 'Properties')
    ET.SubElement(props, 'Database', sGeneratedInventory='inventory_shop_horseTraderSemin')
    ET.SubElement(props, 'Lock', bLocked='1', bLockDifficultyOverride='1', fLockDifficulty='1')
    apply_stash_placement(stash, source_stash(source, person['shop_entity']), STASH_PREFIX)
    link(seller, shop, 'owner'); link(seller, shop, 'shopKeeper'); link(shop, stash, 'shopStash')
    points = [tuple(map(float, h['actor'].get('Pos').split(','))) for h in horses]
    low = [min(p[i] for p in points) for i in range(3)]
    high = [max(p[i] for p in points) for i in range(3)]
    area = add('gm_neuhof_horse_sale_area', 'TriggerArea', ','.join(map(str, low)))
    ET.SubElement(area, 'Properties', bSaved_by_game='0')
    shapes = read_areas(files['triggerareas.fubar'])
    z = low[2]-5
    polygon = ((low[0]-20, low[1]-20, z), (high[0]+20, low[1]-20, z),
               (high[0]+20, high[1]+20, z), (low[0]-20, high[1]+20, z))
    shapes['areas'].append(TriggerArea(guid_value(area.get('EntityGuid')), high[2]-z+10, polygon))
    holder = next(e for e in mission if e.get('EntityClass') == 'LevelHolder')
    for entity, alias in ((shop, 'neuhof_shop'), (stash, 'horse_shop_stash'), (area, 'horse_shop_area')):
        link(holder, entity, "asset['"+alias+"']")
    resources[entry_path] = register_shop_service(resources[entry_path], person['soul']['soul_id'], 'neuhof_shop')
    files.update({'objects_mission0.xml': xml(mission), 'whdata_0': xml(wh),
                  'triggerareas.fubar': write_areas(shapes['areas'], shapes['export_version']),
                  'waitinglinks.xml': append_links(files.get('waitinglinks.xml'), links)})
    files, schedules = register_person_world(files, [person, *horse_people], source, target)
    # Staff the stash-backed shop through the same native scheduler initializer
    # used by ordinary merchants. Owner/context links alone do not open it.
    scheduler = ET.fromstring(files['tables/ai/scheduler.xml'])
    route_idle_through_work(scheduler, seller, work)
    files['tables/ai/scheduler.xml'] = register_shop_activity(xml(scheduler), target, seller, work, shop, role='seller')
    return files, resources, schedules
