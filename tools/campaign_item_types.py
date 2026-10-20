"""Resolve item enum identities by table names rather than source ordinals."""
from pathlib import Path
import xml.etree.ElementTree as ET
import zipfile
from upgrade_map import read


def native_tool_types(target):
    result = {}
    with zipfile.ZipFile(Path(target) / 'Data/Tables.pak') as archive:
        for name in ('npc_tool_type', 'npc_tool_subtype', 'ointment_item_type', 'ointment_item_subtype'):
            root = ET.fromstring(read(archive, 'Libs/Tables/item/' + name + '.xml'))
            result[name] = [dict(row.attrib) for row in root.iter(name)]
        root = ET.fromstring(read(archive, 'Libs/Tables/item/ItemManipulationType.xml'))
        result['item_manipulation_type'] = [dict(row.attrib) for row in root.iter('ItemManipulationData')]
    return result


def resolve(source_rows, target_rows, table, identity, retained_items=()):
    id_field, name_field = table + '_id', table + '_name'
    source = [r for r in source_rows if r.get(id_field) == identity]
    if len(source) != 1 or not source[0].get(name_field):
        raise ValueError('Missing or ambiguous source item type: ' + table + '/' + identity)
    name = source[0][name_field]
    retained_targets = {r['target_id'] for r in retained_items}
    if len(retained_targets) > 1:
        raise ValueError('Conflicting retained item type evidence: ' + table + '/' + identity)
    if retained_targets:
        matches = [r for r in target_rows if r.get(id_field) in retained_targets]
    else:
        if sum(r.get(name_field) == name for r in source_rows) != 1:
            raise ValueError('Ambiguous source item type name requires retained item evidence: ' + name)
        matches = [r for r in target_rows if r.get(name_field) == name]
    if len(matches) != 1 or not matches[0].get(id_field):
        raise ValueError('Missing or ambiguous native item type: ' + table + '/' + name)
    target = matches[0][id_field]
    if sum(r.get(id_field) == target for r in target_rows) != 1:
        raise ValueError('Duplicate native item type ordinal: ' + table + '/' + target)
    return target, dict(table=table, source_id=identity, source_name=name, target_id=target,
                        target_name=matches[0][name_field], retained_items=list(retained_items))


def manipulation(source_rows, target_rows, identity):
    source = [r for r in source_rows if r.get('id') == identity]
    if len(source) != 1 or not source[0].get('tag'):
        raise ValueError('Missing or ambiguous source manipulation type: ' + identity)
    source = source[0]
    matches = [r for r in target_rows if r.get('Tag', '').casefold() == source['tag'].casefold()]
    if len(matches) != 1 or not matches[0].get('Id'):
        raise ValueError('Missing or ambiguous native manipulation tag: ' + source['tag'])
    target = matches[0]
    if sum(r.get('Id') == target['Id'] for r in target_rows) != 1:
        raise ValueError('Duplicate native manipulation ordinal: ' + target['Id'])
    for old, new in (('allow_run', 'AllowRun'), ('allow_sprint', 'AllowSprint')):
        value = source.get(old, '').lower()
        if value not in ('true', 'false') or target.get(new, '').lower() != value:
            raise ValueError('Manipulation movement policy requires conversion: ' + source['tag'] + '/' + old)
    if source.get('sharpening_anim', '') != target.get('SharpeningAnim', ''):
        raise ValueError('Manipulation sharpening animation requires conversion: ' + source['tag'])
    return target['Id'], dict(source_id=identity, source_tag=source['tag'], target_id=target['Id'],
                              target_tag=target['Tag'], movement_policy_preserved=True)
