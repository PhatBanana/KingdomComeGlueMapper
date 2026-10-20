"""Convert legacy shop work locations to the retail market-seller activity.

The source area's entry point is not necessarily its selling point. Resolve
the authored merchantPoint link and use the native interruptible activity at
that transform. Selection is by work contract, never actor or quest identity.
"""
import copy
import xml.etree.ElementTree as E
import zipfile
from pathlib import Path

from character_person import resolve_link_targets, unique, world_entity
from upgrade_map import read

SOURCE = ('final/sa_shop2.xml', 'merchant')
NATIVE_TABLE = 'Libs/Tables/ai/smartEntity/SmartEntity__so_seller.xml'
ACTIVITY = 'seller_market'


def supports(entry):
    behavior = entry['behavior']
    return (behavior['tree_file'].replace('\\', '/').lower(), behavior['tree_name']) == SOURCE


def resolve(entry, archive):
    area = E.Element('Entity', entry['area'])
    links = E.SubElement(area, 'EntityLinks')
    for link in entry['target_links']:
        if 'merchantPoint' in link.get('Name', '').split(','):
            E.SubElement(links, 'Link', link)
    link = unique(links, 'authored merchant selling point')
    entities = resolve_link_targets(archive, area,
        list(E.fromstring(read(archive, 'objects_mission0.xml'))), {})
    point = unique((e for e in entities if e.get('EntityId') == link.get('TargetId')),
                   'merchant selling point entity')
    if point.get('EntityClass') != 'TagPoint':
        raise ValueError('Merchant selling point must have a converted point contract')
    return dict(entry, arrival=dict(world_entity(archive, point, entities).attrib), market_work=True)


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
    return job, dict(person=person, job='native_market_seller', native_behavior=ACTIVITY,
                    source_selling_point=entry['arrival'], pending=[], runtime_verified=False,
                    policy='Native market selling replaces legacy customer/idle dispatch')
