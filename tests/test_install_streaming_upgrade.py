import sys
import tempfile
from pathlib import Path
import unittest
from unittest.mock import patch
import zipfile
import xml.etree.ElementTree as ET
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from install_streaming_upgrade import install
from spatial_hlod import Group, hierarchy, serialize


def pak(path, entries):
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, 'w') as z:
        for name, value in entries.items(): z.writestr(name, value)


class InstallStreamingTests(unittest.TestCase):
    def test_replaces_all_old_copies_and_preserves_lighting(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); data = root/'Data'; level = data/'Levels/test'
            textures = root/'textures'; spatial = root/'spatial'
            tree, blob, _ = serialize(hierarchy([Group('leaf', 'Cluster', (0,0,0), 1)]))
            entries = {'terrain/hlods.xml': ET.tostring(tree), 'terrain/hlods.dat': blob,
                       'mission.xml': b'lighting settings'}
            for folder in (level, spatial/'packages'):
                pak(folder/'level.pak', entries)
                pak(folder/'terrain.pak', {'terrain/terrain.dat': b'preserved terrain'})
            pak(level/'svo-part0.pak', {'tile': b'lighting tile'})
            for name in ('a.pak', 'b.pak'):
                pak(data/name, {'gluebuild/test.txt': b'old', 'other': b'untouched'})
            pak(textures/'kingdomcomegluemapper_world_000.pak',
                {'gluebuild/test.txt': b'new', 'gluebuild/new.txt': b'added'})
            with patch('install_streaming_upgrade.game_running', return_value=False):
                result = install(data, level, textures, spatial, root/'recovery')
            self.assertEqual(result['status'], 'installed_verified')
            for name in ('a.pak', 'b.pak'):
                with zipfile.ZipFile(data/name) as z:
                    self.assertEqual(z.read('gluebuild/test.txt'), b'new')
                    self.assertEqual(z.read('other'), b'untouched')
                with zipfile.ZipFile(result['backups'][str((data/name).resolve())]) as z:
                    self.assertEqual(z.read('gluebuild/test.txt'), b'old')
            with zipfile.ZipFile(level/'svo-part0.pak') as z:
                self.assertEqual(z.read('tile'), b'lighting tile')

    def test_refuses_live_game(self):
        with patch('install_streaming_upgrade.game_running', return_value=True):
            with self.assertRaisesRegex(RuntimeError, 'Close KingdomCome'):
                install('Data', 'Data/Levels/test', 'textures', 'spatial', 'recovery')


if __name__ == '__main__': unittest.main()
