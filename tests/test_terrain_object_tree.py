from pathlib import Path
import struct
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'tools'))
from terrain_object_tree import (destination, maximum_view_distance, place, read_tree,
                                 child_box, DEFAULT_POLICY)
from terrain_surface_placement import convert, upgrade_package, MARKER
from compiled_terrain import parse
from test_lod_ratio_metadata import fixture


ROOT = (0., 0., 0., 4096., 4096., 4096.)


def decal(box=(31., 31., 31., 33., 33., 33.), ratio=100):
    row = bytearray(120)
    struct.pack_into('<I6f', row, 0, 7, *box)
    row[42] = ratio
    struct.pack_into('<9f', row, 72, 1,0,0,0,1,0,0,0,1)
    struct.pack_into('<f', row, 108, 1)
    return bytes(row)


def tree(payload=b'', box=ROOT):
    return SimpleNamespace(data=struct.pack('<HBB6fI',8,0,0,*box,len(payload))+payload,
                           tree_offset=0,version=29)


def terrain(payload):
    blob, _ = fixture()
    old = parse(blob)
    result = bytearray(blob[:old.tree_offset] + tree(payload).data)
    struct.pack_into('<I', result, 4, len(result))
    return bytes(result)


class ObjectTreeTests(unittest.TestCase):
    def test_crossing_bounds_uses_centre_and_creates_missing_children(self):
        record = decal()
        out = place(tree(), [record])
        root, nodes = read_tree(SimpleNamespace(data=out, tree_offset=0))
        owning = [n for n in nodes if n.records]
        self.assertEqual(len(owning), 1)
        self.assertEqual(owning[0].box, (0,0,0,32,32,32))
        self.assertEqual(owning[0].records, [(7,record)])
        self.assertGreater(len(nodes), 1)
        self.assertFalse(root.records)

    def test_equality_selects_low_octant_and_axis_bits_match_kcd2(self):
        tiny = (2048.,)*6
        self.assertEqual(destination(ROOT,tiny,0)[0],0)
        for point, bit in [((3000,1,1),4),((1,3000,1),2),((1,1,3000),1)]:
            self.assertEqual(destination(ROOT,point+point,0)[0],bit)

    def test_stopping_rules_use_size_distance_minimum_and_root_centre(self):
        self.assertEqual(len(destination(ROOT,(1,1,1,1,1,1),0)),9)
        self.assertEqual(destination(ROOT,(1,1,1,600,600,600),0),())
        self.assertEqual(destination(ROOT,(1,1,1,1,1,1),1e9),())
        self.assertEqual(destination(ROOT,(-2,0,0,-1,1,1),0),())
        # Full containment is deliberately not required even at the root.
        self.assertTrue(destination(ROOT,(-1,1,1,3,2,2),0))

    def test_special_view_byte_is_not_nonlinear_lod_or_linear_255_percent(self):
        self.assertEqual(maximum_view_distance(decal(ratio=100)),45)
        self.assertEqual(maximum_view_distance(decal(ratio=255)),4500)
        self.assertEqual(maximum_view_distance(decal(ratio=0)),5)
        self.assertLess(len(destination(ROOT,(31,31,31,33,33,33),4500)),
                        len(destination(ROOT,(31,31,31,33,33,33),45)))

    def test_existing_merged_records_preserved_and_relocation_idempotent(self):
        merged = struct.pack('<I',23)+bytes(68)
        original = terrain(merged+decal()+decal((1023,1023,10,1025,1025,12)))
        output, report = convert(original)
        self.assertEqual(report['before']['root_records'],3)
        self.assertEqual(report['after']['root_records'],1)
        parsed = parse(output)
        root, _ = read_tree(parsed)
        self.assertEqual(root.records,[(23,merged)])
        self.assertEqual(original[8:parse(original).tree_offset],output[8:parsed.tree_offset])
        self.assertEqual(convert(output)[0],output)

    def test_invalid_records_and_child_geometry_fail_closed(self):
        for record in [decal()[:-1], decal()+decal(), struct.pack('<I',99)+bytes(116),
                       decal((4,0,0,1,1,1)),decal((float('nan'),0,0,1,1,1))]:
            with self.assertRaises(ValueError):place(tree(),[record])
        bad = bytearray(tree().data);bad[2]=1
        bad.extend(tree(box=(0,0,0,64,64,64)).data)
        with self.assertRaisesRegex(ValueError,'octant'):
            place(SimpleNamespace(data=bad,tree_offset=0),[decal()])

    def test_package_upgrade_preserves_bake_and_is_atomic_for_linked_source(self):
        import os
        from setup_package_upgrade import rewrite
        with tempfile.TemporaryDirectory() as folder:
            package = Path(folder)/'private'
            level = package/'Data/Levels/kcd1_travel';level.mkdir(parents=True)
            source = Path(folder)/'source.pak'
            with zipfile.ZipFile(source,'w') as z:
                z.writestr('terrain/terrain.dat',terrain(decal()))
                z.writestr('terrain/lighting.svo',b'cached lighting')
            original = source.read_bytes()
            os.link(source,level/'terrain.pak')
            files, report = upgrade_package(package)
            self.assertEqual(list(files),['Data/Levels/kcd1_travel/terrain.pak'])
            self.assertEqual(source.read_bytes(),original)
            saved = (level/'terrain.pak').read_bytes()
            self.assertTrue(upgrade_package(package)[1]['already_current'])
            self.assertEqual((level/'terrain.pak').read_bytes(),saved)
            with zipfile.ZipFile(level/'terrain.pak') as z:
                self.assertEqual(z.read('terrain/lighting.svo'),b'cached lighting')
                self.assertIn(MARKER,z.namelist())
            rewrite(package,'Data/Levels/kcd1_travel/terrain.pak',{'terrain/terrain.dat':terrain(decal())})
            with self.assertRaisesRegex(ValueError,'marker'):
                upgrade_package(package)


if __name__ == '__main__':
    unittest.main()
