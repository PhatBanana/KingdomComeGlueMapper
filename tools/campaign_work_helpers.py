"""Reuse native work helpers only when their local interaction contract matches."""
import copy
import math
from pathlib import Path
import xml.etree.ElementTree as ET
import zipfile

from campaign_dependencies import ImportPlan
from campaign_entity_links import guid_value
from campaign_quest_graph import xml
from upgrade_map import read


def family(root, identity):
    classes = [e for e in root.findall('Class') if e.get('name', '').lower() == identity.lower()]
    if len(classes) != 1:
        raise ValueError('Missing or ambiguous work helper class: ' + identity)
    name = classes[0].get('name')
    if classes[0].get('template'):
        raise ValueError('Inherited work helper template needs conversion: ' + name)
    helpers = {}
    for e in root.findall('Helper'):
        if e.get('className') != name:
            continue
        if not e.get('name') or e.get('name') in helpers:
            raise ValueError('Duplicate or unnamed work helper: ' + name)
        helpers[e.get('name')] = e
    return name, helpers


def equivalent(source, target):
    if source.keys() != target.keys():
        raise ValueError('Work helper point sets differ')
    for name, old in source.items():
        new = target[name]
        # Description contains executable Animation/Category declarations.
        ignored = {'className', 'pos', 'rot'}
        if {k:v for k,v in old.attrib.items() if k not in ignored} != {
                k:v for k,v in new.attrib.items() if k not in ignored}:
            raise ValueError('Work helper animation declarations differ: ' + name)
        for field, size in (('pos', 3), ('rot', 4)):
            a, b = [tuple(map(float, e.get(field, '').split(','))) for e in (old, new)]
            if len(a) != size or len(b) != size or not all(map(math.isfinite, a+b)):
                raise ValueError('Invalid work helper transform: ' + name)
            distance = max(abs(x-y) for x,y in zip(a,b))
            if field == 'rot':
                distance = min(distance, max(abs(x+y) for x,y in zip(a,b)))
            if distance > 1e-5:
                raise ValueError('Work helper transform differs: ' + name)


class WorkHelperAdapter:
    def __init__(self, source, native, collections):
        self.source, self.native, self.collections = source, native, collections

    @classmethod
    def load(cls, source, target):
        with zipfile.ZipFile(Path(source)/'Data/GameData.pak') as old, \
             zipfile.ZipFile(Path(target)/'Data/IPL_GameData.pak') as new, \
             zipfile.ZipFile(Path(target)/'Data/Levels/trosecko/level.pak') as level:
            return cls(ET.fromstring(read(old, 'Libs/SmartObjects.xml')),
                       ET.fromstring(read(new, 'Libs/SmartObjects.xml')),
                       ET.fromstring(read(level, 'smartobjecthelpersetanimations.xml')))

    def plan(self, identity):
        old_name, old = family(self.source, identity)
        name, new = family(self.native, identity)
        equivalent(old, new)
        matches = [e for e in self.collections if e.get('HelperSetName') == name]
        if len(matches) != 1:
            raise ValueError('Missing or ambiguous native work animation collection: ' + name)
        collections = matches[0].findall('SmartObjectHelperSetAnimationCollection')
        if len(collections) != 1 or not collections[0].get('HashValue'):
            raise ValueError('Work animation collection needs variant resolution: ' + name)
        return ImportPlan(source=dict(source_name=old_name, target=name,
            collection=ET.tostring(matches[0], encoding='unicode'), points=sorted(old)))

    def convert(self, identity, plan, registered):
        return plan.source['target'], {'world/work_helpers/' + identity + '.xml':
            plan.source['collection'].encode()}, dict(points=plan.source['points'],
                local_transforms_verified=True, native_animations=True)


def assemble(objects, imported):
    """Emit native collections and per-instance transforms at converted positions."""
    collections = ET.Element('SmartObjectAnimationCollections')
    available = {}
    for path, value in sorted(imported.items()):
        if not path.startswith('world/work_helpers/'):
            continue
        node = ET.fromstring(value.read_bytes() if isinstance(value, Path) else value)
        name = node.get('HelperSetName')
        if name in available:
            raise ValueError('Duplicate converted work helper collection: ' + str(name))
        available[name] = node
    table = ET.Element('database', name='barbora')
    rows = ET.SubElement(table, 'SmartObjectAnimationss', version='1')
    used = set()
    for entity in objects.iter('Entity'):
        if entity.get('EntityClass') not in ('SmartObjectHolder','ItemSlot'):
            continue
        props = entity.find('Properties')
        name = props.get('soclass_SmartObjectHelpers') if props is not None else None
        if not name:
            continue
        if name not in available:
            raise ValueError('Placed work object has no converted animation collection: ' + name)
        scale = tuple(map(float, entity.get('Scale', '1,1,1').split(',')))
        if len(scale) != 3 or any(not math.isfinite(v) or abs(v-1) > 1e-5 for v in scale):
            raise ValueError('Scaled work helper requires animation-transform conversion: ' + name)
        position = tuple(map(float, entity.get('Pos', '').split(',')))
        rotation = tuple(map(float, entity.get('Rotate', '1,0,0,0').split(',')))
        if len(position) != 3 or len(rotation) != 4 or not all(map(math.isfinite, position+rotation)):
            raise ValueError('Invalid placed work helper transform: ' + name)
        variants = available[name].findall('SmartObjectHelperSetAnimationCollection')
        if len(variants) != 1 or not variants[0].get('HashValue'):
            raise ValueError('Ambiguous placed work animation collection: ' + name)
        used.add(name)
        row = ET.SubElement(rows, 'SmartObjectAnimations',
            EntityGuid=str(guid_value(entity.get('EntityGuid'))), Hash=variants[0].get('HashValue'),
            AllowRuntimeAnimValidationFallback='true')
        ET.SubElement(row, 'SmartObjectTransform', Position=entity.get('Pos'),
                      Rotation=entity.get('Rotate', '1,0,0,0'))
    for name in sorted(used):
        collections.append(copy.deepcopy(available[name]))
    if not used:
        return {}
    return {'world/registration/smartobjecthelpersetanimations.xml': xml(collections),
            'world/registration/tables/ai/smartobjectanimations.xml': xml(table)}
