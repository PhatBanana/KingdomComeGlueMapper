"""Clothing texture storage setting, sRGB packing and the rc.exe encoder (skipped without mod tools)."""
import io
import os
import struct
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
import texture_encode
from npc_effects import write_float_dds


def available_rc():
    try:
        return texture_encode.rc_executable()
    except ValueError:
        return None


def decode(blob):
    """Pillow decodes BC7 under the UNORM enum; return the stored bytes / 255 and the format."""
    data = bytearray(blob)
    fmt = struct.unpack_from('<I', data, 128)[0]
    struct.pack_into('<I', data, 128, {99: 98}.get(fmt, fmt))
    image = Image.open(io.BytesIO(bytes(data)))
    image.load()
    return np.asarray(image.convert('RGBA')).astype(np.float64) / 255, fmt


class Setting(unittest.TestCase):
    def test_default_is_bc7_and_float_remains_selectable(self):
        with patch.dict(os.environ, {texture_encode.SETTING: ''}):
            self.assertEqual(texture_encode.mode(), 'bc7')
        with patch.dict(os.environ, {texture_encode.SETTING: ' Float '}):
            self.assertEqual(texture_encode.mode(), 'float')
        with patch.dict(os.environ, {texture_encode.SETTING: 'bc3'}):
            with self.assertRaisesRegex(ValueError, texture_encode.SETTING):
                texture_encode.mode()

    def test_only_power_of_two_textures_of_useful_size_are_compressed(self):
        self.assertTrue(texture_encode.encodable(64, 2048))
        self.assertFalse(texture_encode.encodable(4, 4))        # uniform fallbacks stay as they were
        self.assertFalse(texture_encode.encodable(96, 128))     # rc presets require powers of two

    def test_missing_mod_tools_name_the_fallback_setting(self):
        with tempfile.TemporaryDirectory() as t, self.assertRaisesRegex(ValueError, 'GLUEMAPPER_CLOTHING_TEXTURES=float'):
            texture_encode.rc_executable(t)
        with tempfile.TemporaryDirectory() as t:
            rc = Path(t) / 'Tools/rc/rc.exe'; rc.parent.mkdir(parents=True); rc.write_bytes(b'')
            self.assertEqual(texture_encode.rc_executable(t), rc.resolve())
            with patch.dict(os.environ, {'KCD2_MOD_TOOLS': t}):
                self.assertEqual(texture_encode.rc_executable(), rc.resolve())


class SrgbPacking(unittest.TestCase):
    def test_srgb_bytes_return_the_float_value_after_gpu_decode(self):
        codes = np.arange(256)
        linear = texture_encode.srgb_decode(codes / 255)
        pixels = np.stack([linear, linear, linear, codes / 255], -1)[None]
        packed = texture_encode.colour_bytes(pixels)
        np.testing.assert_array_equal(packed[0, :, 0], codes)
        np.testing.assert_array_equal(packed[0, :, 3], codes)    # alpha is not colour-managed

    def test_dark_values_keep_more_precision_than_plain_bytes(self):
        v = np.linspace(0, .05, 1000) ** 1                         # dark macro values (rgb**2.2)
        shown = v ** (1 / 2.2)
        srgb = texture_encode.srgb_decode(np.round(texture_encode.srgb_encode(v) * 255) / 255) ** (1 / 2.2)
        plain = (np.round(v * 255) / 255) ** (1 / 2.2)
        self.assertLess(np.abs(srgb - shown).max(), np.abs(plain - shown).max() / 2)
        visible = v > .002                                         # above the deepest blacks
        self.assertLess(np.abs(srgb - shown)[visible].max() * 255, 2)
        self.assertGreater(np.abs(plain - shown)[visible].max() * 255, 4)

    def test_size_cap_matches_the_float_writers_first_level(self):
        pixels = np.random.default_rng(5).random((32, 64, 4)).astype(np.float16)
        with tempfile.TemporaryDirectory() as t:
            path = Path(t) / 'f.dds'; write_float_dds(path, pixels, max_size=16)
            data = path.read_bytes()
        height, width = struct.unpack_from('<II', data, 12)
        expected = np.frombuffer(data, '<f2', height * width * 4, 148).reshape(height, width, 4)
        np.testing.assert_array_equal(texture_encode.capped(pixels, 16).astype(np.float16), expected)


class Writers(unittest.TestCase):
    def test_float_mode_writes_the_previous_formats_byte_for_byte(self):
        pixels = np.random.default_rng(1).random((64, 64, 4)).astype(np.float16)
        mask = Image.fromarray((np.random.default_rng(2).random((64, 64, 4)) * 255).astype(np.uint8), 'RGBA')
        with tempfile.TemporaryDirectory() as t, patch.dict(os.environ, {texture_encode.SETTING: 'float'}), \
                patch.object(texture_encode, 'rc_executable', side_effect=AssertionError('rc used')):
            root = Path(t)
            texture_encode.write_colour_dds(root / 'a.dds', pixels); write_float_dds(root / 'b.dds', pixels)
            self.assertEqual((root / 'a.dds').read_bytes(), (root / 'b.dds').read_bytes())
            texture_encode.write_mask_dds(root / 'a_bgs.dds', mask); mask.save(root / 'b_bgs.dds')
            self.assertEqual((root / 'a_bgs.dds').read_bytes(), (root / 'b_bgs.dds').read_bytes())

    def test_placeholder_sized_textures_never_need_the_compiler(self):
        with tempfile.TemporaryDirectory() as t, patch.dict(os.environ, {texture_encode.SETTING: 'bc7'}), \
                patch.object(texture_encode, 'rc_executable', side_effect=AssertionError('rc used')):
            root = Path(t)
            texture_encode.write_colour_dds(root / 'c.dds', np.ones((4, 4, 4), np.float16))
            texture_encode.write_mask_dds(root / 'm.dds', Image.new('RGBA', (4, 4), (0, 0, 0, 255)))
            self.assertEqual((root / 'c.dds').read_bytes()[84:88], b'DX10')

    def test_bc7_mode_encodes_the_capped_srgb_bytes(self):
        seen = []
        def compile_rgba8(rgba, preset, formats, rc=None):
            seen.append((rgba.shape, preset, formats)); return b'encoded'
        pixels = np.full((256, 128, 4), .25, np.float16)
        with tempfile.TemporaryDirectory() as t, patch.dict(os.environ, {texture_encode.SETTING: 'bc7'}), \
                patch.object(texture_encode, 'compile_rgba8', compile_rgba8):
            texture_encode.write_colour_dds(Path(t) / 'c.dds', pixels, max_size=128)
            texture_encode.write_mask_dds(Path(t) / 'm_bgs.dds', Image.new('RGBA', (64, 64)))
            self.assertEqual((Path(t) / 'c.dds').read_bytes(), b'encoded')
        self.assertEqual(seen[0], ((128, 64, 4), texture_encode.COLOUR_PRESET, texture_encode.COLOUR_DXGI))
        self.assertEqual(seen[1], ((64, 64, 4), texture_encode.MASK_PRESET, texture_encode.MASK_DXGI))


@unittest.skipUnless(available_rc(), 'KCD2 Modding Tools (rc.exe) not installed')
class ResourceCompiler(unittest.TestCase):
    def test_colour_is_bc7_with_full_mips_and_preserves_the_linear_values(self):
        from texture_streaming import layout, split_generated
        y, x = np.mgrid[0:128, 0:128] / 127
        pixels = np.stack([x * .02, y * .5, (x + y) / 2, np.where(x > .5, 1., 0.)], -1)
        blob = texture_encode.encode_colour(pixels)
        info = layout(blob)
        self.assertEqual((info['width'], info['height'], len(info['sizes'])), (128, 128, 6))
        stored, fmt = decode(blob)
        self.assertIn(fmt, texture_encode.COLOUR_DXGI)
        linear = texture_encode.srgb_decode(stored[..., :3]) if fmt == 99 else stored[..., :3]
        shown_error = np.abs(linear ** (1 / 2.2) - pixels[..., :3] ** (1 / 2.2)) * 255
        self.assertLess(np.percentile(shown_error, 99), 6)
        np.testing.assert_allclose(stored[..., 3], pixels[..., 3], atol=2 / 255)
        self.assertEqual(sorted(split_generated(blob)), ['', '.1', '.2'])

    def test_mask_is_linear_bc7(self):
        rgba = np.zeros((64, 64, 4), np.uint8); rgba[..., 0] = np.arange(64)[None] * 4; rgba[..., 2] = 192; rgba[..., 3] = 255
        stored, fmt = decode(texture_encode.encode_mask(rgba))
        self.assertEqual(fmt, 98)
        self.assertLess(np.abs(stored * 255 - rgba).max(), 4)

    def test_compiler_runs_in_parallel_workers(self):
        from concurrent.futures import ProcessPoolExecutor
        rgba = [np.full((64, 64, 4), i * 40, np.uint8) for i in range(4)]
        with ProcessPoolExecutor(2) as pool:
            blobs = list(pool.map(texture_encode.encode_mask, rgba))
        self.assertEqual(len({b for b in blobs}), 4)
