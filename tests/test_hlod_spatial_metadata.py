from pathlib import Path
import struct
import sys
import tempfile
import unittest
from unittest.mock import patch
import xml.etree.ElementTree as ET
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from hlod_spatial_metadata import normalize, upgrade_package
from spatial_hlod import Group, serialize, world_hierarchy


def vegetation(x, y, z=80):
    data = bytearray(64)
    # Deliberately asymmetric canopy: it must not decide the owning grid cell.
    struct.pack_into('<I6f', data, 0, 2, x-10, y-5, z, x+100, y+10, z+25)
    struct.pack_into('<4f', data, 44, x, y, z, 1)
    return bytes(data)


def proxy():
    data = bytearray(104)
    struct.pack_into('<I', data, 0, 1)
    return bytes(data)


def fixture():
    leaves = [Group('source_123', 'Vegetation', (90, 40, 999), 450,
                    [vegetation(66, 40)], proxy())]
    return serialize(world_hierarchy(leaves))[:2]


def height(x, y):
    return x * .02 + y * .01


class HlodSpatialMetadataTests(unittest.TestCase):
    def test_native_grid_uses_instance_cell_and_terrain_not_canopy_or_fixed_z(self):
        tree, data = fixture()
        before = ET.tostring(tree)
        changed, report = normalize(tree, data, height)
        self.assertEqual(ET.tostring(tree), before)  # caller's tree unmodified
        self.assertEqual(report['changed_nodes'], 4)
        nodes = [n for n in changed.iter('HLod') if n.get('Type') == 'Vegetation']
        expected = [(2048, 2048, 8000), (512, 512, 1024/2**.5),
                    (128, 128, 256/2**.5), (96, 32, 64/2**.5)]
        for node, (x, y, radius) in zip(nodes, expected):
            for actual, expected_value in zip(map(float, node.get('Pos').split(',')), (x, y, height(x,y))):
                self.assertAlmostEqual(actual, expected_value, places=6)
            self.assertAlmostEqual(float(node.get('Radius')), radius, places=5)

    def test_only_pos_and_radius_change_including_native_coarse_proxy_links(self):
        root = world_hierarchy([Group('leaf', 'Vegetation', (90,40,999),450,
                                      [vegetation(66,40)],proxy())])
        region = root.children[1].children[0]
        region.proxy = proxy()
        region.children[0].proxy = proxy()
        tree, data, _ = serialize(root)
        changed, _ = normalize(tree, data, height)
        for old, new in zip(tree.iter(), changed.iter()):
            allowed = {'Pos','Radius'} if old.get('Type') == 'Vegetation' else set()
            self.assertEqual({k:v for k,v in old.attrib.items() if k not in allowed},
                             {k:v for k,v in new.attrib.items() if k not in allowed})
        again, report = normalize(changed, data, height, validate_only=True)
        self.assertEqual(report['changed_nodes'], 0)
        self.assertEqual(ET.tostring(changed), ET.tostring(again))

    def test_setup_validator_rejects_old_metadata(self):
        with self.assertRaisesRegex(ValueError, 'Incorrect vegetation grid metadata'):
            normalize(*fixture(), height, validate_only=True)

    def test_fresh_builder_assigns_cells_by_instance_origins_not_source_switch_center(self):
        leaves = [Group('source_a', 'Vegetation', (3000,3000,999), 500,
                        [vegetation(65,40)], proxy())]
        tree, data, _ = serialize(world_hierarchy(leaves, height=height))
        _, report = normalize(tree, data, height, validate_only=True)
        self.assertEqual(report['changed_nodes'], 0)
        leaf = next(n for n in tree.iter() if n.get('Name') == 'source_a')
        self.assertEqual(leaf.get('Pos'), '96,32,2.24')

    def test_multi_cell_proxy_membership_is_rejected_not_silently_reassigned(self):
        leaf = Group('bad', 'Vegetation', (32,32,0), 500,
                     [vegetation(30,30), vegetation(300,30)], proxy())
        tree, data, _ = serialize(world_hierarchy([leaf]))
        with self.assertRaisesRegex(ValueError, 'crosses 64m cells'):
            normalize(tree, data, height)

    def test_invalid_height_and_duplicate_cells_fail_without_mutation(self):
        tree, data = fixture()
        with self.assertRaisesRegex(ValueError, 'Non-finite terrain height'):
            normalize(tree, data, lambda x,y: float('nan'))
        leaves = [Group(str(i), 'Vegetation', (32,32,0), 100,
                        [vegetation(30+i,30)], proxy()) for i in range(2)]
        tree, data, _ = serialize(world_hierarchy(leaves))
        with self.assertRaisesRegex(ValueError, 'Duplicate'):
            normalize(tree, data, height)

    def test_targeted_migration_preserves_every_other_member_and_is_idempotent(self):
        tree, data = fixture()
        with tempfile.TemporaryDirectory() as directory:
            package = Path(directory)
            level = package/'Data/Levels/kcd1_travel'
            level.mkdir(parents=True)
            entries = {'terrain/hlods.xml': ET.tostring(tree), 'terrain/hlods.dat':data,
                       'objects_mission0.xml':b'quest entities', 'lighting.bin':b'lighting'}
            with zipfile.ZipFile(level/'level.pak', 'w') as z:
                for name,payload in entries.items(): z.writestr(name,payload)
            with zipfile.ZipFile(level/'terrain.pak', 'w') as z:
                z.writestr('terrain/terrain.dat', b'heightfield fixture')
            terrain = (level/'terrain.pak').read_bytes()
            with patch('region_travel_ground.Heightfield', return_value=height):
                files, report = upgrade_package(package)
                self.assertEqual(report['changed_nodes'], 4)
                self.assertEqual(list(files), ['Data/Levels/kcd1_travel/level.pak'])
                first = (level/'level.pak').read_bytes()
                files, report = upgrade_package(package)
                self.assertEqual(files,{})
                self.assertEqual(report['changed_nodes'],0)
            self.assertEqual((level/'level.pak').read_bytes(),first)
            self.assertEqual((level/'terrain.pak').read_bytes(),terrain)
            with zipfile.ZipFile(level/'level.pak') as z:
                for name,payload in entries.items():
                    if name != 'terrain/hlods.xml': self.assertEqual(z.read(name),payload)


if __name__ == '__main__':
    unittest.main()
