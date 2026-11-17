"""Convert legacy shop work locations to the retail market-seller activity.

The source area's entry point is not necessarily its selling point. Resolve
the authored merchantPoint link and use the native interruptible activity at
that transform. Selection is by work contract, never actor or quest identity.

Several merchantPoints: the source merchant idles among them and serves each
customer from the one nearest that customer. The native seller holds one
point, so keep the point the source daycycle delivers the merchant to (the
area's `inside` link) and report the others. A Shop entity linked as a
merchantPoint is the shop marker the source finds by class, not a pose.

The bathhouse abbess (sa_bathhouse Abbess) walks to her one authored
abbessWorkSpot, aligns and waits there for orders: the same contract.
"""
import copy
import xml.etree.ElementTree as E
import zipfile
from pathlib import Path

from character_person import resolve_link_targets, unique, world_entity
from upgrade_map import read

SOURCE = ('final/sa_shop2.xml', 'merchant')
BATHHOUSE = ('final/sa_bathhouse.xml', 'Abbess')
# Source behaviour -> the area link tag naming its selling pose.
POINTS = {SOURCE: 'merchantPoint', BATHHOUSE: 'abbessWorkSpot'}
NATIVE_TABLE = 'Libs/Tables/ai/smartEntity/SmartEntity__so_seller.xml'
ACTIVITY = 'seller_market'


def source_behavior(entry):
    behavior = entry.get('behavior')
    if behavior is None: return SOURCE
    return (behavior['tree_file'].replace('\\', '/').lower(), behavior['tree_name'])


def supports(entry):
    return source_behavior(entry) in POINTS


def tagged(entry, tag):
    return [link for link in entry['target_links'] if tag in link.get('Name', '').split(',')]


def resolve(entry, archive):
    # Callers resolve selling poses for any work routed here; only the abbess differs.
    kind = BATHHOUSE if source_behavior(entry) == BATHHOUSE else SOURCE
    area = E.Element('Entity', entry['area'])
    links = E.SubElement(area, 'EntityLinks')
    for link in tagged(entry, POINTS[kind]):
        E.SubElement(links, 'Link', link)
    if not len(links) or kind == BATHHOUSE:
        unique(links, 'authored merchant selling point')
    entities = resolve_link_targets(archive, area,
        list(E.fromstring(read(archive, 'objects_mission0.xml'))), {})
    points = [unique((e for e in entities if e.get('EntityId') == link.get('TargetId')),
                     'merchant selling point entity') for link in links]
    alternates = []
    if len(points) > 1:
        poses = [p for p in points if p.get('EntityClass') == 'TagPoint']
        if len(poses) > 1:
            arrival = {link.get('TargetId') for link in tagged(entry, 'inside')}
            chosen = [p for p in poses if p.get('EntityId') in arrival]
            if len(chosen) != 1:
                raise ValueError('Expected one authored merchant selling point at the area arrival, found '
                                 + str(len(chosen)))
            poses = chosen
        if not poses:
            raise ValueError('Merchant selling point must have a converted point contract')
        point = poses[0]
        alternates = [dict(EntityId=p.get('EntityId'), EntityClass=p.get('EntityClass'), Name=p.get('Name'),
                           Pos=world_entity(archive, p, entities).get('Pos')) for p in points if p is not point]
    else:
        point = points[0]
    if point.get('EntityClass') != 'TagPoint':
        raise ValueError('Merchant selling point must have a converted point contract')
    result = dict(entry, arrival=dict(world_entity(archive, point, entities).attrib), market_work=True)
    if alternates: result['market_alternates'] = alternates
    return result


def contract(target):
    with zipfile.ZipFile(Path(target)/'Data/Tables.pak') as archive:
        template = E.fromstring(read(archive, NATIVE_TABLE)).find('.//SmartEntityTemplate')
    behavior = template.find("BehaviorTemplates/SmartBehaviorTemplate[@Name='" + ACTIVITY + "']")
    if behavior is None or behavior.get('InitialState') != 'Enabled':
        raise ValueError('Missing enabled native market seller activity')
    tree = behavior.find('TreeLocation')
    with zipfile.ZipFile(Path(target)/'Data/Scripts.pak') as archive:
        root = E.fromstring(read(archive, 'AI/' + tree.get('FileName')))
    program = root.find("BehaviorTree[@name='" + tree.get('TreeName') + "']/Root")
    if program is None or program.find('.//ExactMove') is None or program.find(
            ".//EntityContextElement[@context='shop_sellerReadyToSell']") is None:
        raise ValueError('Native seller no longer owns movement and service readiness')
    return copy.deepcopy(template)


def bind(mission, scheduler, person, entry, target):
    from campaign_entity_links import guid_value
    template = contract(target)
    job = unique((e for e in mission if e.get('Name') ==
                  'gm_schedule_' + person + '_' + entry['arrival']['EntityId']), 'merchant job')
    job.find('Properties').set('guidSmartObjectType', template.get('DatabaseId'))
    for link in scheduler.findall('.//S_ActivityLink'):
        if link.get('TargetGuid') == str(guid_value(job.get('EntityGuid'))):
            link.find('Parameters').set('BehaviorName', ACTIVITY)
    report = dict(person=person, job='native_market_seller', native_behavior=ACTIVITY,
                  source_selling_point=entry['arrival'], pending=[], runtime_verified=False,
                  policy='Native market selling replaces legacy customer/idle dispatch')
    if entry.get('market_alternates'):
        report['source_alternate_points'] = entry['market_alternates']
        report['policy'] += '; one native point replaces serving from the merchantPoint nearest each customer'
    if source_behavior(entry) == BATHHOUSE:
        report['source_services_not_converted'] = ['bathhouse service orders (bath, healing, love) relayed to the area']
    return job, report
