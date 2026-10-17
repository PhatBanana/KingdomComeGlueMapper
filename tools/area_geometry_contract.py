"""Separate native trigger geometry from entity-owned smart-area geometry.

Trosky, Kuttenberg and Klaster export only TriggerArea records in FUBAR.
SmartAreaShape owns its inline Area and must not also enter that registry.
"""
import xml.etree.ElementTree as ET
from campaign_entity_links import guid_value
from campaign_trigger_areas import read_areas, write_areas


def normalize(blob, missions, *, validate_only=False):
    if isinstance(missions, bytes):
        missions = [missions]
    entities = {}
    for mission in missions:
        for entity in ET.fromstring(mission).iter('Entity'):
            if not entity.get('EntityGuid'):
                continue
            guid = guid_value(entity.get('EntityGuid'))
            if guid in entities:
                raise ValueError('Ambiguous area entity GUID: ' + str(guid))
            entities[guid] = entity
    parsed = read_areas(blob)
    kept, removed = [], []
    for area in parsed['areas']:
        entity = entities.get(area.guid)
        if entity is None:
            raise ValueError('Compiled area has no entity: ' + str(area.guid))
        kind = entity.get('EntityClass')
        if kind == 'TriggerArea':
            kept.append(area)
        elif kind == 'SmartAreaShape':
            shape = entity.find('Area')
            if shape is None or not shape.findall('Points/Point'):
                raise ValueError('Cannot remove compiled smart area without inline geometry: ' + entity.get('Name', ''))
            removed.append(dict(guid=area.guid, name=entity.get('Name')))
        else:
            raise ValueError('Unexpected compiled area entity class: ' + str(kind))
    if validate_only and removed:
        raise ValueError('SmartAreaShape geometry is also registered as a compiled trigger')
    return (write_areas(kept, parsed['export_version']) if removed else blob), removed
