"""Resolve a merchant's physical source stash independently of its shop marker."""
from contextlib import ExitStack
import copy
from pathlib import Path
import xml.etree.ElementTree as ET
import zipfile

from static_assets import asset_pack
from upgrade_map import read


def source_stash(source, shop):
    with zipfile.ZipFile(source / 'Data/Levels/rataje/level.pak') as archive:
        entities = list(ET.fromstring(read(archive, 'objects_mission0.xml')).iter('Entity'))
    targets = {link.get('TargetId') for link in shop.findall('EntityLinks/Link')}
    matches = [e for e in entities if e.get('EntityId') in targets and e.get('EntityClass') == 'Stash']
    if len(matches) != 1:
        raise ValueError('Shop must link to exactly one source stash')
    return copy.deepcopy(matches[0])


def stash_assets(source, stash, prefix):
    model = stash.find('Properties').get('object_Model').replace('\\', '/').lower()
    with ExitStack() as stack:
        index, emitted, material, mesh = asset_pack(stack, source.parent, prefix)
        emitted[prefix + Path(model).name] = mesh(model)
        for lod in (1, 2, 3):
            path = model[:-4] + f'_lod{lod}' + model[-4:]
            if path in index:
                emitted[prefix + Path(path).name] = mesh(path)
        with zipfile.ZipFile(source / 'Data/Objects.pak') as archive:
            for name in archive.namelist():
                if name.lower().startswith(model.rsplit('/', 1)[0] + '/') and name.lower().endswith(('.anm', '.animevents')):
                    emitted[prefix + Path(name).name] = read(archive, name)
        return {name: value.read_bytes() if isinstance(value, Path) else value for name, value in emitted.items()}


def apply_stash_placement(stash, authored, prefix):
    for key in ('Pos', 'Rotate', 'Scale'):
        if authored.get(key) is not None:
            stash.set(key, authored.get(key))
    props = stash.find('Properties')
    original = authored.find('Properties')
    props.set('object_Model', prefix + Path(original.get('object_Model').replace('\\', '/')).name.lower())
    for key in ('fUseAngle', 'fUseDistance', 'sWH_AI_EntityCategory'):
        if original.get(key) is not None:
            props.set(key, original.get(key))
    for tag in ('Animation', 'Physics'):
        previous = props.find(tag)
        if previous is not None:
            props.remove(previous)
        props.append(copy.deepcopy(original.find(tag)))
    # Keep this service chest at its authored location, not a movable rigid body.
    props.find('Physics').set('bRigidBody', '0')
