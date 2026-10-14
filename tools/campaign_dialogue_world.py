"""Discover and convert trigger polygons referenced by source dialogue predicates."""
import re
import xml.etree.ElementTree as E

from campaign_dialogue_conditions import expand_functions, TOKEN
from campaign_entity_links import native_guid
from campaign_trigger_areas import read_areas, write_areas
from upgrade_map import xml


def area_references(models):
    references = set()
    for model in models:
        for topic in model['topics'].values():
            for sequence in topic['sequences']:
                expressions = [sequence['entry'].get(k, '') for k in ('entry_condition', 'npc_entry_condition')]
                expressions.extend(e.get('condition', '') for e in sequence.get('effects', []))
                for expression in expressions:
                    source = expand_functions(expression, model.get('functions', {})).strip()
                    tokens, offset = [], 0
                    while offset < len(source):
                        match = TOKEN.match(source, offset)
                        if not match:
                            raise ValueError('Unparsed dialogue dependency expression: ' + source)
                        tokens.append(next(v for v in match.groups() if v is not None))
                        offset = match.end()
                    for i, token in enumerate(tokens):
                        if token != 'IsActorInside': continue
                        args = tokens[i+1:i+4]
                        if len(args) != 3 or args[0] != '(' or args[2] != ')' or not re.fullmatch(r"'[A-Za-z_]\w*'", args[1]):
                            raise ValueError('Dynamic dialogue area requires conversion')
                        references.add(args[1][1:-1])
    return references


def merge_areas(mission_blob, native_geometry, source_geometry, source_entities, names):
    """Preserve source GUIDs/world-space polygons and all unrelated native data."""
    mission = E.fromstring(mission_blob)
    native = read_areas(native_geometry)
    source = {a.guid: a for a in read_areas(source_geometry)['areas']}
    if native['version'] != 3: raise ValueError('Expected a native target area package')
    geometry = {a.guid: a for a in native['areas']}
    current = list(mission.iter('Entity'))
    next_id = max((int(e.get('EntityId', '0')) for e in current), default=0) + 1
    receipts = []
    for name in sorted(names):
        matches = [e for e in source_entities if e.get('Name') == name]
        if len(matches) != 1: raise ValueError('Missing or ambiguous source dialogue area: ' + name)
        original = matches[0]
        if original.get('EntityClass') != 'TriggerArea' or original.get('ParentGuid') not in (None, '', '0'):
            raise ValueError('Unsupported dialogue area class/attachment: ' + name)
        number = int(original.get('EntityGuid').replace('-', ''), 16)
        guid = native_guid(number)
        if number not in source: raise ValueError('Missing source dialogue polygon: ' + name)
        shape = source[number]
        if number in geometry and (shape.height, shape.points) != (geometry[number].height, geometry[number].points):
            raise ValueError('Conflicting installed dialogue polygon: ' + name)
        matches = [e for e in current if e.get('Name') == name or e.get('EntityGuid', '').lower() == guid]
        attributes = {k: original.get(k) for k in ('Name', 'Pos', 'Rotate', 'Scale') if original.get(k) is not None}
        attributes.update(EntityClass='TriggerArea', EntityGuid=guid)
        if matches:
            if len(matches) != 1 or any(matches[0].get(k) != v for k, v in attributes.items()):
                raise ValueError('Conflicting installed dialogue area: ' + name)
        else:
            entity = E.SubElement(mission, 'Entity', attributes, EntityId=str(next_id))
            E.SubElement(entity, 'Properties', bSaved_by_game='0', bTrackAlways='1')
            next_id += 1
            current.append(entity)
        geometry[number] = shape
        receipts.append(dict(name=name, guid=guid, vertices=len(shape.points), reused=bool(matches)))
    return xml(mission), write_areas(geometry.values(), native['export_version']), receipts
