"""Package native opacity GI using the same initial-state layers as the world."""
from pathlib import Path
import re
import xml.etree.ElementTree as ET
import zipfile

from entity_visuals import initial_layer
from upgrade_map import read
from voxel_lighting import convert_tile, validate_pair


def build(source, destination, tile=None):
    source = Path(source)
    dest = Path(destination)
    dest.mkdir(parents=True, exist_ok=True)
    if list(dest.glob('svo-part*.pak')):
        raise FileExistsError('Voxel packages already exist')
    report = {'mode': 'opacity-only basic GI', 'partial_test': tile is not None, 'tiles': []}
    with zipfile.ZipFile(source/'Data/Levels/rataje/level.pak') as world:
        layers = ET.fromstring(read(world, 'leveldata.xml')).find('Layers')
        active_layers = {0} | {int(e.get('Id')) for e in layers if initial_layer(e.get('Name', ''))}
    report['active_source_layers'] = sorted(active_layers)
    with zipfile.ZipFile(source/'Data/Levels/rataje/svo.pak') as src:
        names = [n for n in src.namelist() if n.endswith('.dat') and (tile is None or Path(n).stem == tile)]
        if not names:
            raise ValueError('No source voxel tiles selected')
        shard = None
        try:
            for number, name in enumerate(names):
                match = re.fullmatch(r'(\d+)_(\d+)_(\d+)_(\d+)\.dat', Path(name).name)
                if not match:
                    raise ValueError('Unexpected source voxel name')
                *center, extent = map(int, match.groups())
                idx, vox = convert_tile(read(src, name), center, extent, active_layers)
                if shard is None or shard.fp.tell()+len(idx)+len(vox) > 800*1024**2:
                    if shard is not None:
                        shard.close()
                    path = dest/f'svo-part{len(list(dest.glob("svo-part*.pak")))}.pak'
                    shard = zipfile.ZipFile(path, 'w', compression=zipfile.ZIP_STORED, allowZip64=False)
                shard.writestr(name[:-4]+'.idx', idx)
                shard.writestr(name[:-4]+'.vox', vox)
                report['tiles'].append(dict(name=name, **validate_pair(idx, vox)))
                print(f'Voxel tile {number+1}/{len(names)}: {name}', flush=True)
        finally:
            if shard is not None:
                shard.close()
    return report


def configure_environment(blob, *, surface_channels=False):
    """Configure the mission for its packaged channel layout.

    Mode 1 requires a validated surface bake; callers must not enable it for
    the legacy opacity-only output of build(). The accepted offline surface
    path keeps lighting dynamic while streaming precomputed geometry.
    """
    root = ET.fromstring(blob)
    gi = root.find('Environment/Total_Illumination_v2')
    if gi is None:
        raise ValueError('Missing level GI configuration')
    gi.set('Active', '1')
    gi.set('IntegrationMode', '1' if surface_channels else '0')
    gi.set('UseLightProbes', '0' if surface_channels else '1')
    if surface_channels:
        gi.set('UpdateLighting','1')
        # Native streamed levels keep this enabled. A precomputed voxel payload
        # does not replace runtime geometry/resource updates when cameras change
        # between the inventory scene and the world.
        gi.set('UpdateGeometry','1')
        gi.set('StreamVoxels','1')
    return ET.tostring(root, encoding='utf-8')
