"""Supply native seat/lean animation helpers and validate imported locations."""
import copy
import xml.etree.ElementTree as ET

from campaign_entity_links import guid_value
from upgrade_map import read

HELPERS = 'smartobjecthelpersetanimations.xml'
ANIMATIONS = 'tables/ai/smartobjectanimations.xml'


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
             or (e.get('EntityClass') == 'AnimDoor' and e.get('Name', '').startswith('gm_door_'))]
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
        row = ET.SubElement(rows, 'SmartObjectAnimations', EntityGuid=str(guid_value(seat.get('EntityGuid'))),
                            Hash='0', AllowRuntimeAnimValidationFallback='true')
        ET.SubElement(row, 'SmartObjectTransform', Position=seat.get('Pos'), Rotation=seat.get('Rotate', '1,0,0,0'))
    result[HELPERS] = ET.tostring(helpers, encoding='utf-8', xml_declaration=True)
    result[ANIMATIONS] = ET.tostring(table, encoding='utf-8', xml_declaration=True)
    return result, {'families': sorted(families), 'runtime_validation_seats': len(seats)}
