"""Native replacements for KCD1 shader names and flags that KCD2 no longer declares."""
from functools import lru_cache
from pathlib import PurePosixPath
import copy
import re
import xml.etree.ElementTree as ET
import zipfile

from build_water_probe import shader_features
from upgrade_map import read

# KCD2 retired GeometryBeam; its own light-shaft material, converted from the
# same KCD1 asset family, now renders through this native material.
NATIVE_BEAM = 'objects/manmade/common_illumination/lightshafts/lightshafts.mtl'
BEAM_ATTRIBUTES = ('Shader', 'GenMask', 'StringGenMask', 'Diffuse', 'Specular', 'Shininess', 'Opacity')


@lru_cache(maxsize=None)
def target_features(library):
    """Named permutation features of each KCD2 shader, from its .ext file."""
    features = {}
    for path in sorted((library / 'KingdomComeDeliverance2/Engine').glob('*.pak')):
        with zipfile.ZipFile(path) as archive:
            for name in archive.namelist():
                if name.lower().endswith('.ext'):
                    stem = PurePosixPath(name.replace('\\', '/')).stem.lower()
                    features[stem] = shader_features(read(archive, name).decode(errors='replace'))
    if not features:
        raise FileNotFoundError('KCD2 shader definitions')
    return features


def drop_undeclared_features(element, features):
    """Remove named flags the target shader does not declare; the engine ignores them.

    Shaders without a .ext (Nodraw) carry no named features to check.
    """
    declared = features.get(element.get('Shader', '').lower())
    flags = re.findall(r'%\w+', element.get('StringGenMask', ''))
    if declared is None or not flags:
        return []
    removed = [flag for flag in flags if flag not in declared]
    if removed:
        element.set('StringGenMask', ''.join(flag for flag in flags if flag in declared))
    return removed


@lru_cache(maxsize=None)
def native_beam_material(library):
    for path in sorted((library / 'KingdomComeDeliverance2/Data').glob('*.pak')):
        try:
            archive = zipfile.ZipFile(path)
        except zipfile.BadZipFile:
            continue
        with archive:
            entry = next((n for n in archive.namelist()
                          if n.replace('\\', '/').lower() == NATIVE_BEAM), None)
            if entry is not None:
                return ET.tostring(ET.fromstring(read(archive, entry)))
    raise FileNotFoundError(NATIVE_BEAM)


def replace_retired_beam(element, native):
    """Render a KCD1 GeometryBeam material the way KCD2's own light shafts do.

    The native shader contract and its tuned colours replace the beam's;
    the source textures stay bound.
    """
    if element.get('Shader', '').lower() != 'geometrybeam':
        return False
    if native.get('Shader', '').lower() == 'geometrybeam':
        raise ValueError('Native light-shaft material still uses GeometryBeam')
    for name in BEAM_ATTRIBUTES:
        if name in native.attrib:
            element.set(name, native.get(name))
        else:
            element.attrib.pop(name, None)
    params = element.find('PublicParams')
    if params is not None:
        element.remove(params)
    native_params = native.find('PublicParams')
    if native_params is not None:
        element.append(copy.deepcopy(native_params))
    return True
