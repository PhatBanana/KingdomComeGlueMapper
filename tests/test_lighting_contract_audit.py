"""Reject malformed clipping dependencies rather than guessing containment."""
from pathlib import Path
import struct
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'tools'))
from audit_lighting_contract import bsp_contains, clip_geometry


class LightingContractAuditTests(unittest.TestCase):
    def test_bsp_terminal_sides_and_border(self):
        nodes = [(1, 0, 0, -2, -1, -1)]
        self.assertTrue(bsp_contains(nodes, (1, 0, 0)))
        self.assertFalse(bsp_contains(nodes, (3, 0, 0)))
        self.assertFalse(bsp_contains(nodes, (2, 0, 0)))

    def test_bsp_cycle_is_not_an_interior_match(self):
        with self.assertRaisesRegex(ValueError, 'Cyclic'):
            bsp_contains([(1, 0, 0, 0, 0, -1)], (1, 0, 0))

    def test_clip_chunk_cannot_point_outside_archive_member(self):
        blob = b'CrChF\x07\0\0' + struct.pack('<II', 1, 16)
        blob += struct.pack('<HHIII', 0x3009, 1, 1, 128, 32)
        with self.assertRaisesRegex(ValueError, 'exceeds file'):
            clip_geometry(blob)


if __name__ == '__main__':
    unittest.main()
