"""Place native lean helpers at the authored KCD1 alignment transform."""
import copy
from pathlib import Path
import xml.etree.ElementTree as ET
import zipfile

from character_person import unique
from cooking_pots import rotate
from entity_visuals import quaternion_product
from upgrade_map import read


def align(point, source_xml, native_xml, family):
    def helper(blob, cls, name):
        return unique((e for e in ET.fromstring(blob).iter('Helper')
                       if e.get('className') == cls and e.get('name') == name), 'lean alignment helper')
    old = helper(source_xml, 'LeaningSpot', 'align')
    new = helper(native_xml, family, family)
    vector = lambda e, key: tuple(map(float, e.get(key).split(',')))
    old_q, new_q = vector(old, 'rot'), vector(new, 'rot')
    correction = quaternion_product(old_q, (new_q[0], -new_q[1], -new_q[2], -new_q[3]))
    native_offset = rotate(correction, vector(new, 'pos'))
    offset = tuple(a-b for a,b in zip(vector(old, 'pos'), native_offset))
    q = tuple(map(float, point.get('Rotate', '1,0,0,0').split(',')))
    world_offset = rotate(q, offset)
    result = copy.deepcopy(point)
    result.set('Pos', ','.join(format(a+b, '.9g') for a,b in zip(vector(point, 'Pos'), world_offset)))
    result.set('Rotate', ','.join(format(v, '.9g') for v in quaternion_product(q, correction)))
    return result


def native_placement(point, source, target, family):
    with zipfile.ZipFile(Path(source)/'Data/GameData.pak') as old, \
         zipfile.ZipFile(Path(target)/'Data/IPL_GameData.pak') as new:
        return align(point, read(old, 'Libs/SmartObjects.xml'), read(new, 'Libs/SmartObjects.xml'), family)
