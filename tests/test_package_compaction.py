"""The finished package's uncompressed textures are deflated losslessly, once, like retail KCD2's."""
import json
import os
from pathlib import Path
import struct
import sys
import tempfile
import unittest
import zipfile

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
import package_compaction
from package_compaction import candidates, compact_archive, compact_package, eligible, uncompressed_textures
from setup_campaign import RECEIPT, digest

FLOAT, BC7 = 10, 98


def header(dxgi, size=256):
    head = bytearray(148); head[:4] = b'DDS '
    struct.pack_into('<7I', head, 4, 124, 0x1007, size, size, 0, 0, 1)
    struct.pack_into('<2I4s', head, 76, 32, 4, b'DX10')
    struct.pack_into('<5I', head, 128, dxgi, 3, 0, 1, 0)
    return bytes(head)


def bake(seed=1, size=256):
    """Half-float pixels like the clothing bakes: smooth colour, cut-out alpha."""
    rng = np.random.default_rng(seed)
    y, x = np.mgrid[0:size, 0:size] / size
    rgb = np.stack([0.02 + 0.01 * x, 0.015 + 0.01 * y, 0.01 + 0.005 * x * y], -1) ** 2.2
    alpha = (x > 0.2).astype(float)[..., None]
    return np.concatenate([rgb + rng.normal(0, 1e-4, rgb.shape), alpha], -1).astype(np.float16).tobytes()


def write_pak(path, members):
    with zipfile.ZipFile(path, 'x', zipfile.ZIP_STORED, allowZip64=False) as archive:
        for number, (name, data) in enumerate(members):
            info = zipfile.ZipInfo(name, (2026, 1, 1, 0, 0, number % 60))
            info.create_system = 0
            info.external_attr = 0x20
            archive.writestr(info, data)


def contents(path):
    with zipfile.ZipFile(path) as archive:
        return [(m.filename, m.date_time, m.external_attr, m.create_system, archive.read(m)) for m in archive.infolist()]


class PackageCompactionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.root = Path(self.tmp.name)
        self.package = self.root / 'map'; (self.package / 'Data/Levels/kcd1_travel').mkdir(parents=True)
        noise = np.random.default_rng(9).integers(0, 256, 200_000, dtype=np.uint8).tobytes()
        person = 'objects/characters/gm_person_1/'
        self.people = self.package / 'Data/gm_person_1.pak'
        write_pak(self.people, [
            (person + 'native_outfit_arms_0_diff.dds', header(FLOAT) + bake(1, 16)),
            (person + 'noise.dds', header(FLOAT) + noise),
            (person + 'boots.dds', header(BC7) + bytes(200_000)),     # block format: stays stored
            (person + 'body.skin', bake(4)),
            ('sounds/voice.ogg', bake(5)),
            ('hlods/world/tree.dds', header(FLOAT) + bake(6)),
        ])
        # The streamed pieces of a family can live in another shard than its base.
        self.shard = self.package / 'Data/gm_person_1_01.pak'
        write_pak(self.shard, [(person + 'native_outfit_arms_0_diff.dds.1', bake(2)),
                               (person + 'native_outfit_arms_0_diff.dds.1a', bake(3)),
                               (person + 'boots.dds.1', bytes(200_000))])
        self.lighting = self.package / 'Data/gluemapper_lighting_00.pak'
        write_pak(self.lighting, [('textures/cubemaps/kcd1_travel/probe.dds', header(FLOAT) + bake(7))])
        self.plain = self.package / 'Data/Levels/kcd1_travel/terrain.pak'
        write_pak(self.plain, [('terrain/terrain.dat', bake(8))])
        receipt = dict(files={p.relative_to(self.package).as_posix(): digest(p)
                              for p in self.package.rglob('*') if p.is_file()})
        (self.package / RECEIPT).write_text(json.dumps(receipt))
        self.uncompressed = uncompressed_textures(self.package)

    def tearDown(self):
        self.tmp.cleanup()

    def methods(self, path):
        with zipfile.ZipFile(path) as archive:
            return {m.filename.rsplit('/', 1)[-1]: m.compress_type for m in archive.infolist()}

    def test_only_stored_uncompressed_textures_outside_hlods_and_lighting_are_eligible(self):
        self.assertIn('objects/characters/gm_person_1/native_outfit_arms_0_diff.dds', self.uncompressed)
        self.assertNotIn('objects/characters/gm_person_1/boots.dds', self.uncompressed)
        self.assertEqual(sorted(candidates(self.package)), sorted([self.people, self.shard]))
        with zipfile.ZipFile(self.shard) as archive:
            picked = [m.filename.rsplit('/', 1)[-1] for m in archive.infolist() if eligible(self.shard.name, m, self.uncompressed)]
        self.assertEqual(picked, ['native_outfit_arms_0_diff.dds.1', 'native_outfit_arms_0_diff.dds.1a'])

    def test_members_come_back_identical_and_only_compressible_uncompressed_textures_are_deflated(self):
        for path, expected in ((self.people, {'native_outfit_arms_0_diff.dds': 8, 'noise.dds': 0, 'boots.dds': 0,
                                               'body.skin': 0, 'voice.ogg': 0, 'tree.dds': 0}),
                               (self.shard, {'native_outfit_arms_0_diff.dds.1': 8, 'native_outfit_arms_0_diff.dds.1a': 8,
                                             'boots.dds.1': 0})):
            original = contents(path)
            before, after, deflated = compact_archive(path, self.uncompressed)
            self.assertEqual(contents(path), original)
            self.assertLess(after, before)
            self.assertEqual(self.methods(path), expected)
            with zipfile.ZipFile(path) as archive:
                self.assertIsNone(archive.testzip())
                self.assertTrue(all(m.compress_size < m.file_size * 0.95 for m in archive.infolist() if m.compress_type == 8))
            self.assertFalse(path.with_name(path.name + '.deflate').exists())

    def test_a_zip32_archive_stays_zip32(self):
        compact_archive(self.shard, self.uncompressed)
        data = self.shard.read_bytes()
        self.assertNotIn(b'PK\x06\x06', data); self.assertNotIn(b'PK\x06\x07', data)

    def test_package_pass_updates_the_receipt_keeps_hard_linked_originals_and_is_idempotent(self):
        staged = self.root / 'staged'
        staged.mkdir()
        for path in self.package.rglob('*'):
            target = staged / path.relative_to(self.package)
            if path.is_dir(): target.mkdir(parents=True, exist_ok=True)
            else: target.parent.mkdir(parents=True, exist_ok=True); os.link(path, target)
        originals = {p: p.read_bytes() for p in (self.people, self.shard, self.package / RECEIPT)}
        reported = []
        report = compact_package(staged, lambda *a: reported.append(a))
        self.assertEqual(report['archives'], 2); self.assertEqual(report['members'], 3)
        self.assertLess(report['bytes_after'], report['bytes_before'])
        self.assertEqual(reported[-1][:3], ('Compress package textures', 2, 2))
        receipt = json.loads((staged / RECEIPT).read_text())
        self.assertEqual(receipt['files'], {p.relative_to(staged).as_posix(): digest(p)
                                            for p in staged.rglob('*') if p.is_file() and p.name != RECEIPT})
        self.assertEqual(receipt['package_compaction']['version'], package_compaction.VERSION)
        for path, data in originals.items():
            self.assertEqual(path.read_bytes(), data)                               # the verified package is untouched
        self.assertEqual(contents(staged / 'Data/gm_person_1.pak'), contents(self.people))
        self.assertEqual(candidates(staged), [])          # its incompressible texture stays stored, and that is remembered
        self.assertEqual(compact_package(staged), dict(version=package_compaction.VERSION, archives=0))
        # A later step that rewrites an archive (new digest) makes it a candidate again.
        rewritten = staged / 'Data/gm_person_1.pak'
        rewritten.unlink(); write_pak(rewritten, [('objects/x.dds', header(FLOAT) + bake(9))])
        receipt['files']['Data/gm_person_1.pak'] = digest(rewritten)
        (staged / RECEIPT).unlink(); (staged / RECEIPT).write_text(json.dumps(receipt))
        self.assertEqual(candidates(staged), [rewritten])

    def test_cancel_keeps_the_original_archive(self):
        original = self.people.read_bytes()
        with self.assertRaises(InterruptedError):
            compact_archive(self.people, self.uncompressed, cancelled=lambda: True)
        self.assertEqual(self.people.read_bytes(), original)
        self.assertFalse(self.people.with_name(self.people.name + '.deflate').exists())

    def test_the_setting_turns_the_pass_off(self):
        os.environ[package_compaction.SETTING] = '0'
        try: self.assertFalse(package_compaction.enabled())
        finally: os.environ.pop(package_compaction.SETTING)
        self.assertTrue(package_compaction.enabled())


if __name__ == '__main__':
    unittest.main()
