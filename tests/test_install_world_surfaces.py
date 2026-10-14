import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
import zipfile
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from install_world_surfaces import install
from validate_world_surfaces import digest


class InstallTests(unittest.TestCase):
    def fixture(self,root):
        level=root/'level';level.mkdir();stage=root/'staged';packages=stage/'packages';packages.mkdir(parents=True)
        for name in ['level.pak','terrain.pak','svo-part0.pak','svo-part1.pak']:
            (level/name).write_bytes(('old '+name).encode())
        for name in ['level.pak','terrain.pak','svo-part0.pak']:
            with zipfile.ZipFile(packages/name,'w') as z:
                if name.startswith('svo'):
                    z.writestr('terrain/svo/tile.idx',b'index');z.writestr('terrain/svo/tile.vox',b'voxels')
                else:z.writestr('payload',b'new '+name.encode())
        report={'level_dir':str(level),'tiles':1,'baseline_files':{str(p):digest(p) for p in level.iterdir()},
                'packages':{p.name:digest(p) for p in packages.iterdir()}}
        (stage/'staging.json').write_text(json.dumps(report))
        return level,stage,report

    @patch('install_world_surfaces.game_running',return_value=False)
    def test_installs_complete_set_and_preserves_recovery(self,_):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);level,stage,old=self.fixture(root);r=install(stage,root/'recovery')
            self.assertEqual(r['status'],'installed_verified')
            self.assertEqual({p.name for p in level.iterdir()},set(old['packages']))
            for path,sha in old['baseline_files'].items():self.assertEqual(digest(root/'recovery/previous'/Path(path).name),sha)

    @patch('install_world_surfaces.game_running',return_value=False)
    def test_failed_replacement_rolls_back(self,_):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);level,stage,old=self.fixture(root);replace=Path.replace;failed=[]
            def fail_once(path,target):
                if path.name=='terrain.pak' and not failed:
                    failed.append(True);raise OSError('simulated replacement failure')
                return replace(path,target)
            with patch.object(Path,'replace',fail_once),self.assertRaises(OSError):install(stage,root/'recovery')
            for path,sha in old['baseline_files'].items():self.assertEqual(digest(path),sha)
            self.assertEqual(json.loads((root/'recovery/installation.json').read_text())['status'],'rolled_back')

    @patch('install_world_surfaces.game_running',return_value=True)
    def test_live_game_refused(self,_):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);level,stage,old=self.fixture(root)
            with self.assertRaises(RuntimeError):install(stage,root/'recovery')
            self.assertFalse((root/'recovery').exists())


if __name__=='__main__':unittest.main()
