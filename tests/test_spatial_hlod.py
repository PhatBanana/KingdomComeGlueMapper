import struct
import sys
from pathlib import Path
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from spatial_hlod import Group,hierarchy,world_hierarchy,serialize,records,read_groups


def brush(identity):
    b=bytearray(104);struct.pack_into('<I',b,0,1);struct.pack_into('<H',b,40,identity)
    return bytes(b)


class SpatialHlodTests(unittest.TestCase):
    def test_vegetation_uses_native_tiers_separate_from_buildings(self):
        leaves=[Group(str(i),'Vegetation',(32+(i%64)*64,32+(i//64)*64,80),100,[brush(i)],brush(i))
                for i in range(4096)]
        leaves.append(Group('house','Cluster',(100,100,30),100,[brush(1)],brush(2)))
        root=world_hierarchy(leaves)
        self.assertEqual([n.kind for n in root.children], ['Layer','Vegetation'])
        veg=root.children[1]
        self.assertEqual(len(veg.children),16)
        self.assertTrue(all(len(n.children)==16 for n in veg.children))
        self.assertTrue(all(len(q.children)==16 for n in veg.children for q in n.children))
        self.assertTrue(all(g.kind=='Vegetation' for n in veg.children for q in n.children for g in q.children))

    def test_proxy_indices_reference_parent_records(self):
        a=Group('a','Cluster',(0,0,0),2,[brush(10)],brush(20))
        b=Group('b','Vegetation',(20,0,0),3,[brush(11)],brush(21))
        tree,data,report=serialize(hierarchy([a,b]))
        payload=records(data[int(tree.get('DataOffset'))+4:int(tree.get('DataOffset'))+int(tree.get('DataSize'))])
        self.assertEqual(payload,[brush(20),brush(21)])
        for node,g in zip(tree,[a,b]):
            self.assertEqual(payload[int(node.get('ProxyIndex'))],g.proxy)
            offset=int(node.get('DataOffset'))
            self.assertEqual(records(data[offset+4:offset+int(node.get('DataSize'))]),g.records)
        self.assertEqual(report['proxies'],2)

    def test_hierarchy_contains_child_spheres_and_preserves_records(self):
        import math
        leaves=[Group(str(i),'Cluster',(i*15,0,0),10,[brush(i)]) for i in range(100)]
        root=hierarchy(leaves,fanout=4)
        def verify(g):
            for c in g.children:
                self.assertLessEqual(math.dist(c.center,g.center)+c.radius,g.radius+1e-9);verify(c)
        verify(root)
        tree,data,_=serialize(root)
        self.assertCountEqual(read_groups(tree,data),[brush(i) for i in range(100)])

    def test_rejects_duplicate_names_and_invalid_proxy_records(self):
        with self.assertRaisesRegex(ValueError,'Duplicate'):
            serialize(hierarchy([Group('same','Cluster',(0,0,0),1),Group('same','Cluster',(1,0,0),1)]))
        with self.assertRaisesRegex(ValueError,'Proxy'):
            serialize(hierarchy([Group('a','Cluster',(0,0,0),1,proxy=b'bad')]))

if __name__=='__main__':unittest.main()
