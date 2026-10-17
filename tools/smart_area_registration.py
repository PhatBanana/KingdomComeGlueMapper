"""Keep emitted SmartAreaShape entities in the native area manager lifecycle."""
import xml.etree.ElementTree as ET
from campaign_entity_links import guid_value
from upgrade_map import xml


def reconcile(metadata, mission, *, validate_only=False):
    root = ET.fromstring(metadata)
    entries = root.find('AI/SmartAreaManager/SmartAreas')
    if entries is None:
        raise ValueError('Missing native SmartAreaManager registration')
    registered = [int(e.findtext('Guid')) for e in entries]
    if len(registered) != len(set(registered)):
        raise ValueError('Duplicate native smart-area registration')
    expected = {guid_value(e.get('EntityGuid')) for e in ET.fromstring(mission).iter('Entity')
                if e.get('EntityClass') == 'SmartAreaShape'}
    missing = sorted(expected - set(registered))
    if validate_only and missing:
        raise ValueError('Unregistered SmartAreaShape entities: ' + ', '.join(map(str, missing)))
    for guid in missing:
        ET.SubElement(ET.SubElement(entries, 'SmartArea'), 'Guid').text = str(guid)
    return xml(root), missing
