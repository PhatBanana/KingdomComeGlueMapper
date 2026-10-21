"""Discover static-profile people and shops without settlement/name lists."""
import xml.etree.ElementTree as E
import zipfile

from campaign_profile_actors import collect
from build_profile_systems import source_world
from character_person_ai import capture_person_ai, index_person_links
from upgrade_map import read


def shops_for_people(roster, keepers, shops):
    people = {p['soul_id']: p for p in roster}
    if len(people) != len(roster):
        raise ValueError('Profile contains competing placements of a shared soul')
    shop_rows = {}
    for shop in shops:
        identity = shop['shop_id']
        if identity in shop_rows: raise ValueError('Duplicate source shop identity')
        shop_rows[identity] = shop
    result, seen = [], set()
    for keeper in keepers:
        person = people.get(keeper['keeper_id'])
        if person is None: continue
        identity = keeper['shop_id']
        if identity not in shop_rows: raise ValueError('Source keeper has a missing shop: ' + identity)
        if identity in seen:
            raise ValueError('Shared shop staffing requires an explicit multi-keeper lifecycle: ' + identity)
        seen.add(identity)
        result.append(dict(person=person['name'], soul_id=person['soul_id'], shop=shop_rows[identity],
                           namespace='gm_source_shop_' + identity))
    return sorted(result, key=lambda r: int(r['shop']['shop_id']))


def discover(source, source_level, profiles, tables):
    with zipfile.ZipFile(source/'Data/Levels'/source_level/'level.pak') as archive:
        documents, entities = source_world(archive)
        souls = E.fromstring(read(archive, 'whdata_0'))
        roster = collect(E.fromstring(read(archive, 'whdata_1')), souls, documents, profiles)
    by_guid = {e.get('EntityGuid'): e for e in entities if e.get('EntityGuid')}
    instances = {s.findtext('Guid'): s for s in souls.findall('SoulList/Souls/Soul')}
    links = index_person_links(entities)
    people = {}
    for record in roster:
        soul = tables.row('rpg/soul', 'soul_id', record['soul_id'])
        person = dict(name=record['name'], soul=soul, actor=by_guid[record['entity_guid']],
                      instance=instances[record['instance_id']], source_level=source_level)
        person['ai'] = capture_person_ai(tables, soul, person['actor'], person['instance'], entities, links)
        people[record['name']] = person
    shops = shops_for_people(roster, tables.get('shop/shopkeeper')['rows'], tables.get('shop/shop')['rows'])
    return roster, people, shops


def validate_people(roster, mission, souls):
    """Validate all selected identities, not just this build's newly added count."""
    entities = {}
    for entity in mission:
        guid = entity.get('EntityGuid')
        # Static geometry has no gameplay GUID and may appear many times.
        if not guid: continue
        if guid in entities: raise ValueError('Duplicate destination entity GUID')
        entities[guid] = entity
    for record in roster:
        matches = [s for s in souls.findall('SoulList/Souls/Soul')
                   if s.findtext('SharedSoulGuid') == record['soul_id']]
        if len(matches) != 1: raise ValueError('Missing or duplicate population soul: ' + record['name'])
        actor = entities.get(matches[0].findtext('EntityGuid'))
        if actor is None or actor.get('Name') != record['name'] or actor.get('EntityClass') not in ('NPC', 'NPC_Female'):
            raise ValueError('Population soul has no matching person: ' + record['name'])
    return len(roster)


def validate_services(package, target, shops, level, *, require_storage=()):
    """A table row alone does not prove a previously imported shop is usable."""
    from container_items import item_patches
    from world_item_definitions import native_items
    from character_person_activity import validate_scheduler_targets
    items = native_items(target,item_patches(package))
    resources={}
    for path in sorted((package/'Data').glob('*.pak')):
        with zipfile.ZipFile(path) as archive:
            for name in archive.namelist():
                if name.lower().startswith(('libs/tables/shop/', 'libs/tables/item/inventorypreset')) and name.lower().endswith('.xml'):
                    resources[name.lower()]=read(archive,name)
    shop_rows=[row for blob in resources.values() for row in E.fromstring(blob).iter('ShopData')]
    presets={row.get('Name'):row for blob in resources.values() for row in E.fromstring(blob).iter('InventoryPreset')}
    with zipfile.ZipFile(package/'Data/Levels'/level/'level.pak') as archive:
        mission=E.fromstring(read(archive,'objects_mission0.xml'))
        scheduler=read(archive,'tables/ai/scheduler.xml')
        validate_scheduler_targets(E.fromstring(scheduler))
    modid=E.parse(package/'mod.manifest').findtext('info/modid')
    with zipfile.ZipFile(package/'Data/gluemappertravel.pak') as archive:
        alias='Mods/'+modid+'/Data/Levels/'+level+'/tables/ai/scheduler.xml'
        if read(archive,alias)!=scheduler:raise ValueError('Population mounted scheduler differs from level')
    by_guid={e.get('EntityGuid'):e for e in mission if e.get('EntityGuid')}
    checked=[]
    for selected in shops:
        identity=str(20000+int(selected['shop']['shop_id']))
        rows=[r for r in shop_rows if r.get('shop_id')==identity]
        entities=[e for e in mission if e.get('EntityClass')=='Shop' and
                  e.find('Properties').get('iShopId')==identity]
        people=[e for e in mission if e.get('Name')==selected['person']]
        if len(rows)!=1 or len(entities)!=1 or len(people)!=1:
            raise ValueError('Incomplete or duplicate population shop: '+identity)
        row,shop,npc=rows[0],entities[0],people[0]
        if shop.find('Properties').get('sShopName')!=row.get('shop_name'):
            raise ValueError('Population shop name and table differ: '+identity)
        if not any(l.get('Name')=='shopKeeper' and l.get('TargetGuid')==shop.get('EntityGuid')
                   for l in npc.findall('EntityLinks/Link')):
            raise ValueError('Population shop has no assigned keeper: '+identity)
        stashes=[by_guid.get(l.get('TargetGuid')) for l in shop.findall('EntityLinks/Link') if l.get('Name')=='shopStash']
        if (identity in require_storage and not stashes) or any(s is None or s.get('EntityClass')!='Stash' for s in stashes):
            raise ValueError('Population shop storage is missing: '+identity)
        preset=presets.get(row.get('inventory_preset'))
        if preset is None or not len(preset):raise ValueError('Population shop stock is missing: '+identity)
        for item in preset.findall('PresetItem'):
            definition=items.get(item.get('ItemClassId','').lower())
            if definition is None or definition.get('Name')!=item.get('Name') or int(item.get('Amount','0'))<=0:
                raise ValueError('Population shop stock item is unresolved: '+identity)
        checked.append(dict(person=selected['person'],shop_id=identity,stock_rows=len(preset),storage=len(stashes)))
    return checked


def retain_work(previous, current, people):
    """A repeat upgrade must not turn unresolved legacy jobs into success."""
    selected=set(people)
    updated={r['person'] for key in ('converted','pending') for r in current[key] if not r.get('extension_only')}
    extensions={(r['person'], r['job']) for r in current['converted'] if r.get('extension_only')}
    result={key:[r for r in previous.get(key,[]) if r['person'] in selected and r['person'] not in updated
                 and (key != 'converted' or (r['person'],r.get('job')) not in extensions)]+current[key]
            for key in ('converted','pending')}
    result['complete']=not result['pending'] and not any(r.get('pending') for r in result['converted'])
    return result
