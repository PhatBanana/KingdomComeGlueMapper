"""Supply native seat/lean animation helpers and validate imported locations."""
import copy
import xml.etree.ElementTree as ET

from campaign_entity_links import guid_value
from upgrade_map import read

HELPERS = 'smartobjecthelpersetanimations.xml'
ANIMATIONS = 'tables/ai/smartobjectanimations.xml'


def collection_hash(collection):
    """Resolve the local animation collection, independently of world baking."""
    variants = collection.findall('SmartObjectHelperSetAnimationCollection')
    if len(variants) != 1:
        raise ValueError('Ambiguous native animation collection: ' + str(collection.get('HelperSetName')))
    value = variants[0].get('HashValue', '')
    if not value.isdecimal() or not 0 < int(value) < 2**64:
        raise ValueError('Invalid native animation collection hash: ' + str(collection.get('HelperSetName')))
    return value


def converted_door(entity):
    return (entity.get('EntityClass') == 'AnimDoor'
            and entity.get('Name', '').startswith(('gm_door_', 'gm_rental_')))


def install(files, native, prefixes=('gm_chair_', 'gm_bench_'), extra_collections=()):
    result = dict(files)
    helpers = ET.fromstring(files.get(HELPERS, b'<SmartObjectAnimationCollections/>'))
    native_helpers = ET.fromstring(read(native, HELPERS))
    if helpers.tag != 'SmartObjectAnimationCollections' or native_helpers.tag != helpers.tag:
        raise ValueError('Unexpected animation helper format')
    seats = [e for e in ET.fromstring(files['objects_mission0.xml']).iter('Entity')
             if (e.get('EntityClass') == 'StanceSmartObject' and e.get('Name', '').startswith(prefixes))
             or (e.get('EntityClass') == 'DetailMovementSmartObject'
                 and e.get('Name', '').startswith(('gm_', 'gmtravel_')))
             or (e.get('EntityClass') == 'SmartObjectHolder' and e.get('Name', '').startswith('gm_wash_'))
             or (e.get('EntityClass') == 'SmartObjectHolder' and e.get('Name', '').startswith('gm_schedule_')
                 and e.find('Properties') is not None and e.find('Properties').get('soclass_SmartObjectHelpers'))
             or (e.get('EntityClass') == 'ItemSlot' and e.get('Name', '').startswith('gm_job_item_')
                 and e.find('Properties') is not None and e.find('Properties').get('soclass_SmartObjectHelpers'))
             or converted_door(e)]
    # Native guard points are DetailMovementSmartObjects without helper sets;
    # their unstance supplies the movement itself. Do not invent a helper row.
    seats = [e for e in seats if e.find('Properties') is not None
             and e.find('Properties').get('soclass_SmartObjectHelpers')]
    families = {e.find('Properties').get('soclass_SmartObjectHelpers') for e in seats}
    available = {e.get('HelperSetName'): e for e in native_helpers}
    available.update({e.get('HelperSetName'): e for e in helpers if e.get('HelperSetName','').startswith('gm_Door')})
    available.update({e.get('HelperSetName'): e for e in extra_collections})
    for family in sorted(families):
        if family not in available: raise ValueError('Missing native smart-object animations: ' + str(family))
        for old in list(helpers):
            if old.get('HelperSetName') == family: helpers.remove(old)
        helpers.append(copy.deepcopy(available[family]))
    table = ET.fromstring(files.get(ANIMATIONS, b'<database name="barbora"><SmartObjectAnimationss version="1"/></database>'))
    rows = table.find('SmartObjectAnimationss')
    if rows is None: raise ValueError('Missing SmartObjectAnimationss table')
    ids = {str(guid_value(e.get('EntityGuid'))) for e in seats}
    for old in list(rows):
        if old.get('EntityGuid') in ids: rows.remove(old)
    for seat in seats:
        # Trosky baked navigation/physics results and projected targets cannot
        # be reused at KCD1 coordinates. Request native runtime validation.
        animation_hash = '0'
        if ((seat.get('EntityClass') == 'StanceSmartObject'
             and seat.find('Properties').get('soclass_SmartObjectHelpers', '').startswith(('Sit_1Place_', 'Bed_1Place_')))
                or converted_door(seat)
                or (seat.get('Name', '').startswith('gm_wash_') and any(
                    l.get('Name', '').startswith("schedulerReservedItem['refillWatertube',")
                    for l in seat.findall('EntityLinks/Link')))
                or seat.get('Name','').startswith(('gm_schedule_','gm_job_item_'))):
            family=seat.find('Properties').get('soclass_SmartObjectHelpers')
            # This hash selects the local animation/start-transform collection;
            # zero leaves native unstances without a move target when runtime
            # preparation is disabled. The entity world transform below is new.
            # Sitting, lying transitions and doors need this reference; it is not
            # a foreign world bake. Keep validation at the imported location.
            animation_hash=collection_hash(available[family])
        row = ET.SubElement(rows, 'SmartObjectAnimations', EntityGuid=str(guid_value(seat.get('EntityGuid'))),
                            Hash=animation_hash, AllowRuntimeAnimValidationFallback='true')
        ET.SubElement(row, 'SmartObjectTransform', Position=seat.get('Pos'), Rotation=seat.get('Rotate', '1,0,0,0'))
    result[HELPERS] = ET.tostring(helpers, encoding='utf-8', xml_declaration=True)
    result[ANIMATIONS] = ET.tostring(table, encoding='utf-8', xml_declaration=True)
    return result, {'families': sorted(families), 'runtime_validation_seats': len(seats)}
