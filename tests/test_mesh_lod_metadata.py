from pathlib import Path
import struct
import sys
import tempfile
import unittest
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from clothing_regions import Chunk, read_chunks, write_chunks
from mesh_lod_metadata import normalize, generated_entries, upgrade_package


def fixture():
    # Areas 1 and 4; one tiny triangle is intentionally excluded by the engine.
    positions = [(0,0,0),(2,0,0),(0,1,0),(8,0,0),(0,.000001,0)]
    mesh = bytearray(264)
    struct.pack_into('<6I', mesh, 0, 2, 0, 5, 9, 1, 4)
    struct.pack_into('<I', mesh, 28, 2)
    struct.pack_into('<I', mesh, 48, 3)
    struct.pack_into('<f', mesh, 136, 999)
    pos = struct.pack('<6I',0,0,5,12,0,0)+b''.join(struct.pack('<3f',*p) for p in positions)
    indices = struct.pack('<6I',0,5,9,2,0,0)+struct.pack('<9H',0,1,2,0,3,2,0,1,4)
    subsets = struct.pack('<4I',0,1,0,0)+struct.pack('<5I4f',0,9,0,5,0,0,0,0,0)
    chunks = [Chunk(0x1000,0x801,1,bytes(mesh)),Chunk(0x1016,0x800,2,pos),
              Chunk(0x1016,0x800,3,indices),Chunk(0x1017,0x800,4,subsets)]
    return write_chunks(chunks,{})


class MeshMetadataTests(unittest.TestCase):
    def test_geometric_mean_threshold_and_preservation(self):
        old=read_chunks(fixture()); new=read_chunks(normalize(fixture()))
        self.assertAlmostEqual(struct.unpack_from('<f',new[0].data,136)[0],2)
        self.assertEqual(struct.unpack_from('<I',new[0].data)[0],10)
        self.assertEqual(old[1:],new[1:])
        self.assertEqual(old[0].data[4:136],new[0].data[4:136])
        self.assertEqual(normalize(normalize(fixture())),normalize(fixture()))

    def test_bad_indices_rejected(self):
        chunks=read_chunks(fixture()); bad=bytearray(chunks[2].data)
        struct.pack_into('<H',bad,24,99)
        with self.assertRaisesRegex(ValueError,'vertex index'):
            normalize(write_chunks(chunks,{3:bytes(bad)}))

    def test_external_lod_processed_native_and_skin_untouched(self):
        entries=[('glueveg/a_lod2.cgf',fixture()),('objects/a.cgf',b'native'),('gluenpc/a.skin',b'skin')]
        out=list(generated_entries(entries))
        self.assertNotEqual(out[0][1],entries[0][1]); self.assertEqual(out[1:],entries[1:])

    def test_migration_is_idempotent_and_preserves_other_entries(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);(root/'Data').mkdir()
            path=root/'Data/kingdomcomegluemapper_world_000.pak'
            with zipfile.ZipFile(path,'w') as z:
                z.writestr('glueveg/a.cgf',fixture());z.writestr('keep',b'untouched')
            changed,report=upgrade_package(root)
            self.assertEqual(report['updated_mesh_files'],1)
            self.assertIn(path.relative_to(root).as_posix(),changed)
            with zipfile.ZipFile(path) as z:self.assertEqual(z.read('keep'),b'untouched')
            self.assertEqual(upgrade_package(root)[0],{})
            self.assertFalse(list(root.rglob('*.lod-pending')))
