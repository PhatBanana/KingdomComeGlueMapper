"""Asset-free checks for baking KCD1 runtime terrain alignment into KCD2 tilt bytes."""
import hashlib
import json
import math
from pathlib import Path
import struct
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import zipfile
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from vegetation import convert_instance
from vegetation_tilt import (HeightField, MARKER, bake, source_tilts, target_up, tilt_bytes,
                             up_vectors, upgrade_package)

# One byte step is 1/255 turn; rounding both axes stays within one step overall.
QUANTUM = 360 / 255


def slope(degrees):
    h = HeightField.__new__(HeightField)
    h.heights = np.broadcast_to(np.arange(4097)[:, None] * math.tan(math.radians(degrees)), (4097, 4097))
    return h


def angle(a, b):
    return np.degrees(np.arccos(np.clip((np.asarray(a) * np.asarray(b)).sum(-1), -1, 1)))


def group(path, alignment):
    row = bytearray(360)
    row[:256] = path.encode().ljust(256, b'\0')
    struct.pack_into('<f', row, 280, alignment)
    struct.pack_into('<f', row, 324, 1.0)
    return bytes(row)


def source_record(group_index, pos, yaw, x, y):
    b = bytearray(64)
    struct.pack_into('<I6fHbbI HBB4f4B I', b, 0, 2, 1, 2, 3, 4, 5, 6, 19, 0, 0, 0x40000c08,
                     group_index, 100, 100, *pos, 1.0, 133, yaw, x, y, 0xdeadbeef)
    return bytes(b)


def terrain(groups):
    """Smallest parseable converted terrain: header, group table and empty sectors."""
    header = bytearray(32)
    struct.pack_into('<4BIIfII', header, 0, 29, 0, 6, 0, 0, 4096, 1, 64, 64)
    blob = header + struct.pack('<I', len(groups)) + b''.join(groups) + struct.pack('<I', 0) + struct.pack('<I', 0)
    blob += (struct.pack('<hh8fii', 8, 0, *([0.0] * 8), 0, 0) + bytes(24)) * 5461
    blob += struct.pack('<HBB6fI', 8, 0, 0, 0, 0, 0, 4096, 4096, 4096, 0)
    struct.pack_into('<I', blob, 4, len(blob))
    return bytes(blob)


def hlods(records):
    payload = b''.join(records)
    return struct.pack('<II', 2, len(payload)) + payload


GROUPS = [group('glueveg/log.cgf', 1.0), group('glueveg/tree.cgf', 0.0),
          group('glueveg/rock.cgf', 0.5), group('objects/native/rock.cgf', 1.0)]


def converted(group_index, pos, yaw, x, y):
    return convert_instance(source_record(group_index, pos, yaw, x, y), 0, group_index)


class TiltTests(unittest.TestCase):
    def test_flat_ground_keeps_upright_bytes_for_every_coefficient(self):
        normals = slope(0).normal(np.array([[100.5, 200.5, 0.0]] * 3))
        for coefficient in (1, .5, 0):
            x, y = tilt_bytes(normals, coefficient, [0, 77, 254])
            self.assertEqual((x.tolist(), y.tolist()), ([0, 0, 0], [0, 0, 0]))

    def test_twenty_degree_slope_matches_blended_normal_at_any_yaw(self):
        yaw = np.arange(0, 255, 5)
        normals = slope(20).normal(np.tile([[1000.0, 2000.0, 0]], (len(yaw), 1)))
        for coefficient, tilt in ((1, 20), (.5, None), (0, 0)):
            x, y = tilt_bytes(normals, coefficient, yaw)
            up = up_vectors(yaw, x, y)
            self.assertLessEqual(angle(up, target_up(normals, coefficient)).max(), QUANTUM)
            if tilt is not None:
                np.testing.assert_allclose(np.degrees(np.arccos(up[:, 2])), tilt, atol=QUANTUM)
        self.assertEqual(set(tilt_bytes(normals, 0, yaw)[0].tolist()), {0})

    def test_decode_round_trips_written_bytes_within_quantization(self):
        rng = np.random.default_rng(11)
        theta = np.radians(rng.uniform(0, 60, 2000)); phi = rng.uniform(0, 2 * np.pi, 2000)
        normals = np.stack((np.sin(theta) * np.cos(phi), np.sin(theta) * np.sin(phi), np.cos(theta)), 1)
        coefficient = rng.choice([1, .5, .2], 2000); yaw = rng.integers(0, 255, 2000)
        x, y = tilt_bytes(normals, coefficient, yaw)
        self.assertTrue(((x < 255) & (y < 255)).all())
        self.assertLessEqual(angle(up_vectors(yaw, x, y), target_up(normals, coefficient)).max(), QUANTUM)

    def test_invalid_normals_or_coefficients_are_rejected(self):
        for normals, coefficient in (([[0, 0, -1.]], 1), ([[0, 0, 1.]], 1.5), ([[np.nan, 0, 1.]], 1)):
            with self.assertRaises(ValueError):
                tilt_bytes(normals, coefficient, [0])

    def test_source_tilt_replaces_random_tumble_and_skips_unaligned_groups(self):
        data = b''.join(GROUPS) + source_record(0, (1000, 2000, 5), 40, 135, 233) \
            + source_record(1, (1000, 2010, 5), 40, 135, 233)
        source = SimpleNamespace(data=data, tables={'vegetation': {'offset': 0, 'paths': ['a', 'b', 'c', 'd']}})
        records = [dict(offset=1440, group=0, pos=[1000, 2000, 5]), dict(offset=1504, group=1, pos=[1000, 2010, 5])]
        tilts = source_tilts(source, records, slope(20))
        self.assertEqual(set(tilts), {1440})
        aligned = convert_instance(data, 1440, 0, tilts[1440])
        self.assertNotEqual(aligned[62:64], bytes([135, 233]))
        self.assertEqual(aligned[44:62], data[1440 + 40:1440 + 58])
        up = up_vectors(aligned[61], aligned[62], aligned[63])
        self.assertLessEqual(angle(up, slope(20).normal(np.array([[1000., 2000, 5]]))[0]), QUANTUM)
        untouched = convert_instance(data, 1504, 1, tilts.get(1504))
        self.assertEqual(untouched[60:64], bytes([133, 40, 135, 233]))
        for invalid in ((1,), (255, 0), (1.0, 2)):
            with self.assertRaises(ValueError):
                convert_instance(data, 1440, 0, invalid)

    def test_hlod_bake_scopes_aligned_imported_groups_and_is_idempotent(self):
        from lod_ratio_metadata import imported
        blob = terrain(GROUPS)
        rows = [converted(0, (1000, 2000, 5), 9, 0, 0), converted(1, (1000, 2000, 5), 9, 0, 0),
                converted(2, (1000, 2000, 5), 9, 135, 233), converted(3, (1000, 2000, 5), 9, 0, 0)]
        data = hlods([struct.pack('<I', 1) + bytes(100)] + rows)
        baked, report = bake(blob, data, imported, slope(20))
        self.assertEqual((report['aligned_groups'], report['scoped'], report['changed'], report['replaced_off_normal']), (2, 2, 2, 1))
        records = [baked[8 + 104 + i * 64:8 + 104 + (i + 1) * 64] for i in range(4)]
        self.assertEqual(records[1], rows[1]); self.assertEqual(records[3], rows[3])
        self.assertEqual(baked[:8 + 104], data[:8 + 104])
        for record, original in zip(records[:3], rows[:3]):
            self.assertEqual(record[:62], original[:62])
        self.assertAlmostEqual(float(np.degrees(np.arccos(up_vectors(9, records[0][62], records[0][63])[2]))), 20, delta=QUANTUM)
        self.assertEqual(bake(blob, baked, imported, slope(20))[0], baked)
        self.assertEqual(bake(blob, data, lambda path: False)[0], data)  # no heightfield is needed

    def test_package_stage_refreshes_lod_receipt_and_resumes_without_rewrite(self):
        from lod_ratio_metadata import MARKER as LOD_MARKER, marker_for, validate_marker
        blob = terrain(GROUPS)
        data = hlods([converted(0, (1000, 2000, 5), 9, 0, 0), converted(1, (1000, 2000, 5), 9, 0, 0)])
        lod = marker_for(blob, data, dict(version=1, target_encoding='kcd2-piecewise-1-to-20', scoped={}))
        with tempfile.TemporaryDirectory() as directory:
            package = Path(directory); level = package / 'Data/Levels/kcd1_travel'; level.mkdir(parents=True)
            with zipfile.ZipFile(level / 'terrain.pak', 'w') as z: z.writestr('terrain/terrain.dat', blob)
            with zipfile.ZipFile(level / 'level.pak', 'w') as z:
                z.writestr('terrain/hlods.dat', data); z.writestr(LOD_MARKER, json.dumps(lod))
            with patch('vegetation_tilt.HeightField', return_value=slope(20)):
                files, report = upgrade_package(package)
                self.assertEqual(list(files), ['Data/Levels/kcd1_travel/level.pak'])
                self.assertEqual((report['scoped'], report['changed']), (1, 1))
                with zipfile.ZipFile(level / 'level.pak') as z:
                    baked = z.read('terrain/hlods.dat')
                    validate_marker(blob, baked, json.loads(z.read(LOD_MARKER)))
                    self.assertEqual(json.loads(z.read(MARKER))['hlods_sha256'], report['hlods_sha256'])
                self.assertNotEqual(baked, data); self.assertEqual(len(baked), len(data))
                before = (level / 'level.pak').read_bytes()
                files, report = upgrade_package(package)
                self.assertEqual(files, {}); self.assertTrue(report['already_current'])
                self.assertEqual((level / 'level.pak').read_bytes(), before)

    def test_package_stage_follows_a_later_hlod_rewrite(self):
        from lod_ratio_metadata import MARKER as LOD_MARKER, marker_for, validate_marker
        blob = terrain(GROUPS)
        data = hlods([converted(0, (1000, 2000, 5), 9, 0, 0), converted(1, (1000, 2000, 5), 9, 0, 0)])
        lod = marker_for(blob, data, dict(version=1, target_encoding='kcd2-piecewise-1-to-20', scoped={}))
        with tempfile.TemporaryDirectory() as directory:
            package = Path(directory); level = package / 'Data/Levels/kcd1_travel'; level.mkdir(parents=True)
            with zipfile.ZipFile(level / 'terrain.pak', 'w') as z: z.writestr('terrain/terrain.dat', blob)
            with zipfile.ZipFile(level / 'level.pak', 'w') as z:
                z.writestr('terrain/hlods.dat', data); z.writestr(LOD_MARKER, json.dumps(lod))
            with patch('vegetation_tilt.HeightField', return_value=slope(20)):
                files, report = upgrade_package(package)
                self.assertEqual((report['scoped'], report['changed'], report['already_baked']), (1, 1, 0))
                with zipfile.ZipFile(level / 'level.pak') as z:
                    baked = z.read('terrain/hlods.dat'); lod = json.loads(z.read(LOD_MARKER)); stale = z.read(MARKER)
                # A later finalize step (static gates, stocks) rewrites hlods.dat keeping the tilt bytes
                # and refreshes the LOD receipt, as every HLOD writer must; the tilt receipt goes stale.
                later = hlods([baked[8:72], baked[72:136], converted(1, (1500, 2500, 5), 3, 0, 0)])
                with zipfile.ZipFile(level / 'level.pak', 'w') as z:
                    z.writestr('terrain/hlods.dat', later); z.writestr(MARKER, stale)
                    z.writestr(LOD_MARKER, json.dumps(marker_for(blob, later, lod)))
                files, report = upgrade_package(package)
                self.assertEqual(list(files), ['Data/Levels/kcd1_travel/level.pak'])
                self.assertEqual((report['scoped'], report['changed'], report['already_baked']), (1, 0, 1))
                self.assertEqual(report['hlods_sha256'], hashlib.sha256(later).hexdigest())
                with zipfile.ZipFile(level / 'level.pak') as z:
                    self.assertEqual(z.read('terrain/hlods.dat'), later)
                    self.assertEqual(json.loads(z.read(MARKER)), report)
                    validate_marker(blob, later, json.loads(z.read(LOD_MARKER)))
                files, report = upgrade_package(package)
                self.assertEqual(files, {}); self.assertTrue(report['already_current'])

    def test_package_without_aligned_imported_vegetation_is_not_rewritten(self):
        with tempfile.TemporaryDirectory() as directory:
            package = Path(directory); level = package / 'Data/Levels/kcd1_travel'; level.mkdir(parents=True)
            with zipfile.ZipFile(level / 'terrain.pak', 'w') as z: z.writestr('terrain/terrain.dat', terrain(GROUPS))
            with zipfile.ZipFile(level / 'level.pak', 'w') as z:
                z.writestr('terrain/hlods.dat', hlods([converted(1, (1000, 2000, 5), 9, 0, 0)]))
            before = (level / 'level.pak').read_bytes()
            self.assertEqual(upgrade_package(package)[0], {})
            self.assertEqual((level / 'level.pak').read_bytes(), before)


if __name__ == '__main__':
    unittest.main()
