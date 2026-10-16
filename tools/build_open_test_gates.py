"""Opt-in testing override for the reviewed Talburg and Skalitz gate pieces."""
import argparse
import json
import math
from pathlib import Path
import struct
import xml.etree.ElementTree as ET
import zipfile
from build_horse_trader_test import digest, rewrite
from compiled_terrain import parse
from upgrade_map import read, xml

GRATES = ((665.926513671875,3467.761962890625,68.28124237060547),
          (725.7950439453125,3473.84814453125,62.68354797363281))
LIFT = 4.0


def open_gates(files, meshes):
    data = bytearray(files['terrain/hlods.dat'])
    hierarchy = ET.fromstring(files['terrain/hlods.xml'])
    mission = ET.fromstring(files['objects_mission0.xml'])
    hits = []
    if struct.unpack_from('<I',data)[0] != 2:
        raise ValueError('Unknown HLOD format')
    for group in hierarchy.iter('HLod'):
        start = int(group.get('DataOffset')); size = int(group.get('DataSize'))
        if start+size > len(data) or struct.unpack_from('<I',data,start)[0] != size-4:
            raise ValueError('Invalid HLOD block')
        cursor = start+4
        while cursor < start+size:
            kind = struct.unpack_from('<I',data,cursor)[0]
            if kind not in (1,2):raise ValueError('Unknown record type')
            if kind == 1:
                mesh = meshes[struct.unpack_from('<H',data,cursor+40)[0]]
                position = tuple(struct.unpack_from('<f',data,cursor+i)[0] for i in (56,72,88))
                if mesh == 'gluebuild/setup_buildings/mesh1197.cgf' and any(math.dist(position,p)<.01 for p in GRATES):
                    if position in hits:raise ValueError('Duplicate gate placement')
                    hits.append(position)
                    # Move the actual brush and its world-space render/collision bounds.
                    for off in (12,24,88):
                        struct.pack_into('<f',data,cursor+off,struct.unpack_from('<f',data,cursor+off)[0]+LIFT)
                    group.set('Radius',str(float(group.get('Radius'))+LIFT))
            cursor += 104 if kind==1 else 64
        if cursor != start+size:raise ValueError('Invalid record boundary')
    if len(hits)!=2:raise ValueError('Expected two original Skalitz portcullises; wrong baseline or already applied')
    gates = [e for e in mission.iter('Entity') if e.get('Name')=='glue_item_124019']
    if len(gates)!=1:raise ValueError('Missing Talburg palisade gate')
    gate=gates[0]
    if gate.get('Geometry')!='gluebuild/setup_props/entity104.cga' or gate.get('Pos')!='2346.5435,2828.605,105.96074':
        raise ValueError('Talburg gate baseline changed')
    gate.set('Pos','2346.5435,2828.605,109.96074')
    result=dict(files)
    result.update({'terrain/hlods.dat':bytes(data),'terrain/hlods.xml':xml(hierarchy),'objects_mission0.xml':xml(mission)})
    return result,dict(skalitz_portcullises=[list(p) for p in hits],talburg_palisade='glue_item_124019',lift_metres=LIFT,
                       testing_only=True,runtime_passage_verified=False)


def build(mod, output):
    if output.exists():raise FileExistsError(output)
    level=mod/'Data/Levels/kcd1_travel/level.pak'
    with zipfile.ZipFile(mod/'Data/Levels/kcd1_travel/terrain.pak') as z:
        meshes=parse(read(z,'terrain/terrain.dat')).tables['meshes']['paths']
    with zipfile.ZipFile(level) as z:
        original={n:read(z,n) for n in ('terrain/hlods.dat','terrain/hlods.xml','objects_mission0.xml')}
    updated,report=open_gates(original,meshes)
    target=output/'Data/Levels/kcd1_travel/level.pak'
    rewrite(level,target,updated)
    with zipfile.ZipFile(level) as a,zipfile.ZipFile(target) as b:
        before={i.filename:(i.CRC,i.file_size) for i in a.infolist() if i.filename not in updated}
        after={i.filename:(i.CRC,i.file_size) for i in b.infolist() if i.filename not in updated}
        if before!=after:raise ValueError('Unrelated archive entries changed')
        for n,payload in updated.items():
            if read(b,n)!=payload:raise ValueError('Staging mismatch')
    report.update(baseline_sha256=digest(level),staged_sha256=digest(target),unrelated_entries_preserved=len(before),installed=False)
    (output/'gates.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report))


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--mod',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    build(**vars(p.parse_args()))
