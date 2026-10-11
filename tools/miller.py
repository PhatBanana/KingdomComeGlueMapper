"""Resolve Peshek's authored home/daycycle and explicitly enabled test shop."""
import copy
from pathlib import Path
import xml.etree.ElementTree as ET
import zipfile

from campaign_dependency_adapters import SourceTables
from campaign_sources import RetailSourceReader
from character_person import resolve_person, unique
from region_travel_services import shop_resources
from upgrade_map import read

NAME = 'rat_pesek'
NAMESPACE = 'gm_rattay_miller'
ROLE = 'GM_RATTAY_MILLER'
LOCKPICK = '8d76f58e-a521-4205-a7e8-9ac077eee5f0'
MONEY = '5ef63059-322e-4e1b-abe8-926e100c770e'


def schedule_windows(schedule):
    """Convert a circular source daycycle to non-wrapping native minute ranges."""
    entries = sorted(schedule, key=lambda e: e['start_minute'])
    starts = [e['start_minute'] for e in entries]
    if len(entries) < 2 or len(set(starts)) != len(starts) or any(not 0 <= v < 1440 for v in starts):
        raise ValueError('Invalid source daycycle boundaries')
    if {e['activity'] for e in entries} != {'work', 'sleep'}:
        raise ValueError('Miller daycycle needs another activity adapter')
    result = []
    for i, entry in enumerate(entries):
        start, end = entry['start_minute'], entries[(i+1) % len(entries)]['start_minute']
        for a, b in ([(start, end)] if end > start else [(start, 1440), (0, end)]):
            if a != b: result.append(dict(activity=entry['activity'], start=a, end=b))
    return result


def resolve(source):
    person = resolve_person(source, NAME)
    with RetailSourceReader(source) as reader:
        tables = SourceTables(source, reader)
        keeper = tables.row('shop/shopkeeper', 'keeper_id', person['soul']['soul_id'])
        shop = tables.row('shop/shop', 'shop_id', keeper['shop_id'])
        stock = [r for r in tables.get('shop/shop_type2item')['rows'] if r['shop_type_id'] == shop['shop_type_id']]
    with zipfile.ZipFile(Path(source)/'Data/Levels/rataje/level.pak') as archive:
        entities = {e.get('EntityId'): e for e in ET.fromstring(read(archive, 'objects_mission0.xml')).iter('Entity')}
    links = person['actor'].findall('EntityLinks/Link')
    work = entities[unique((l for l in links if l.get('Name', '').startswith('Work[')), 'miller work').get('TargetId')]
    home = entities[unique((l for l in links if 'Home' in l.get('Name', '').split(',')), 'miller home').get('TargetId')]
    beds = [entities[l.get('TargetId')] for l in home.findall('EntityLinks/Link') if l.get('TargetId') in entities
            and entities[l.get('TargetId')].get('EntityClass') == 'Bed']
    # The downstairs bed is Henry's. Preserve that designation and use the
    # source household's non-player bed, rather than guessing a coordinate.
    bed = unique((b for b in beds if 'playersBed:true' not in b.find('Properties/Script').get('Misc', '')), 'non-player mill bed')
    placed_shop = unique((e for e in entities.values() if e.get('EntityClass') == 'Shop'
                          and e.find('Properties').get('iShopId') == shop['shop_id']), 'miller shop')
    selected = {r['item_id']: int(r['amount']) for r in stock if r['item_id'] in (LOCKPICK, MONEY)}
    if set(selected) != {LOCKPICK, MONEY} or min(selected.values()) <= 0:
        raise ValueError('Source miller lockpick/cash stock changed')
    person.update(shop=shop, stock=selected, area=work, shop_entity=placed_shop, bed=bed,
                  source_stock=stock, windows=schedule_windows(person['ai']['schedule']))
    return person


def resources(person, target):
    enabled = copy.deepcopy(person)
    # The standalone test world has no Good Thief unlock quest. Enable only
    # the requested native supplies. The three source skill books have no
    # shared native IDs and must not silently become unrelated KCD2 items.
    enabled['shop']['restock_day_mask'] = '127'
    files, report = shop_resources(enabled, target, NAMESPACE)
    report.update(source_shop=person['shop'], source_stock=person['source_stock'],
        stock_policy='Lockpicks and cash enabled immediately for the test world; source quantities, native prices',
        restock_policy='Native daily test-shop restock; source weekday mask 9 is not equivalent',
        pending_stock=[r for r in person['source_stock'] if r['item_id'] not in person['stock']])
    return files, report
