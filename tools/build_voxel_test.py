"""Stage converted KCD1 opacity voxels for native KCD2 basic GI testing."""
import argparse
import json
from pathlib import Path
import xml.etree.ElementTree as ET
import zipfile

from build_horse_trader_test import digest, rewrite
from upgrade_map import read
from world_voxels import build as build_voxels, configure_environment


def build(source, mod, output, tile=None):
    if output.exists():
        raise FileExistsError('Choose a fresh voxel staging directory')
    output.mkdir(parents=True)
    package = output/'package'
    relative = Path('Data/Levels/kcd1_travel')
    dest = package/relative
    dest.mkdir(parents=True)
    report = build_voxels(source, dest, tile)
    report['runtime_verified'] = False
    level = mod/relative/'level.pak'
    with zipfile.ZipFile(level) as z:
        root = ET.fromstring(read(z, 'mission_mission0.xml'))
    gi = root.find('Environment/Total_Illumination_v2')
    if gi is None:
        raise ValueError('Missing level GI configuration')
    report['previous_gi'] = dict(gi.attrib)
    mission = configure_environment(ET.tostring(root))
    report['generated_gi'] = ET.fromstring(mission).find('Environment/Total_Illumination_v2').attrib
    rewrite(level, dest/'level.pak', {'mission_mission0.xml': mission})
    report['baseline'] = digest(level)
    for path in dest.glob('*.pak'):
        with zipfile.ZipFile(path) as z:
            if z.testzip() is not None:
                raise ValueError('Voxel package CRC failure')
    report['files'] = {p.relative_to(package).as_posix(): digest(p) for p in package.rglob('*.pak')}
    (output/'voxel-report.json').write_text(json.dumps(report, indent=2)+'\n')
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('source', 'mod', 'output'):
        parser.add_argument('--'+name, type=Path, required=True)
    parser.add_argument('--tile', help='Limit an explicitly partial development test to one source tile')
    build(**vars(parser.parse_args()))
