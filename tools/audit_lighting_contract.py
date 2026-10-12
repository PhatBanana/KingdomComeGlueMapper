"""Compare packaged source, converted and native lighting dependencies, read-only."""
import argparse
import copy
import hashlib
import json
from pathlib import Path
import struct
import xml.etree.ElementTree as ET
import zipfile

from cooking_pots import rotate
from upgrade_map import read
from world_lighting import defaults, overlay


from lighting_clips import clip_geometry, bsp_contains


def entities(archive):
    result = []
    for name in archive.namelist():
        if not name.lower().endswith('.xml'):
            continue
        blob = read(archive, name)
        if b'EnvironmentLight' not in blob and b'ClipVolume' not in blob:
            continue
        root = ET.fromstring(blob)
        for e in root.iter('Entity'):
            if e.get('EntityClass') in ('EnvironmentLight', 'ClipVolume'):
                result.append((name, e))
    return result


def effective(entity, schema):
    props = copy.deepcopy(schema)
    overlay(props, entity.find('Properties'))
    return {path: dict(props.find(path).attrib) for path in ('Options', 'Color', 'Projection')}


def audit(source, target, mod):
    report = {'worlds': {}, 'house_clips': [], 'house_probes': [],
              'limits': ['BSP compatibility is structural, not proof of native renderer registration.',
                         'No nearest-volume associations are invented by this audit.']}
    schemas = {}
    for label, game in [('source', source), ('native', target)]:
        with zipfile.ZipFile(game/'Data/Scripts.pak') as z:
            name = next(n for n in z.namelist() if n.lower().endswith('/environmentlight.lua'))
            schemas[label] = defaults(read(z, name))
    paths = {'source': source/'Data/Levels/rataje/level.pak',
             'native': target/'Data/Levels/trosecko/level.pak',
             'converted': mod/'Data/Levels/kcd1_travel/level.pak'}
    clips = {}
    for label, path in paths.items():
        with zipfile.ZipFile(path) as z:
            names = {n.lower(): n for n in z.namelist()}
            records = entities(z)
            probes = [e for _, e in records if e.get('EntityClass') == 'EnvironmentLight']
            schema = schemas['source' if label == 'source' else 'native']
            opts = [effective(e, schema)['Options'] for e in probes]
            report['worlds'][label] = {'package': str(path), 'probes': len(probes),
                'ignore_visibility_areas': sum(o['bIgnoresVisAreas'] == '1' for o in opts),
                'deferred_clip_bounds': sum(o['bDeferredClipBounds'] == '1' for o in opts),
                'probes_with_links': sum(bool(e.findall('EntityLinks/Link')) for e in probes)}
            for _, e in records:
                name = e.get('Name', '')
                if e.get('EntityClass') == 'ClipVolume' and (
                    name in ('ClipVolume_henryhouse_a', 'ClipVolume_henryhouse_b', 'ClipVolume_henryhouse_d',
                             'gm_lighting_8756', 'gm_lighting_8775', 'gm_lighting_8795')):
                    node = e.find('ClipVolume')
                    asset = node.get('GeometryFileName').replace('%level%/', '').lower()
                    geometry, bsp = clip_geometry(read(z, names[asset]))
                    report['house_clips'].append(dict(world=label, name=name, asset=asset,
                        entity=dict(e.attrib), flags=node.get('Flags'), geometry=geometry))
                    if label == 'source': clips[name] = (e, geometry, bsp)
                if name in ('skalice_forge_probe_2', 'skalice_forge_probe_5', 'level_global_probe',
                            'gm_lighting_26456', 'gm_lighting_26457', 'gm_lighting_26965', 'global_probe_trosecko'):
                    report['house_probes'].append(dict(world=label, entity=dict(e.attrib),
                        effective=effective(e, schema), authored=ET.tostring(e, encoding='unicode')))
            if label == 'native':
                native_clip = next(e for _, e in records if e.get('EntityClass') == 'ClipVolume')
                asset = native_clip.find('ClipVolume').get('GeometryFileName').replace('%level%/', '').lower()
                report['native_clip_example'] = clip_geometry(read(z, names[asset]))[0]
    for probe in report['house_probes']:
        if probe['world'] != 'source' or 'forge' not in probe['entity']['Name']:
            continue
        e = ET.fromstring(probe['authored']);p = e.find('Properties')
        pos = tuple(map(float, e.get('Pos').split(',')))
        rotation = tuple(map(float, e.get('Rotate', '1,0,0,0').split(',')))
        offset = rotate(rotation, [float(p.get('GenOffset'+a, '0')) for a in 'XYZ'])
        points = {'entity_origin': pos, 'bake_origin': [a+b for a,b in zip(pos,offset)]}
        probe['clip_membership'] = {}
        for point_name, point in points.items():
            matches = []
            for name, (clip, geometry, bsp) in clips.items():
                q = tuple(map(float, clip.get('Rotate', '1,0,0,0').split(',')))
                origin = tuple(map(float, clip.get('Pos').split(',')))
                local = rotate((q[0],-q[1],-q[2],-q[3]), [a-b for a,b in zip(point,origin)])
                lo, hi = geometry['local_bounds']
                if all(lo[a] <= local[a] <= hi[a] for a in range(3)) and bsp_contains(bsp, local):
                    matches.append(name)
            probe['clip_membership'][point_name] = {'position': point, 'inside': matches}
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('source','target','mod','output'):
        parser.add_argument('--'+name,type=Path,required=True)
    args = vars(parser.parse_args());output = args.pop('output')
    result = audit(**args)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2)+'\n', encoding='utf-8')
    print(json.dumps(result['worlds'], indent=2))
    for probe in result['house_probes']:
        if 'clip_membership' in probe: print(probe['entity']['Name'], probe['clip_membership'])
