"""Read-only compiled ground/water coverage and layer audit for Skalitz."""
import argparse
from collections import Counter, defaultdict
import hashlib
import json
from pathlib import Path
import struct
import xml.etree.ElementTree as ET
import zipfile

from compiled_terrain import parse
from entity_visuals import initial_layer
from upgrade_map import read
from water_volumes import read_water, water_record
from vegetation import verify_target_hlods


def nearby(bounds):
    # Includes both town gates and approaches, not the whole province.
    return bounds[0] <= 1100 and bounds[3] >= 500 and bounds[1] <= 3700 and bounds[4] >= 3100


def inventory(terrain, layers=None):
    rows = []
    def visit(data, offset, size, kind):
        if kind not in (1, 7, 9, 11): return
        bbox = struct.unpack_from('<6f', data, offset+4)
        if not nearby(bbox): return
        extra = 4 if terrain.version == 29 else 0
        layer = struct.unpack_from('<H', data, offset+28)[0]
        row = dict(offset=offset, kind=kind, bbox=bbox, layer=layer,
                   layer_name=(layers or {}).get(layer, 'shared' if layer == 0 else 'unknown'),
                   flags=hex(struct.unpack_from('<Q' if extra else '<I', data, offset+32)[0]))
        if kind == 1:
            mesh = struct.unpack_from('<H', data, offset+36+extra)[0]
            row['mesh'] = terrain.tables['meshes']['paths'][mesh].lower()
            key = data[offset+4:offset+28] + data[offset+40+extra:offset+88+extra]
            mat = struct.unpack_from('<i', data, offset+92+extra)[0]
        elif kind == 9:
            w = water_record(data, offset, offset+size, terrain.version)
            key = data[offset+4:offset+28] + data[w['geometry_offset']:offset+size]
            mat = w['material']
        else:
            # Bounds prove candidate placement coverage, not shader/shape identity.
            key = data[offset+4:offset+28]
            mat = struct.unpack_from('<i', data, offset+(108 if kind == 7 else 104)+extra)[0]
        row['key'] = str(kind)+':'+hashlib.sha256(key).hexdigest()
        row['material'] = terrain.tables['materials']['paths'][mat] if mat >= 0 else ''
        row['initial'] = layer == 0 or initial_layer(row['layer_name'])
        rows.append(row)
    read_water(terrain, visit)
    return rows


def audit(source, mod):
    with zipfile.ZipFile(source/'Data/Levels/rataje/level.pak') as z:
        layers = {int(e.get('Id')):e.get('Name') for e in ET.fromstring(read(z,'leveldata.xml')).find('Layers')}
        original = inventory(parse(read(z,'terrain/terrain.dat')), layers)
    with zipfile.ZipFile(mod/'Data/Levels/kcd1_travel/terrain.pak') as z:
        terrain = parse(read(z,'terrain/terrain.dat'))
    target = inventory(terrain)
    with zipfile.ZipFile(mod/'Data/Levels/kcd1_travel/level.pak') as z:
        data = read(z, 'terrain/hlods.dat')
    verify_target_hlods(data)
    cursor = 4
    while cursor < len(data):
        end = cursor+4+struct.unpack_from('<I',data,cursor)[0]; cursor += 4
        while cursor < end:
            kind = struct.unpack_from('<I',data,cursor)[0]
            if kind == 1:
                bbox = struct.unpack_from('<6f',data,cursor+4)
                if nearby(bbox):
                    mesh = struct.unpack_from('<H',data,cursor+40)[0]
                    key = data[cursor+4:cursor+28]+data[cursor+44:cursor+92]
                    target.append(dict(kind=1, bbox=bbox, offset=cursor, mesh=terrain.tables['meshes']['paths'][mesh],
                        key='1:'+hashlib.sha256(key).hexdigest(), flags=hex(struct.unpack_from('<Q',data,cursor+32)[0])))
            cursor += 104 if kind == 1 else 64
    matches = defaultdict(list)
    for r in target: matches[r['key']].append(r)
    # Give an active placement priority when quest variants share exact bounds.
    for r in sorted(original,key=lambda r:not r['initial']):
        pool = matches[r['key']]
        r['present'] = bool(pool)
        if pool:
            match=pool.pop();r['target']=match
    ground_words=('terrain','land_deco','stream_edge','rock','ground','mud','puddle','water','ditch','gutter','canal')
    ground=[r for r in original if r['kind']!=1 or any(w in (r.get('mesh','')+' '+r['material']).lower() for w in ground_words)]
    missing=[r for r in ground if r['initial'] and not r['present']]
    unexpected=[r for r in ground if not r['initial'] and r['present']]
    return dict(region_xy=[500,3100,1100,3700], source_counts=dict(Counter(r['kind'] for r in original)),
        target_counts=dict(Counter(r['kind'] for r in target)),
        ground_counts=dict(Counter(('present' if r['present'] else 'absent')+('_initial' if r['initial'] else '_non_initial') for r in ground)),
        missing_initial=missing, imported_non_initial=unexpected,
        water=[r for r in original if r['kind']==9],
        unpaired_target=[r for pool in matches.values() for r in pool],
        records=ground,
        limits=['Brush correspondence uses exact bounds and transforms, not asset content.',
                'Water correspondence includes bounds and surface/physics geometry.',
                'Decal and road matches use bounds only; visual fidelity is not established.',
                'Initial-state classification follows current importer policy; unnamed/platform layers need editor ancestry review.',
                'This audits compiled brushes, decals, road records and water, not dynamic entities or vegetation.'])


if __name__ == '__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--source',type=Path,required=True);p.add_argument('--mod',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    r=audit(a.source,a.mod);a.output.parent.mkdir(parents=True,exist_ok=True)
    a.output.write_text(json.dumps(r,indent=2),encoding='utf-8')
    print(json.dumps({k:r[k] for k in ('source_counts','target_counts','ground_counts')},indent=2))
    print('Missing initial:',len(r['missing_initial']),'Imported non-initial:',len(r['imported_non_initial']))
