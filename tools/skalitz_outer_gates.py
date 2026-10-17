"""Open the six authored outer-town gate leaves, retaining their gatehouses.

Placements and orientations come from intact KCD1 sv_state0 brushes. Generated
mesh numbers are deliberately not identities. This is an opt-in test-world
override, not a replacement for campaign-controlled door animation.
"""
import itertools
import math
import struct
import xml.etree.ElementTree as ET
from upgrade_map import xml

# x, y, z, source first rotation row (uniform scale included), opening direction.
LEAVES = (
    (752.3049926757812,3530.66455078125,50.880592346191406,-.8778586387634277,.5700889229774475,1),
    (754.8948974609375,3532.350830078125,50.88056564331055,-.8778587579727173,.5700886249542236,-1),
    (867.8873291015625,3393.803955078125,36.816505432128906,1.0238535404205322,.21762606501579285,1),
    (864.8636474609375,3394.44287109375,36.81783676147461,1.0238534212112427,.21762636303901672,-1),
    (828.72265625,3520.096923828125,50.60757827758789,-.8134598135948181,-.6587262749671936,-1),
    (826.3438720703125,3522.0244140625,50.60760498046875,-.813460111618042,-.6587260961532593,1),
)


def normalize(files):
    """Idempotently correct fresh or previously raised-portcullis packages."""
    from build_open_test_gates import GRATES, LIFT
    data = bytearray(files['terrain/hlods.dat'])
    root = ET.fromstring(files['terrain/hlods.xml'])
    if struct.unpack_from('<I', data)[0] != 2:
        raise ValueError('Unknown HLOD format')
    found = set(); restored = 0; opened = 0
    for group in root.iter('HLod'):
        start = int(group.get('DataOffset')); end = start + int(group.get('DataSize'))
        if end > len(data) or struct.unpack_from('<I', data, start)[0] != end-start-4:
            raise ValueError('Invalid HLOD block')
        cursor = start+4
        while cursor < end:
            kind = struct.unpack_from('<I', data, cursor)[0]
            if kind not in (1, 2): raise ValueError('Unknown HLOD record')
            if kind == 1:
                t = list(struct.unpack_from('<12f', data, cursor+44))
                point = (t[3], t[7], t[11])
                for p in GRATES:
                    if math.dist(point, (p[0],p[1],p[2]+LIFT)) < .01:
                        for off in (12,24,88):
                            struct.pack_into('<f', data, cursor+off, struct.unpack_from('<f',data,cursor+off)[0]-LIFT)
                        restored += 1
                for i, (x,y,z,a,b,direction) in enumerate(LEAVES):
                    if math.dist(point, (x,y,z)) >= .01: continue
                    if i in found: raise ValueError('Duplicate outer gate leaf')
                    found.add(i)
                    original = (a,b,0,x,-b,a,0,y,0,0,1.0467270612716675,z)
                    target = list(original)
                    for j in range(3):
                        target[j] = -direction*original[4+j]
                        target[4+j] = direction*original[j]
                    if all(abs(v-w)<1e-5 for v,w in zip(t,target)): continue
                    if not all(abs(v-w)<1e-5 for v,w in zip(t,original)):
                        raise ValueError('Outer gate source transform changed')
                    # Rotate the render/collision AABB with the same hinge transform.
                    bounds = struct.unpack_from('<6f',data,cursor+4)
                    points = [(x-direction*(py-y), y+direction*(px-x), pz)
                        for px,py,pz in itertools.product(*[(bounds[j],bounds[j+3]) for j in range(3)])]
                    new_bounds = tuple(min(p[j] for p in points) for j in range(3)) + tuple(max(p[j] for p in points) for j in range(3))
                    struct.pack_into('<6f',data,cursor+4,*new_bounds)
                    struct.pack_into('<12f',data,cursor+44,*target)
                    group.set('Radius',str(float(group.get('Radius'))+8))
                    opened += 1
            cursor += 104 if kind == 1 else 64
        if cursor != end: raise ValueError('Invalid HLOD boundary')
    if len(found) != len(LEAVES): raise ValueError('Expected all six Skalitz outer palisade gate leaves')
    result = dict(files)
    result.update({'terrain/hlods.dat':bytes(data),'terrain/hlods.xml':xml(root)})
    return result, dict(opened_leaves=opened, restored_castle_portcullises=restored,
        outer_gate_sites=3, runtime_passage_verified=False)
