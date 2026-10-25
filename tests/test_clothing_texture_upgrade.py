"""Saved-package clothing texture re-encoding: families across shards, idempotency, archive replacement."""
import io
import os
import struct
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
import clothing_texture_upgrade as upgrade_module
import texture_encode
from npc_effects import write_float_dds
from texture_streaming import checked_entries, complete_rgba_mips, generated_entries, split_generated

PREFIX = 'objects/characters/gluetravel/gm_person_' + 'a' * 32 + '/'


def fake_bc7(rgba, fmt):
    """A structurally valid BC7 DDS (mips to 4x4, rc's CExtCEnd tail) carrying a digest of the input."""
    height, width = rgba.shape[:2]
    count = min(width, height).bit_length() - 2
    sizes = [max(1, (width >> i) // 4) * max(1, (height >> i) // 4) * 16 for i in range(count)]
    header = bytearray(148)
    header[:4] = b'DDS '
    struct.pack_into('<7I', header, 4, 124, 0x2100F, height, width, 0, 0, count)
    struct.pack_into('<2I4s', header, 76, 32, 4, b'DX10')
    struct.pack_into('<I', header, 108, 0x401008)
    struct.pack_into('<5I', header, 128, fmt, 3, 0, 1, 0)
    seed = np.frombuffer(rgba.tobytes()[:4096], np.uint8)
    body = np.resize(seed, sum(sizes)).tobytes()
    return bytes(header) + body + b'CExtCEnd'


def fake_colour(pixels, rc=None):
    return fake_bc7(texture_encode.colour_bytes(pixels), 99)


def fake_mask(rgba, rc=None):
    return fake_bc7(np.asarray(rgba, np.uint8), 98)


def float_family(size, seed):
    pixels = np.random.default_rng(seed).random((size, size, 4)).astype(np.float16)
    with tempfile.TemporaryDirectory() as t:
        path = Path(t) / 'f.dds'; write_float_dds(path, pixels); blob = path.read_bytes()
    return pixels, split_generated(blob)


def mask_family(size, seed):
    rgba = (np.random.default_rng(seed).random((size, size, 4)) * 255).astype(np.uint8)
    buffer = io.BytesIO(); Image.fromarray(rgba, 'RGBA').save(buffer, 'DDS')
    return rgba, split_generated(complete_rgba_mips(buffer.getvalue()))


def write_shard(path, entries):
    with zipfile.ZipFile(path, 'x', zipfile.ZIP_STORED, allowZip64=False) as archive:
        for name, data in entries:
            item = zipfile.ZipInfo(name, (2026, 1, 1, 0, 0, 0)); item.create_system = 0
            archive.writestr(item, data)


def members(paths):
    result = {}
    for path in paths:
        with zipfile.ZipFile(path) as archive:
            for info in archive.infolist(): result[info.filename] = (path.name, archive.read(info))
    return result


class Helpers(unittest.TestCase):
    def test_join_family_restores_the_file_split_generated_cut(self):
        _, family = float_family(64, 1)
        with tempfile.TemporaryDirectory() as t:
            path = Path(t) / 'f.dds'; write_float_dds(path, np.random.default_rng(1).random((64, 64, 4)).astype(np.float16))
            whole = path.read_bytes()
        joined = upgrade_module.join_family(family[''], {k: v for k, v in family.items() if k})
        self.assertEqual(joined[148:], whole[148:148 + len(joined) - 148])
        with self.assertRaisesRegex(ValueError, 'Incomplete'):
            upgrade_module.join_family(family[''], {'.2': family['.2']})

    def test_classify_float_mask_and_converted_bases(self):
        _, colour = float_family(64, 2)
        _, mask = mask_family(64, 3)
        self.assertEqual(upgrade_module.classify(colour['']), 'colour')
        self.assertEqual(upgrade_module.classify(mask['']), 'mask')
        self.assertIsNone(upgrade_module.classify(fake_bc7(np.zeros((64, 64, 4), np.uint8), 99)))
        self.assertIsNone(upgrade_module.classify(b'not a texture'))

    def test_archive_groups_keep_each_actor_and_the_container_set_together(self):
        with tempfile.TemporaryDirectory() as t:
            data = Path(t) / 'Data'; data.mkdir()
            for name in ('gm_person_ab.pak', 'gm_person_ab_01.pak', 'gm_person_cd.pak',
                         'gluemapper_containers_00.pak', 'gluemapper_containers_01.pak', 'gluemappertravel.pak'):
                (data / name).write_bytes(b'')
            groups = upgrade_module.archive_groups(t)
        self.assertEqual({k: [p.name for p in v] for k, v in groups.items()},
                         {'gm_person_ab': ['gm_person_ab.pak', 'gm_person_ab_01.pak'], 'gm_person_cd': ['gm_person_cd.pak'],
                          'gluemapper_containers': ['gluemapper_containers_00.pak', 'gluemapper_containers_01.pak']})


@patch.object(texture_encode, 'encode_colour', fake_colour)
@patch.object(texture_encode, 'encode_mask', fake_mask)
@patch.dict(os.environ, {texture_encode.SETTING: 'bc7'})
class Migration(unittest.TestCase):
    def package(self, root):
        data = root / 'Data'; data.mkdir(parents=True)
        self.diff, diff = float_family(512, 4)
        self.mask, bgs = mask_family(512, 5)
        _, spec = float_family(1024, 6)
        _, small = float_family(32, 7)
        entries = [(PREFIX + 'body.skin', b'skin'), (PREFIX + 'clothes.mtl', b'<Material/>')]
        for stem, family in (('native_a_0_diff.dds', diff), ('native_a_0_bgs.dds', bgs),
                             ('native_a_0_spec.dds', spec), ('native_b_0_diff.dds', small)):
            entries += [(PREFIX + stem + k, v) for k, v in sorted(family.items())]
        entries.sort()
        # The family of native_a_0_bgs crosses the shard boundary, as the actor writer allows.
        cut = next(i for i, (n, _) in enumerate(entries) if n.endswith('_bgs.dds.3'))
        shards = [data / ('gm_person_' + 'a' * 32 + '.pak'), data / ('gm_person_' + 'a' * 32 + '_01.pak')]
        write_shard(shards[0], entries[:cut]); write_shard(shards[1], entries[cut:])
        unrelated = data / 'gluemappertravel.pak'; write_shard(unrelated, [('Libs/x.xml', b'x')])
        return shards, unrelated

    def test_float_and_mask_families_are_reencoded_across_shards_and_validated(self):
        with tempfile.TemporaryDirectory() as t:
            root = Path(t) / 'package'
            shards, unrelated = self.package(root)
            before = members(shards)
            travel = unrelated.read_bytes()
            keep = Path(t) / 'linked.pak'; os.link(shards[1], keep)
            with patch.object(upgrade_module, '_mod_tools_rc', return_value='rc.exe'):
                files, report = upgrade_module.upgrade(root, None, workers=1)
            self.assertEqual(sorted(files), sorted('Data/' + p.name for p in shards))
            self.assertEqual(report['converted'], dict(colour=2, mask=1))
            self.assertEqual(report['skipped_small'], 1)
            self.assertLess(report['bytes_after'], report['bytes_before'])
            after = members(shards)
            list(checked_entries((n, d) for n, (_, d) in after.items()))
            # Unrelated members and the tiny placeholder bake are untouched.
            for name in (PREFIX + 'body.skin', PREFIX + 'clothes.mtl', PREFIX + 'native_b_0_diff.dds'):
                self.assertEqual(after[name], before[name])
            self.assertEqual(unrelated.read_bytes(), travel)
            # Each converted family is exactly what the archive writers emit for the encoded texture.
            expected = dict(generated_entries([(PREFIX + 'native_a_0_spec.dds', fake_colour(
                np.zeros((1024, 1024, 4))))]))
            spec = {n: d for n, (_, d) in after.items() if n.startswith(PREFIX + 'native_a_0_spec.dds')}
            self.assertEqual(sorted(spec), sorted(expected))
            self.assertEqual({n: len(d) for n, d in spec.items()}, {n: len(d) for n, d in expected.items()})
            self.assertEqual(struct.unpack_from('<I', after[PREFIX + 'native_a_0_diff.dds'][1], 128)[0], 99)
            self.assertEqual(struct.unpack_from('<I', after[PREFIX + 'native_a_0_bgs.dds'][1], 128)[0], 98)
            # The previous archive file was replaced, not rewritten in place.
            self.assertNotEqual(keep.read_bytes(), shards[1].read_bytes())
            self.assertEqual({n: d for n, (_, d) in members([keep]).items()},
                             {n: d for n, (s, d) in before.items() if s == shards[1].name})
            self.assertFalse(list((root / 'Data').glob('*pending*')))
            # A second run finds nothing to convert and never needs the compiler.
            with patch.object(upgrade_module, '_mod_tools_rc', side_effect=AssertionError('rc used')):
                again, second = upgrade_module.upgrade(root, None, workers=1)
            self.assertEqual(again, {})
            self.assertEqual(second['converted'], dict(colour=0, mask=0))
            self.assertEqual(second['already_compressed'], 3)

    def test_float_setting_leaves_saved_packages_alone(self):
        with tempfile.TemporaryDirectory() as t, patch.dict(os.environ, {texture_encode.SETTING: 'float'}):
            root = Path(t) / 'package'
            shards, _ = self.package(root)
            before = members(shards)
            files, report = upgrade_module.upgrade(root, None, workers=1)
            self.assertEqual((files, report['mode']), ({}, 'float'))
            self.assertEqual(members(shards), before)

    def test_a_failed_encode_leaves_every_archive_unchanged(self):
        def broken(pixels, rc=None): raise ValueError('rc failed')
        with tempfile.TemporaryDirectory() as t, patch.object(texture_encode, 'encode_colour', broken), \
                patch.object(upgrade_module, '_mod_tools_rc', return_value='rc.exe'):
            root = Path(t) / 'package'
            shards, _ = self.package(root)
            before = [p.read_bytes() for p in shards]
            with self.assertRaisesRegex(ValueError, 'rc failed'):
                upgrade_module.upgrade(root, None, workers=1)
            self.assertEqual([p.read_bytes() for p in shards], before)
            self.assertFalse(list((root / 'Data').glob('*pending*')))
            self.assertEqual(sorted(p.name for p in Path(t).iterdir()), ['package'])  # work folder removed


class Finalize(unittest.TestCase):
    def test_receipt_records_conversions_and_keeps_the_first_stamp_when_nothing_changes(self):
        from setup_package_upgrade import upgrade_clothing_textures
        receipt = dict(files={'Data/a.pak': 'old'})
        report = dict(version=1, mode='bc7', converted=dict(colour=3, mask=1))
        with patch.object(upgrade_module, 'upgrade', return_value=({'Data/a.pak': 'new'}, report)):
            upgrade_clothing_textures('p', receipt, None, None, None)
        self.assertEqual(receipt['files'], {'Data/a.pak': 'new'})
        self.assertEqual(receipt[upgrade_module.RECEIPT_KEY], report)
        with patch.object(upgrade_module, 'upgrade', return_value=({}, dict(report, converted=dict(colour=0, mask=0)))):
            upgrade_clothing_textures('p', receipt, None, None, None)
        self.assertEqual(receipt[upgrade_module.RECEIPT_KEY], report)
