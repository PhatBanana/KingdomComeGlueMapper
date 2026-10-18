from pathlib import Path
import struct
import sys
import unittest
import tempfile
import zipfile
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from clothing_regions import Chunk, read_chunks, write_chunks
from mesh_lod_metadata import normalize
from mesh_streaming import split, validate_split, validate_pair, generated_entries, upgrade_package, restore_package
from test_mesh_lod_metadata import fixture as area_fixture


def fixture():
    chunks = read_chunks(area_fixture())
    node = bytearray(204)
    node[:4] = b'tree'
    struct.pack_into('<i', node, 64, 1)
    struct.pack_into('<i', node, 68, -1)
    chunks.append(Chunk(0x100b, 0x824, 5, bytes(node)))
    chunks.append(Chunk(0x1018, 0x800, 6, b'physics bytes'))
    return write_chunks(chunks, {})


class StreamingTests(unittest.TestCase):
    def test_lossless_payload_and_small_header(self):
        source = fixture()
        h, b = split(source)
        self.assertEqual(b, normalize(source))
        heads = read_chunks(h)
        self.assertFalse(any(c.kind in (0x1016, 0x1017) for c in heads))
        self.assertEqual(heads[-1].data, b'physics bytes')
        self.assertEqual(struct.unpack_from('<I', heads[0].data)[0], 11)
        validate_split(h, b)
        validate_pair(h, b)
        self.assertEqual(split(h), (h, None))

    def test_mismatched_pair_rejected(self):
        h, b = split(fixture())
        chunks = read_chunks(b)
        damaged = bytearray(chunks[0].data)
        struct.pack_into('<f', damaged, 136, 4)
        with self.assertRaises(ValueError):
            validate_split(h, write_chunks(chunks, {1: bytes(damaged)}))

    def test_companion_filename_and_preservation(self):
        entries = list(generated_entries([('glueveg/tree_lod1.cgf', fixture())]))
        self.assertEqual([n for n,b in entries], ['glueveg/tree_lod1.cgf','glueveg/tree_lod1.cgfm'])
        self.assertEqual(list(generated_entries(entries)), entries)

    def test_unnamed_render_mesh_rejected(self):
        with self.assertRaisesRegex(ValueError, 'unique named'):
            split(area_fixture())

    def test_migration_pair_and_missing_companion(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); (root/'Data').mkdir()
            path=root/'Data/kingdomcomegluemapper_world_000.pak'
            with zipfile.ZipFile(path,'w') as z:
                z.writestr('glueveg/tree.cgf',fixture())
                z.writestr('keep',b'unchanged')
            changed, report=upgrade_package(root)
            self.assertEqual(report['split_mesh_files'],1)
            self.assertEqual(len(changed),2)
            payload=path.with_name(path.stem+'_meshes.pak')
            with zipfile.ZipFile(path) as h, zipfile.ZipFile(payload) as b:
                validate_split(h.read('glueveg/tree.cgf'),b.read('glueveg/tree.cgfm'))
                self.assertEqual(h.read('keep'),b'unchanged')
            self.assertEqual(upgrade_package(root)[0],{})
            payload.unlink()
            with self.assertRaisesRegex(ValueError,'Missing geometry companion'):
                upgrade_package(root)

    def test_conflicting_companion_rejected_before_rewrite(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); (root/'Data').mkdir()
            path=root/'Data/kingdomcomegluemapper_world_000.pak'
            with zipfile.ZipFile(path,'w') as z:
                z.writestr('glueveg/tree.cgf',fixture())
                z.writestr('glueveg/tree.cgfm',b'conflicting')
            old=path.read_bytes()
            with self.assertRaisesRegex(ValueError,'Conflicting geometry companion'):
                upgrade_package(root)
            self.assertEqual(path.read_bytes(),old)

    def test_restore_recovers_exact_payload_and_removes_companions(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); (root/'Data').mkdir()
            path=root/'Data/kingdomcomegluemapper_world_000.pak'
            with zipfile.ZipFile(path,'w') as z:
                z.writestr('glueveg/tree.cgf',normalize(fixture()))
                z.writestr('keep',b'unchanged')
            upgrade_package(root)
            changed,removed=restore_package(root)
            self.assertEqual(len(changed),1);self.assertEqual(len(removed),1)
            self.assertFalse((root/removed[0]).exists())
            with zipfile.ZipFile(path) as z:
                self.assertEqual(z.read('glueveg/tree.cgf'),normalize(fixture()))
                self.assertEqual(z.read('keep'),b'unchanged')
            self.assertEqual(restore_package(root),({},[]))
