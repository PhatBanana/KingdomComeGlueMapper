"""Clothing texture storage setting, sRGB packing, encoder choice and the texconv/rc encoders (skipped when absent)."""
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
    def test_default_is_float_and_bc7_is_opt_in(self):
        with patch.dict(os.environ, {texture_encode.SETTING: ''}):
            self.assertEqual(texture_encode.mode(), 'float')
        with patch.dict(os.environ, {texture_encode.SETTING: ' BC7 '}):
            self.assertEqual(texture_encode.mode(), 'bc7')
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
            # Bake pools pass reserved paths without a suffix; the bytes must not depend on the name.
            texture_encode.write_mask_dds(root / 'reserved', Image.new('RGBA', (4, 4), (0, 0, 0, 255)))
            self.assertEqual((root / 'reserved').read_bytes(), (root / 'm.dds').read_bytes())

    def test_bc7_mode_encodes_the_capped_srgb_bytes(self):
        seen = []
        def compile_rgba8(rgba, preset, formats, rc=None):
            seen.append((rgba.shape, preset, formats)); return b'encoded'
        pixels = np.full((256, 128, 4), .25, np.float16)
        with tempfile.TemporaryDirectory() as t, patch.dict(os.environ, {texture_encode.SETTING: 'bc7'}), \
                patch.object(texture_encode, 'encoder', return_value=('rc', 'rc.exe')), \
                patch.object(texture_encode, 'compile_rgba8', compile_rgba8):
            texture_encode.write_colour_dds(Path(t) / 'c.dds', pixels, max_size=128)
            texture_encode.write_mask_dds(Path(t) / 'm_bgs.dds', Image.new('RGBA', (64, 64)))
            self.assertEqual((Path(t) / 'c.dds').read_bytes(), b'encoded')
        self.assertEqual(seen[0], ((128, 64, 4), texture_encode.COLOUR_PRESET, texture_encode.COLOUR_DXGI))
        self.assertEqual(seen[1], ((64, 64, 4), texture_encode.MASK_PRESET, texture_encode.MASK_DXGI))

    def test_texconv_gets_the_float_writers_chain_as_srgb_bytes_to_the_4x4_tail(self):
        seen = []
        def compile_texconv(levels, srgb, executable):
            seen.append((levels, srgb)); return b'encoded'
        pixels = np.random.default_rng(4).random((64, 128, 4)).astype(np.float16)
        mask = (np.random.default_rng(5).random((64, 64, 4)) * 255).astype(np.uint8)
        with patch.object(texture_encode, 'compile_texconv', compile_texconv):
            texture_encode.encode_colour(pixels, ('texconv', 'texconv.exe'))
            texture_encode.encode_mask(mask, ('texconv', 'texconv.exe'))
        colour, srgb = seen[0]
        self.assertTrue(srgb)
        self.assertEqual([l.shape[:2] for l in colour], [(64, 128), (32, 64), (16, 32), (8, 16), (4, 8)])
        with tempfile.TemporaryDirectory() as t:
            path = Path(t) / 'f.dds'; write_float_dds(path, pixels); data = path.read_bytes()
        level1 = np.frombuffer(data, '<f2', 32 * 64 * 4, 148 + 64 * 128 * 8).reshape(32, 64, 4)
        np.testing.assert_array_equal(colour[1], texture_encode.colour_bytes(level1))
        levels, srgb = seen[1]
        self.assertFalse(srgb)
        self.assertEqual(len(levels), 5)
        np.testing.assert_array_equal(levels[0], mask)
        # Same box filter as the RGBA8 masks' completed chain.
        from texture_streaming import complete_rgba_mips
        buffer = io.BytesIO(); Image.fromarray(mask, 'RGBA').save(buffer, 'DDS')
        full = complete_rgba_mips(buffer.getvalue())
        tail = sum(4 * (64 >> i) ** 2 for i in range(1, 7))
        level = full[len(full) - tail:len(full) - tail + 32 * 32 * 4]
        stored = np.asarray(Image.frombytes('RGBA', (32, 32), level))  # Pillow stores BGRA
        np.testing.assert_array_equal(stored[..., [2, 1, 0, 3]], levels[1])


class EncoderChoice(unittest.TestCase):
    def test_auto_prefers_texconv_and_overrides_are_explicit(self):
        with tempfile.TemporaryDirectory() as t:
            exe = Path(t) / 'texconv.exe'; exe.write_bytes(b'')
            rc = Path(t) / 'Tools/rc/rc.exe'; rc.parent.mkdir(parents=True); rc.write_bytes(b'')
            env = {texture_encode.TEXCONV_SETTING: str(exe), 'KCD2_MOD_TOOLS': t, texture_encode.ENCODER_SETTING: ''}
            with patch.dict(os.environ, env):
                self.assertEqual(texture_encode.encoder(), ('texconv', str(exe.resolve())))
            with patch.dict(os.environ, dict(env, GLUEMAPPER_TEXTURE_ENCODER='rc')):
                self.assertEqual(texture_encode.encoder(), ('rc', str(rc.resolve())))
            with patch.dict(os.environ, dict(env, GLUEMAPPER_TEXTURE_ENCODER='nvtt')):
                with self.assertRaisesRegex(ValueError, 'GLUEMAPPER_TEXTURE_ENCODER'):
                    texture_encode.encoder()
            with patch.dict(os.environ, dict(env, GLUEMAPPER_TEXCONV=str(Path(t) / 'missing.exe'))):
                with self.assertRaisesRegex(ValueError, 'GLUEMAPPER_TEXCONV'):
                    texture_encode.encoder()
            with patch.dict(os.environ, dict(env, GLUEMAPPER_TEXTURE_ENCODER='texconv')), \
                    patch.object(texture_encode, 'texconv_executable', return_value=None):
                with self.assertRaisesRegex(ValueError, 'texconv.exe not found'):
                    texture_encode.encoder()
            with patch.dict(os.environ, env), patch.object(texture_encode, 'texconv_executable', return_value=None):
                self.assertEqual(texture_encode.encoder()[0], 'rc')        # auto falls back

    def test_rc_is_found_beside_the_game_in_another_steam_library(self):
        with tempfile.TemporaryDirectory() as t:
            game = Path(t) / 'SteamLibrary/steamapps/common/KingdomComeDeliverance2'; game.mkdir(parents=True)
            rc = game.parent / 'KCD2Mod/Tools/rc/rc.exe'; rc.parent.mkdir(parents=True); rc.write_bytes(b'')
            texture_encode._discovered_rc.cache_clear()
            try:
                with patch('steam_installations.discover', return_value=({'kcd2': [str(game)], 'mod_tools': []}, [])):
                    self.assertEqual(texture_encode._discovered_rc(), rc.resolve())
            finally:
                texture_encode._discovered_rc.cache_clear()


def gradient():
    y, x = np.mgrid[0:128, 0:128] / 127
    return np.stack([x * .02, y * .5, (x + y) / 2, np.where(x > .5, 1., 0.)], -1)


def available_texconv():
    try:
        return texture_encode.texconv_executable()
    except ValueError:
        return None


class RealEncoder:
    tool = None

    def test_colour_is_bc7_with_full_mips_and_preserves_the_linear_values(self):
        from texture_streaming import layout, split_generated, validate_family
        pixels = gradient()
        blob = texture_encode.encode_colour(pixels, self.tool)
        info = layout(blob)
        self.assertEqual((info['width'], info['height'], len(info['sizes'])), (128, 128, 6))
        self.assertTrue(blob.endswith(b'CExtCEnd'))
        stored, fmt = decode(blob)
        self.assertIn(fmt, texture_encode.COLOUR_DXGI)
        linear = texture_encode.srgb_decode(stored[..., :3]) if fmt == 99 else stored[..., :3]
        shown_error = np.abs(linear ** (1 / 2.2) - pixels[..., :3] ** (1 / 2.2)) * 255
        self.assertLess(np.percentile(shown_error, 99), 6)
        np.testing.assert_allclose(stored[..., 3], pixels[..., 3], atol=2 / 255)
        family = split_generated(blob)
        self.assertEqual(sorted(family), ['', '.1', '.2'])
        validate_family(family[''], {k: v for k, v in family.items() if k})

    def test_mask_is_linear_bc7_without_colour_conversion(self):
        rgba = np.zeros((64, 64, 4), np.uint8); rgba[..., 0] = np.arange(64)[None] * 4; rgba[..., 2] = 192; rgba[..., 3] = 255
        blob = texture_encode.encode_mask(rgba, self.tool)
        stored, fmt = decode(blob)
        self.assertEqual(fmt, 98)
        self.assertEqual(struct.unpack_from('<I', blob, 36)[0], 0)
        self.assertLess(np.abs(stored * 255 - rgba).max(), 4)

    def test_encoder_runs_in_parallel_workers(self):
        import functools
        from concurrent.futures import ProcessPoolExecutor
        rgba = [np.full((64, 64, 4), i * 40, np.uint8) for i in range(4)]
        with ProcessPoolExecutor(2) as pool:
            blobs = list(pool.map(functools.partial(texture_encode.encode_mask, tool=self.tool), rgba))
        self.assertEqual(len(set(blobs)), 4)


@unittest.skipUnless(available_rc(), 'KCD2 Modding Tools (rc.exe) not installed')
class ResourceCompiler(RealEncoder, unittest.TestCase):
    tool = ('rc', str(available_rc()))


@unittest.skipUnless(available_texconv(), 'texconv.exe not found (set GLUEMAPPER_TEXCONV)')
class Texconv(RealEncoder, unittest.TestCase):
    tool = ('texconv', str(available_texconv()))

    def test_stored_colour_bytes_are_the_srgb_input_unconverted(self):
        levels = [np.full((64 >> i, 64 >> i, 4), (37, 90, 201, 255), np.uint8) for i in range(5)]
        blob = texture_encode.compile_texconv(levels, True, self.tool[1])
        stored, fmt = decode(blob)
        self.assertEqual((fmt, struct.unpack_from('<I', blob, 36)[0]), (99, texture_encode.SRGB_READ))
        np.testing.assert_array_equal(np.round(stored[0, 0] * 255), (37, 90, 201, 255))


@unittest.skipUnless(available_rc() and available_texconv(), 'needs both rc.exe and texconv.exe')
class EncodersAgree(unittest.TestCase):
    def test_texconv_writes_rcs_header_and_layout(self):
        pixels = gradient()
        a = texture_encode.encode_colour(pixels, ('rc', str(available_rc())))
        b = texture_encode.encode_colour(pixels, ('texconv', str(available_texconv())))
        self.assertEqual(len(a), len(b))
        self.assertEqual(a[:40] + a[44:148], b[:40] + b[44:148])
        self.assertAlmostEqual(struct.unpack_from('<f', a, 40)[0], struct.unpack_from('<f', b, 40)[0], places=4)


def reference_colour_levels(pixels):
    """The previous, Pillow-based chain (commit 5a31ffa); the fast chain must match it byte for byte."""
    level = np.asarray(pixels, dtype=np.float16).astype(np.float32)
    levels = [level]
    for _ in range(texture_encode.mip_count(level.shape[1], level.shape[0]) - 1):
        h, w = max(1, level.shape[0] // 2), max(1, level.shape[1] // 2)
        level = np.stack([np.asarray(Image.fromarray(np.ascontiguousarray(level[..., c])).resize(
            (w, h), Image.Resampling.BOX)) for c in range(4)], axis=-1).astype(np.float16).astype(np.float32)
        levels.append(level)
    return [texture_encode.colour_bytes(level) for level in levels]


class FastChain(unittest.TestCase):
    def test_vectorized_chain_is_byte_identical_to_the_pillow_chain(self):
        rng = np.random.default_rng(11)
        cases = [rng.random((256, 512, 4)), rng.random((128, 64, 4)) * 1.4 - .2,
                 rng.random((64, 64, 4)) ** 6, np.full((64, 128, 4), .5)]
        for pixels in cases:
            pixels = pixels.astype(np.float16)
            new, old = texture_encode.colour_levels(pixels), reference_colour_levels(pixels)
            self.assertEqual(len(new), len(old))
            for a, b in zip(new, old):
                np.testing.assert_array_equal(a, b)


class BatchStaging(unittest.TestCase):
    def test_staging_only_when_texconv_will_encode(self):
        with tempfile.TemporaryDirectory() as t:
            exe = Path(t) / 'texconv.exe'; exe.write_bytes(b'')
            for env, expected in (({}, True), ({texture_encode.SETTING: 'float'}, False),
                                  ({texture_encode.ENCODER_SETTING: 'rc'}, False)):
                batches = texture_encode.Batches()
                with patch.dict(os.environ, {texture_encode.TEXCONV_SETTING: str(exe), texture_encode.SETTING: 'bc7',
                                             texture_encode.ENCODER_SETTING: '', **env}):
                    staging = batches.staging()
                self.assertEqual(staging is not None, expected, env)
                if staging: self.assertTrue(Path(staging.directory).is_dir())
                batches.finish()
                if staging: self.assertFalse(Path(staging.directory).exists())
            batches = texture_encode.Batches()
            with patch.object(texture_encode, 'texconv_executable', return_value=None):
                self.assertIsNone(batches.staging())        # rc fallback: workers write directly

    def test_batches_flush_by_size_and_finish_writes_everything(self):
        calls = []
        def encode(jobs, executable, write=True):
            calls.append(len(jobs))
            for job in jobs: Path(job.target).write_bytes(b'encoded')
        with tempfile.TemporaryDirectory() as t, patch.object(texture_encode, 'encode_staged', encode), \
                patch.object(texture_encode, 'texconv_executable', return_value=Path('texconv.exe')), patch.object(texture_encode, '_tool_identity', return_value='fake'), \
                patch.dict(os.environ, {texture_encode.SETTING: 'bc7', texture_encode.ENCODER_SETTING: ''}):
            batches = texture_encode.Batches(batch=3)
            staging = batches.staging()
            levels = [np.zeros((64 >> i, 64 >> i, 4), np.uint8) for i in range(5)]
            for i in range(7):
                batches.add(texture_encode.stage(levels, True, Path(t) / f'{i}.dds', staging))
            batches.add(None)                                  # a texture the worker wrote itself
            batches.finish()
            self.assertEqual(sorted(calls), [1, 3, 3])
            self.assertEqual(sorted(p.name for p in Path(t).glob('*.dds')), [f'{i}.dds' for i in range(7)])
            self.assertFalse(Path(staging.directory).exists())

    def test_abort_discards_staged_work(self):
        with patch.object(texture_encode, 'texconv_executable', return_value=Path('texconv.exe')), patch.object(texture_encode, '_tool_identity', return_value='fake'), \
                patch.dict(os.environ, {texture_encode.SETTING: 'bc7', texture_encode.ENCODER_SETTING: ''}):
            batches = texture_encode.Batches()
            staging = batches.staging()
            batches.add(texture_encode.stage([np.zeros((64, 64, 4), np.uint8)], False, 'x.dds', staging))
            batches.abort()
            self.assertFalse(Path(staging.directory).exists())


@unittest.skipUnless(available_texconv(), 'texconv.exe not found (set GLUEMAPPER_TEXCONV)')
class TexconvBatches(unittest.TestCase):
    def test_a_batch_equals_single_encodes_and_failures_name_the_texture(self):
        rng = np.random.default_rng(3)
        exe = str(available_texconv())
        colour = [texture_encode.colour_levels(rng.random((128, 64, 4)).astype(np.float16)) for _ in range(3)]
        mask = texture_encode.mask_levels((rng.random((64, 64, 4)) * 255).astype(np.uint8))
        singles = [texture_encode.compile_texconv(l, True, exe) for l in colour]
        singles.append(texture_encode.compile_texconv(mask, False, exe))
        with tempfile.TemporaryDirectory() as t:
            staging = Path(t) / 'staging'; staging.mkdir()
            jobs = [texture_encode.stage(l, True, Path(t) / f'c{i}.dds', staging) for i, l in enumerate(colour)]
            jobs.append(texture_encode.stage(mask, False, Path(t) / 'm.dds', staging))
            runs = []
            original = texture_encode._texconv_batch
            def counted(batch, *args):
                runs.append(len(batch)); return original(batch, *args)
            with patch.object(texture_encode, '_texconv_batch', counted):
                texture_encode.encode_staged(jobs, exe)
            self.assertEqual(sorted(runs), [1, 3])               # one run per colour space
            self.assertEqual([(Path(t) / n).read_bytes() for n in ('c0.dds', 'c1.dds', 'c2.dds', 'm.dds')], singles)
            self.assertEqual(list(staging.iterdir()), [])        # inputs removed
            # A failing batch is retried texture by texture; the broken one is named.
            jobs = [texture_encode.stage(l, True, Path(t) / f'r{i}.dds', staging) for i, l in enumerate(colour)]
            Path(jobs[1].source).write_bytes(b'not a texture')
            with self.assertRaisesRegex(ValueError, 'r1.dds'):
                texture_encode.encode_staged(jobs, exe)
            self.assertEqual((Path(t) / 'r0.dds').read_bytes(), singles[0])


class EncodeCache(unittest.TestCase):
    def fake_batch(self, runs):
        from texture_streaming import layout
        def run(jobs, executable, srgb, output):
            runs.append(len(jobs))
            for job in jobs:
                _, _, _, width, height, count = job[:6]
                header = texture_encode.cry_header(width, height, count, 99 if srgb else 98, 0)
                body = bytes(sum(layout(header)['sizes'])) + Path(job.source).read_bytes()[148:164]
                Path(output, Path(job.source).name).write_bytes(header + body[:sum(layout(header)['sizes'])])
        return run

    def test_identical_inputs_are_encoded_once_and_reused_from_the_cache(self):
        rng = np.random.default_rng(9)
        a = texture_encode.colour_levels(rng.random((64, 64, 4)).astype(np.float16))
        b = texture_encode.colour_levels(rng.random((64, 64, 4)).astype(np.float16))
        runs = []
        with tempfile.TemporaryDirectory() as t, patch.object(texture_encode, '_texconv_batch', self.fake_batch(runs)):
            root = Path(t); (root / 'in').mkdir(); cache = root / 'cache'
            staging = texture_encode.Staging((str(root / 'in'), str(cache), 'texconv:one'))
            jobs = [texture_encode.stage(l, True, root / name, staging) for l, name in ((a, 'p1.dds'), (b, 'p2.dds'), (a, 'p3.dds'))]
            self.assertEqual(jobs[0].key, jobs[2].key)
            self.assertNotEqual(jobs[0].key, jobs[1].key)
            texture_encode.encode_staged(jobs, 'texconv.exe')
            self.assertEqual(runs, [2])                                    # the duplicate was not encoded
            self.assertEqual((root / 'p1.dds').read_bytes(), (root / 'p3.dds').read_bytes())
            self.assertEqual(list((root / 'in').iterdir()), [])
            # Another person (or build) with the same garment: written from the cache, nothing staged.
            self.assertIsNone(texture_encode.stage(a, True, root / 'p4.dds', staging))
            self.assertEqual((root / 'p4.dds').read_bytes(), (root / 'p1.dds').read_bytes())
            self.assertEqual(list((root / 'in').iterdir()), [])
            # A different encoder build, or a damaged entry, is a miss.
            other = texture_encode.Staging((str(root / 'in'), str(cache), 'texconv:two'))
            self.assertIsNotNone(texture_encode.stage(a, True, root / 'p5.dds', other))
            entry = texture_encode._cached(cache, jobs[1].key); entry.write_bytes(entry.read_bytes()[:-100])
            self.assertIsNotNone(texture_encode.stage(b, True, root / 'p6.dds', staging))

    def test_workspace_cache_unless_rebuilding(self):
        with tempfile.TemporaryDirectory() as t:
            with patch.dict(os.environ, {'GLUEMAPPER_BUILD_CACHE': t, 'GLUEMAPPER_REBUILD_CACHE': '0'}):
                self.assertEqual(texture_encode.encode_cache(), Path(t) / 'bc7-textures')
            with patch.dict(os.environ, {'GLUEMAPPER_BUILD_CACHE': t, 'GLUEMAPPER_REBUILD_CACHE': '1'}):
                self.assertNotEqual(texture_encode.encode_cache(), Path(t) / 'bc7-textures')


    def test_a_retargeted_copy_is_written_from_its_twin_in_one_batch_or_from_the_cache_in_a_later_one(self):
        a = texture_encode.colour_levels(np.random.default_rng(4).random((64, 64, 4)).astype(np.float16))
        runs = []
        with tempfile.TemporaryDirectory() as t, patch.object(texture_encode, '_texconv_batch', self.fake_batch(runs)):
            root = Path(t); (root / 'in').mkdir(); cache = root / 'cache'
            staging = texture_encode.Staging((str(root / 'in'), str(cache), 'texconv:one'))
            first = texture_encode.stage(a, True, root / 'one.dds', staging)
            twin = first.retarget(root / 'two.dds')
            self.assertEqual((twin.source, twin.key), (first.source, first.key))
            texture_encode.encode_staged([first, twin], 'texconv.exe')
            self.assertEqual(runs, [1])
            self.assertEqual((root / 'one.dds').read_bytes(), (root / 'two.dds').read_bytes())
            self.assertEqual(list((root / 'in').iterdir()), [])
            # The input is gone once an earlier batch encoded it; the copy comes from the cache.
            later = first.retarget(root / 'three.dds')
            texture_encode.encode_staged([later], 'texconv.exe')
            self.assertEqual(runs, [1])
            self.assertEqual((root / 'three.dds').read_bytes(), (root / 'one.dds').read_bytes())
            gone = first.retarget(root / 'four.dds')
            texture_encode._cached(cache, first.key).unlink()
            with self.assertRaisesRegex(ValueError, 'four.dds'):
                texture_encode.encode_staged([gone], 'texconv.exe')
