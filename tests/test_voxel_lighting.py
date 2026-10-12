"""Voxel format checks: source corruption and lossless opacity semantics."""
from pathlib import Path
import struct
import sys
import unittest
import zlib

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'tools'))
from voxel_lighting import opacity_block, convert_tile, validate_pair, inflate


class VoxelTests(unittest.TestCase):
    def source(self):
        raw = bytes([1, 1, 1, 1, 0, 0, 0, 1])+bytes(8)+bytes([0xf0, 0x8f])
        packed = struct.pack('<I', len(raw))+zlib.compress(raw)
        node = struct.pack('<I', len(packed))+packed
        node += bytes((-len(node)) % 4)
        root = struct.pack('<I', 0)+struct.pack('<II', 68, len(node))+bytes(56)
        return root+node

    def test_opacity_expansion_and_spatial_extent(self):
        idx, vox = convert_tile(self.source(), (128, 128, 128))
        self.assertEqual(validate_pair(idx, vox), {'nodes': 2, 'blocks': 1, 'channel_masks': [1]})
        child = struct.unpack_from('<8I', idx, 36)
        self.assertEqual(child[:4], (0, 0, 0, 128))
        raw = zlib.decompress(vox[child[6]+4:])
        self.assertEqual(raw[:8], bytes([16,16,16,0,0,0,0,0]))
        self.assertEqual(raw[20:24], bytes([0, 225, 225, 64]))
        self.assertEqual(raw[24:], bytes(16**3*4-4))
        self.assertEqual(struct.unpack_from('<I', raw, 16)[0], 64)

    def test_reject_cycle(self):
        blob = bytearray(self.source())
        struct.pack_into('<II', blob, 4, 0, 68)
        with self.assertRaises(ValueError):
            convert_tile(blob, (128, 128, 128))

    def test_reject_trailing_or_truncated_records(self):
        for blob in [self.source()+b'x', self.source()[:-1]]:
            with self.assertRaises(ValueError):
                convert_tile(blob, (128, 128, 128))

    def test_reject_advanced_or_multilayer_source(self):
        for layers, subsets in [(2, 1), (1, 3)]:
            with self.assertRaises(ValueError):
                opacity_block(bytes([1, 1, 1, layers, 0, 0, 0, subsets])+bytes(10))

    def test_reject_payload_offset_corruption(self):
        idx, vox = convert_tile(self.source(), (128, 128, 128))
        bad = bytearray(idx)
        struct.pack_into('<I', bad, 36+24, 5)
        with self.assertRaises(ValueError):
            validate_pair(bad, vox)

    def test_only_selected_world_layers_contribute(self):
        header = bytes([1, 1, 1, 3, 0, 0, 0, 1])+bytes(4)
        raw = header+struct.pack('<I', 0)+bytes([0x01, 0x10])
        raw += struct.pack('<I', 718)+bytes([0x20, 0x02])
        raw += struct.pack('<I', 999)+bytes([0xff, 0xff])
        result = opacity_block(raw, {0, 718})
        self.assertEqual(result[20:24], bytes([1, 4, 4, 1]))
        self.assertNotIn(225, result[20:])

    def test_crop_expansion_preserves_xyz_and_empty_cells(self):
        raw = bytes([2,1,1,1,3,5,7,1])+bytes(8)+bytes([0xf0,0x8f,0x12,0x34])
        result = opacity_block(raw)
        offset = 20+4*(7*16*16+5*16+3)
        self.assertEqual(result[offset:offset+8], bytes([0,225,225,64,4,1,16,9]))
        self.assertFalse(any(result[20:offset]))
        self.assertFalse(any(result[offset+8:]))

    def test_reject_inflate_size_and_trailing_data(self):
        for expected, suffix in [(1, b''), (3, b''), (2, b'bad')]:
            with self.assertRaises(ValueError):
                inflate(zlib.compress(b'ab')+suffix, expected)


if __name__ == '__main__':
    unittest.main()
