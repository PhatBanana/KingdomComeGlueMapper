import sys
import struct
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'tools'))
from clothing_regions import Chunk, read_chunks, write_chunks
from static_lod_transforms import align_external_lod


def fixture(z, bounds=(-9, 6, 2, -2, 14, 19), name=b'tower'):
    node = bytearray(204); node[:len(name)] = name
    struct.pack_into('<4i', node, 64, 1, -1, 0, 0)
    struct.pack_into('<16f', node, 84, 1,0,0,0,0,1,0,0,0,0,1,0,0,0,z,0)
    mesh = bytearray(264); struct.pack_into('<6f', mesh, 108, *bounds)
    return write_chunks([Chunk(0x1000,0x801,1,bytes(mesh)),
                         Chunk(0x100b,0x824,2,bytes(node)),
                         Chunk(0x1016,0x800,3,b'geometry unchanged')], {})


class StaticLodTransformsTests(unittest.TestCase):
    def test_displaced_root_aligns_without_changing_geometry(self):
        base, lod = fixture(0), fixture(4177)
        result, report = align_external_lod(base,lod)
        self.assertEqual(report['new_translation'],[0,0,0])
        self.assertEqual(result,base)
        self.assertEqual(align_external_lod(base,result),(result,None))

    def test_unproven_relationships_are_preserved(self):
        base=fixture(0)
        for lod in (fixture(2), fixture(4177,name=b'other'),
                    fixture(4177,bounds=(-9,6,42,-2,14,59))):
            self.assertEqual(align_external_lod(base,lod),(lod,None))


if __name__ == '__main__': unittest.main()
