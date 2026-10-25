from pathlib import Path
import json
import struct
import sys
import tempfile
import unittest
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'tools'))
from compiled_terrain import parse
from road_view_distance import convert, kcd1_distance, target_byte
from terrain_object_tree import read_tree
from test_lod_ratio_metadata import fixture

MATERIALS = ['materials/terrain/roads/native_road', 'gluelandscape/setup_roads/m4']


def road(box, view, material):
    row = bytearray(112)  # header only: no vertices, indices, tangents or spline points
    struct.pack_into('<I6f', row, 0, 11, *box)
    row[42], row[43] = view, 100
    struct.pack_into('<i', row, 108, material)
    return bytes(row)


def terrain(*records):
    blob, _ = fixture()
    old = parse(blob)
    table = old.tables['materials']['offset'] - 4
    if struct.unpack_from('<I', blob, table)[0] != 0:
        raise AssertionError('Fixture layout changed')
    materials = struct.pack('<I', len(MATERIALS)) + b''.join(p.encode().ljust(256, b'\0') for p in MATERIALS)
    payload = b''.join(records)
    out = bytearray(blob[:table] + materials + blob[table+4:old.tree_offset]
                    + struct.pack('<HBB6fI', 8, 0, 0, 0, 0, 0, 4096, 4096, 4096, len(payload)) + payload)
    struct.pack_into('<I', out, 4, len(out))
    return bytes(out)


def view_bytes(data):
    _, nodes = read_tree(parse(data))
    return sorted((struct.unpack_from('<i', b, 108)[0], b[42]) for n in nodes for k, b in n.records if k == 11)


class RoadViewDistanceTests(unittest.TestCase):
    def test_kcd1_distance_scales_with_road_size(self):
        # 30-40-0 box: diagonal 50 m, radius 25 m. KCD1: 25 * 100 * 0.2 = 500 m.
        self.assertAlmostEqual(kcd1_distance(road((0, 0, 5, 30, 40, 5), 20, 1)), 500.0, places=3)
        self.assertAlmostEqual(kcd1_distance(road((0, 0, 0, 6, 8, 0), 10, 1)), 50.0, places=3)

    def test_target_reproduces_kcd1_distance_within_native_cap(self):
        # 50 m in KCD1 needs ceil(50 / 110 * 100) = 46 under KCD2's flat 110 ratio.
        self.assertEqual(target_byte(road((0, 0, 0, 6, 8, 0), 10, 1)), 46)
        self.assertEqual(target_byte(road((0, 0, 5, 30, 40, 5), 20, 1)), 100)  # capped at native
        self.assertEqual(target_byte(road((0, 0, 0, 0.6, 0.8, 0), 20, 1)), 20)  # never shortened
        self.assertEqual(target_byte(road((0, 0, 0, 6, 8, 0), 255, 1)), 255)   # special 100x byte
        self.assertEqual(target_byte(road((0, 0, 0, 6, 8, 0), 120, 1)), 120)
        with self.assertRaises(ValueError):
            kcd1_distance(road((0, 0, 0, 1, 1, 1), 20, 1)[:100])

    def test_only_imported_roads_change(self):
        data = terrain(road((10, 10, 0, 16, 18, 0), 10, 0), road((10, 10, 0, 16, 18, 0), 10, 1),
                       road((20, 20, 0, 26, 28, 0), 10, -1))
        output, report = convert(parse(data))
        self.assertEqual(view_bytes(output), [(-1, 46), (0, 10), (1, 46)])
        self.assertEqual((report['roads'], report['imported'], report['changed']), (3, 2, 2))
        self.assertEqual(len(output), len(data))
        with self.assertRaises(ValueError):
            convert(parse(terrain(road((0, 0, 0, 1, 1, 1), 10, 7))))

    def test_package_upgrade_rewrites_once_including_previously_placed_packages(self):
        from terrain_surface_placement import MARKER, convert as place_surfaces, upgrade_package
        source = terrain(road((10, 10, 0, 16, 18, 0), 10, 1))
        placed, old_report = place_surfaces(source)  # a package placed before this migration
        for initial, marker in [(source, None), (placed, old_report)]:
            with tempfile.TemporaryDirectory() as folder:
                package = Path(folder)
                level = package/'Data/Levels/kcd1_travel'
                level.mkdir(parents=True)
                with zipfile.ZipFile(level/'terrain.pak', 'w') as z:
                    z.writestr('terrain/terrain.dat', initial)
                    if marker:
                        z.writestr(MARKER, json.dumps(marker))
                files, report = upgrade_package(package)
                self.assertEqual(report['roads']['changed'], 1)
                with zipfile.ZipFile(level/'terrain.pak') as z:
                    upgraded = z.read('terrain/terrain.dat')
                self.assertEqual(view_bytes(upgraded), [(1, 46)])
                again = upgrade_package(package)[1]
                self.assertTrue(again['already_current'])
                with zipfile.ZipFile(level/'terrain.pak') as z:
                    self.assertEqual(z.read('terrain/terrain.dat'), upgraded)


if __name__ == '__main__':
    unittest.main()
