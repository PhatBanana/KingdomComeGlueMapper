import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from region_travel import write_character_shards


class CharacterShardTests(unittest.TestCase):
    def test_appearances_are_split_into_bounded_zip32_shards(self):
        with tempfile.TemporaryDirectory() as t:
            root = Path(t); data = root / 'Data'; data.mkdir()
            assets = {}
            for i in range(5):
                path = root / f'tex{i}.dds'; path.write_bytes(bytes([i]) * 4000)
                assets[f'objects/characters/gluetravel/npc/tex{i}.dds'] = path
            paks = write_character_shards(assets, data, limit=9000)
            self.assertEqual([p.name for p in paks], ['gluemappertravel_characters_00.pak',
                                                      'gluemappertravel_characters_01.pak',
                                                      'gluemappertravel_characters_02.pak'])
            packed = {}
            for pak in paks:
                self.assertLessEqual(pak.stat().st_size, 9000 + 1024)
                with zipfile.ZipFile(pak) as z:
                    for info in z.infolist():
                        self.assertEqual(info.compress_type, zipfile.ZIP_STORED)
                        packed[info.filename] = z.read(info)
            self.assertEqual(packed, {n: p.read_bytes() for n, p in assets.items()})

    def test_oversized_asset_is_rejected(self):
        with tempfile.TemporaryDirectory() as t:
            root = Path(t); data = root / 'Data'; data.mkdir()
            path = root / 'big.dds'; path.write_bytes(b'x' * 5000)
            with self.assertRaisesRegex(ValueError, 'exceeds ZIP32 shard limit'):
                write_character_shards({'objects/big.dds': path}, data, limit=4000)

    def test_no_appearances_writes_no_shard(self):
        with tempfile.TemporaryDirectory() as t:
            data = Path(t)
            self.assertEqual(write_character_shards({}, data), [])
            self.assertFalse(list(data.glob('*.pak')))


if __name__ == '__main__':
    unittest.main()
