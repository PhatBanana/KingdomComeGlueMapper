"""Preset and failure boundaries: never install an incomplete optional bake."""
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from setup_mods import checked_config,worker
from setup_baking import bake_package
from contextlib import ExitStack

class BakeSetupTests(unittest.TestCase):
    def config(self,root):
        return dict(mods=['map'],action='build_install',kcd1='source',kcd2='target',workspace=str(root),package='',baking='all')

    def test_validate_presets_and_ignore_irrelevant_options(self):
        c=self.config('.')
        for preset in ('none','buildings','all'):
            c['baking']=preset;self.assertEqual(checked_config(c)['baking'],preset)
        c['baking']='invalid'
        with self.assertRaises(ValueError):checked_config(c)
        c['baking']='all';c['mods']=['fishing'];self.assertEqual(checked_config(c)['baking'],'none')
        c['mods']=['map'];c['action']='install';self.assertEqual(checked_config(c)['baking'],'none')

    def test_failed_bake_keeps_installation_untouched(self):
        with tempfile.TemporaryDirectory() as t:
            root=Path(t);config=self.config(root);(root/'job.json').write_text(json.dumps(config))
            def converted(path):
                (Path(path).parent/'package').mkdir();return 0
            with patch('setup_mods.preflight'),patch('setup_mods.legacy.worker',side_effect=converted),patch('setup_mods.bake_package',side_effect=ValueError('Tile failed')) as bake,patch('setup_mods.legacy.install_transaction') as install:
                self.assertEqual(worker(root/'job.json'),1);install.assert_not_called()
                self.assertEqual(bake.call_args.args[3],'all')
                self.assertTrue((root/'package/map').is_dir())

    def test_cancelled_bake_does_not_install(self):
        with tempfile.TemporaryDirectory() as t:
            root=Path(t);(root/'job.json').write_text(json.dumps(self.config(root)))
            def converted(path):(Path(path).parent/'package').mkdir();return 0
            with patch('setup_mods.preflight'),patch('setup_mods.legacy.worker',side_effect=converted),patch('setup_mods.bake_package',side_effect=InterruptedError('Cancelled')),patch('setup_mods.legacy.install_transaction') as install:
                self.assertEqual(worker(root/'job.json'),2);install.assert_not_called()

    def test_no_baking_does_not_read_or_modify_package(self):
        with patch('setup_baking.verify_package') as verify:
            bake_package('nonexistent','game','workspace','none',lambda *a:None,lambda:False)
            verify.assert_not_called()

    def test_failed_bake_retains_plan_and_original_package_for_retry(self):
        with tempfile.TemporaryDirectory() as t,ExitStack() as stack:
            root=Path(t);package=root/'map';level=package/'Data/Levels/test';level.mkdir(parents=True)
            (level/'terrain.pak').write_bytes(b'original terrain')
            (level/'level.pak').write_bytes(b'original level')
            receipt={'files':{'Data/Levels/test/terrain.pak':'x'}}
            stack.enter_context(patch('setup_baking.verify_package',return_value=receipt))
            plan=stack.enter_context(patch('world_surface_scene.plan'))
            stack.enter_context(patch('world_surface_landscape.augment'))
            def covered(base,scene,**kw):
                scene.mkdir(parents=True);(scene/'plan.json').write_text('{"errors":{}}')
            stack.enter_context(patch('world_surface_coverage.augment',side_effect=covered))
            build=stack.enter_context(patch('world_surface_tiles.build',side_effect=[InterruptedError('cancelled'),ValueError('tile error')]))
            stage=stack.enter_context(patch('stage_world_surfaces.stage'))
            for error in (InterruptedError,ValueError):
                with self.assertRaises(error):bake_package(package,root/'game',root/'baking','all',lambda *a:None,lambda:False)
            self.assertEqual(plan.call_count,1)
            self.assertEqual(build.call_args_list[0].args[0],build.call_args_list[1].args[0])
            stage.assert_not_called()
            self.assertEqual((level/'terrain.pak').read_bytes(),b'original terrain')
            self.assertEqual((level/'level.pak').read_bytes(),b'original level')

if __name__=='__main__':unittest.main()
