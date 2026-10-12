"""Restore authored ladders with KCD2's native player climbing contract."""
import copy
import math
import xml.etree.ElementTree as ET

from campaign_entity_links import guid_value
from chairs import inventory
from cooking_pots import vector
from entity_visuals import world_transform
from seating_animations import HELPERS, ANIMATIONS
from upgrade_map import read

PREFIX = 'gm_ladder_'
SOURCE_TYPE = '6ec5aa20-ecd7-47e2-913f-3f94d78e439e'
LEVEL_FILES = ('objects_mission0.xml', HELPERS, ANIMATIONS)


def check_helpers(source, native, family):
    """Same-named helpers must also have equivalent local transforms."""
    def collect(root):
        return {e.get('name'): e for e in root.findall('Helper') if e.get('className') == family}
    a, b = collect(source), collect(native)
    if not {'up', 'down', 'align'} <= a.keys() or a.keys() != b.keys():
        raise ValueError('Missing native ladder helpers: ' + family)
    for name in a:
        for field, size in (('pos', 3), ('rot', 4)):
            x = tuple(map(float, a[name].get(field).split(',')))
            y = tuple(map(float, b[name].get(field).split(',')))
            if len(x) != size or len(y) != size or not all(map(math.isfinite, x+y)):
                raise ValueError('Invalid ladder helper transform: ' + family)
            distance = max(abs(i-j) for i, j in zip(x, y))
            if field == 'rot': distance = min(distance, max(abs(i+j) for i, j in zip(x, y)))
            if distance > 1e-5: raise ValueError('Different native ladder helper transform: ' + family)


def convert(files, source, native, source_helpers, native_helpers, guid):
    entities, ladders, deferred = inventory(source, 'Ladder')
    root = ET.fromstring(files['objects_mission0.xml'])
    if any(e.get('Name', '').startswith(PREFIX) for e in root.iter('Entity')):
        raise ValueError('Ladders already converted; use the pre-conversion baseline')
    native_entities = ET.fromstring(read(native, 'objects_mission0.xml'))
    types = {e.find('Properties').get('guidSmartObjectType') for e in native_entities.iter('Entity')
             if e.get('EntityClass') == 'Ladder'}
    if len(types) != 1 or not next(iter(types)):
        raise ValueError('Expected one native ordinary-ladder smart-object type')
    native_type = next(iter(types))
    src_helpers, dst_helpers = ET.fromstring(source_helpers), ET.fromstring(native_helpers)
    collections = ET.fromstring(files.get(HELPERS, b'<SmartObjectAnimationCollections/>'))
    available = {e.get('HelperSetName'): e for e in ET.fromstring(read(native, HELPERS))}
    table = ET.fromstring(files.get(ANIMATIONS, b'<database name="barbora"><SmartObjectAnimationss version="1"/></database>'))
    rows = table.find('SmartObjectAnimationss')
    if rows is None or collections.tag != 'SmartObjectAnimationCollections':
        raise ValueError('Unexpected smart-object animation format')
    visuals = {e.get('Name'): e for e in root.iter('Entity')}
    next_id = max((int(e.get('EntityId', '0')) for e in root.iter('Entity')), default=0)+1
    records, families, removed = [], set(), set()
    for original in sorted(ladders, key=lambda e: int(e.get('EntityId'))):
        key = original.get('EntityId')
        visual = visuals.get('glue_item_' + key)
        if visual is None or not visual.get('Geometry'):
            raise ValueError(f'Ladder {key}: converted geometry is missing')
        if original.findall('EntityLinks/Link'):
            raise ValueError(f'Ladder {key}: source links require conversion')
        p, q, scale = world_transform(original, entities)
        if any(abs(s-1) > 1e-5 for s in scale):
            raise ValueError(f'Ladder {key}: non-unit scale needs climb-distance validation')
        props = copy.deepcopy(original.find('Properties'))
        height = float(props.get('height', '3.7'))
        if not math.isfinite(height) or height <= 0:
            raise ValueError(f'Ladder {key}: invalid climb height')
        family = props.attrib.pop('soclasses_SmartObjectHelpers', '')
        source_type = props.get('guidSmartObjectType', '')
        if source_type not in ('', SOURCE_TYPE) or (not family and source_type):
            raise ValueError(f'Ladder {key}: unsupported source smart-object contract')
        if props.get('esLadderType', 'Ladder') != 'Ladder':
            raise ValueError(f'Ladder {key}: siege ladder needs a separate contract')
        if family:
            check_helpers(src_helpers, dst_helpers, family)
            if family not in available: raise ValueError('Missing ladder animation collection: '+family)
            families.add(family)
        # Some source ladders deliberately have no AI type; two also lack helpers.
        # Player climbing is implemented by native Ladder.lua independently.
        props.set('soclass_SmartObjectHelpers', family)
        props.set('guidSmartObjectType', native_type if source_type else '')
        props.set('fileModel', visual.get('Geometry'))
        props.set('esNavCompoment', 'Ladder')  # Shipped property spelling.
        props.set('bDrawWeaponOntop', 'false')
        for group in props.iter():
            for name, value in list(group.attrib.items()):
                if name.startswith('b'):
                    if value.lower() not in ('0', '1', 'true', 'false'):
                        raise ValueError(f'Ladder {key}: invalid boolean {name}')
                    group.set(name, 'true' if value.lower() in ('1', 'true') else 'false')
        node = ET.Element('Entity', EntityId=str(next_id), EntityGuid=guid('ladder/'+key),
                          EntityClass='Ladder', Name=PREFIX+key, Pos=vector(p), Rotate=vector(q), Scale=vector(scale))
        next_id += 1
        for attr in ('Material', 'ViewDistRatio', 'CastShadowMinSpec'):
            if attr in visual.attrib: node.set(attr, visual.get(attr))
        node.append(props)
        root.append(node)
        removed.add(visual.get('Name'))
        if family:
            row = ET.SubElement(rows, 'SmartObjectAnimations', EntityGuid=str(guid_value(node.get('EntityGuid'))),
                                Hash='0', AllowRuntimeAnimValidationFallback='true')
            ET.SubElement(row, 'SmartObjectTransform', Position=node.get('Pos'), Rotation=node.get('Rotate'))
        records.append(dict(source_id=key, position=p, height=height, helper_family=family,
                            source_model=original.find('Properties').get('fileModel'),
                            converted_model=visual.get('Geometry'), entity_guid=node.get('EntityGuid')))
    for parent in root.iter():
        for child in list(parent):
            if child.get('Name') in removed: parent.remove(child)
    for family in sorted(families):
        for old in list(collections):
            if old.get('HelperSetName') == family: collections.remove(old)
        collections.append(copy.deepcopy(available[family]))
    result = dict(files)
    for name, tree in zip(LEVEL_FILES, (root, collections, table)):
        result[name] = ET.tostring(tree, encoding='utf-8', xml_declaration=True)
    return result, dict(converted=len(records), visuals_replaced=len(removed), records=records,
                        native_type=native_type, families=sorted(families), inactive_layers=deferred,
                        runtime_verified=False)


def build(files, source, target, guid):
    import zipfile
    from pathlib import Path
    source, target = Path(source), Path(target)
    with zipfile.ZipFile(source/'Data/Levels/rataje/level.pak') as src, \
         zipfile.ZipFile(target/'Data/Levels/trosecko/level.pak') as native, \
         zipfile.ZipFile(source/'Data/GameData.pak') as sg, \
         zipfile.ZipFile(target/'Data/IPL_GameData.pak') as ng:
        def helpers(z):
            name = next(n for n in z.namelist() if n.lower() == 'libs/smartobjects.xml')
            return read(z, name)
        return convert(files, src, native, helpers(sg), helpers(ng), guid)
