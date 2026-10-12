from pathlib import Path
import struct
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from brush_registration import repair_hlods


class BrushRegistrationTests(unittest.TestCase):
    def test_only_legacy_flag_on_imported_brush_changes(self):
        records = []
        for mesh in (0, 1):
            b = bytearray(104)
            struct.pack_into('<I', b, 0, 1)
            struct.pack_into('<Q', b, 32, 0x80180040100408)
            struct.pack_into('<H', b, 40, mesh)
            struct.pack_into('<12f', b, 44, 1,0,0,796,0,1,0,3478,0,0,1,50)
            records.append(b)
        data = struct.pack('<II', 2, 208) + b''.join(records)
        meshes = ['gluebuild/setup_buildings/mesh997.cgf', 'objects/native.cgf']
        fixed, report = repair_hlods(data, meshes)
        self.assertEqual(len(report), 1)
        self.assertEqual([i for i,(a,b) in enumerate(zip(data,fixed)) if a != b], [42])
        self.assertEqual(struct.unpack_from('<Q', fixed, 40)[0], 0x80180040000408)
        again, report = repair_hlods(fixed, meshes)
        self.assertEqual(again, fixed)
        self.assertEqual(report, [])

    def test_invalid_mesh_reference_is_rejected(self):
        b = bytearray(104)
        struct.pack_into('<I', b, 0, 1)
        with self.assertRaisesRegex(ValueError, 'resource table'):
            repair_hlods(struct.pack('<II', 2, 104) + b, [])
