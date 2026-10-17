import struct
import sys
import unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from skalitz_outer_gates import LEAVES, normalize
from build_open_test_gates import GRATES


def fixture():
    rows=[]
    for x,y,z,a,b,d in LEAVES:
        r=bytearray(104);struct.pack_into('<I',r,0,1)
        struct.pack_into('<6f',r,4,x-2,y-.2,z,x+2,y+.2,z+4)
        struct.pack_into('<12f',r,44,a,b,0,x,-b,a,0,y,0,0,1.0467270612716675,z)
        rows.append(r)
    for x,y,z in GRATES:
        r=bytearray(104);struct.pack_into('<I',r,0,1)
        struct.pack_into('<6f',r,4,x-1,y-1,z+4,x+1,y+1,z+8)
        struct.pack_into('<12f',r,44,1,0,0,x,0,1,0,y,0,0,1,z+4)
        rows.append(r)
    # Unrelated brush must remain byte-identical.
    rows.append(bytearray(rows[0]));struct.pack_into('<f',rows[-1],56,100)
    return {'terrain/hlods.dat':struct.pack('<II',2,len(rows)*104)+b''.join(rows),
        'terrain/hlods.xml':f'<HLod DataOffset="4" DataSize="{len(rows)*104+4}" Radius="8000"/>'.encode()}


class OuterGateTests(unittest.TestCase):
    def test_opens_leaves_restores_inner_gates_and_is_idempotent(self):
        f=fixture();updated,report=normalize(f)
        self.assertEqual(report['opened_leaves'],6)
        self.assertEqual(report['restored_castle_portcullises'],2)
        data=updated['terrain/hlods.dat']
        self.assertEqual(data[-104:],f['terrain/hlods.dat'][-104:])
        for i,(x,y,z,a,b,d) in enumerate(LEAVES):
            t=struct.unpack_from('<12f',data,8+i*104+44)
            self.assertEqual((t[3],t[7],t[11]),(x,y,z))
            self.assertAlmostEqual(t[0],d*b,places=5)
            bounds=struct.unpack_from('<6f',data,8+i*104+4)
            self.assertAlmostEqual(bounds[3]-bounds[0],.4,places=3)
            self.assertAlmostEqual(bounds[4]-bounds[1],4,places=3)
        for i,p in enumerate(GRATES):
            self.assertEqual(struct.unpack_from('<f',data,8+(6+i)*104+88)[0],p[2])
        again,r=normalize(updated)
        self.assertEqual(again,updated);self.assertEqual(r['opened_leaves'],0)

    def test_unexpected_transform_rejected(self):
        f=fixture();data=bytearray(f['terrain/hlods.dat'])
        struct.pack_into('<f',data,8+44,4)
        f['terrain/hlods.dat']=data
        with self.assertRaisesRegex(ValueError,'transform changed'):normalize(f)
