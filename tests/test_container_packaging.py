"""Container asset shards are written in parallel with the bytes of the serial writer."""
import hashlib
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'tools'))
import build_world_containers as containers


def assets(folder, count=23):
    paths = {}
    for index in range(count):
        path = folder/'converted'/f'{index:03d}.dds'
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(bytes([index]) * (300 + 37 * index))
        os.utime(path, (1_700_000_000, 1_700_000_000))  # zip entries record the file time
        paths[f'objects/loot/{index:03d}.dds'] = path
    return paths


class ContainerPackagingTests(unittest.TestCase):
    def package(self, root, paths, workers):
        output = root/f'out-{workers}'; output.mkdir()
        with patch.object(containers, 'SHARD_LIMIT', 2048), \
                patch.dict(os.environ, {containers.PACK_WORKERS_SETTING: str(workers)}):
            return output, containers.package(output, paths)

    def test_parallel_shards_match_the_serial_writer(self):
        with tempfile.TemporaryDirectory() as t:
            root = Path(t); paths = assets(root)
            serial_root, serial = self.package(root, paths, 1)
            parallel_root, parallel = self.package(root, paths, 4)
            self.assertGreater(len(serial), 4)
            self.assertEqual([e['path'] for e in serial], [e['path'] for e in parallel])
            self.assertEqual([e['sha256'] for e in serial], [e['sha256'] for e in parallel])
            members = []
            for entry in parallel:
                blob = (parallel_root/entry['path']).read_bytes()
                self.assertEqual(hashlib.sha256(blob).hexdigest(), entry['sha256'])
                self.assertEqual(blob, (serial_root/entry['path']).read_bytes())
                with zipfile.ZipFile(parallel_root/entry['path']) as archive:
                    self.assertTrue(all(i.compress_type == zipfile.ZIP_STORED for i in archive.infolist()))
                    self.assertLessEqual(sum(i.file_size for i in archive.infolist()), 2048)
                    members.extend(archive.namelist())
            self.assertEqual(members, sorted(paths))

    def test_no_assets_write_no_archive(self):
        with tempfile.TemporaryDirectory() as t:
            self.assertEqual(containers.package(Path(t), {}), [])
            self.assertFalse((Path(t)/'Data').exists())

    def test_a_shard_that_fails_while_writing_raises(self):
        with tempfile.TemporaryDirectory() as t:
            root = Path(t); paths = assets(root)
            original = containers._write_shard
            def failing(dest, members, cancelled):
                if dest.name.endswith('_02.pak'): raise OSError('disk full')
                return original(dest, members, cancelled)
            with patch.object(containers, '_write_shard', failing), self.assertRaisesRegex(OSError, 'disk full'):
                self.package(root, paths, 4)

    def test_oversized_member_is_refused_before_writing(self):
        with tempfile.TemporaryDirectory() as t:
            root = Path(t); paths = assets(root, 2)
            big = root/'big.dds'; big.write_bytes(b'x' * 3000); paths['objects/loot/big.dds'] = big
            with self.assertRaisesRegex(ValueError, 'Oversized container resource'):
                self.package(root, paths, 2)
            self.assertFalse((root/'out-2'/'Data').exists())


if __name__ == '__main__':
    unittest.main()
