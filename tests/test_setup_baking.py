"""Preset and failure boundaries: never install an incomplete optional bake."""
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from setup_mods import checked_config,worker
from setup_baking import bake_package,restore_baked_exposure
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
            root=Path(t);package=root/'map';level=package/'Data/Levels/kcd1_travel';level.mkdir(parents=True)
            base=package/'Data/Levels/kcd1_rataje';base.mkdir()
            (base/'terrain.pak').write_bytes(b'intermediate terrain')
            (level/'terrain.pak').write_bytes(b'original terrain')
            (level/'level.pak').write_bytes(b'original level')
            receipt={'files':{'Data/Levels/kcd1_travel/terrain.pak':'x'},'travel_bridge':{'destination':'kcd1_travel'}}
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
            self.assertEqual(plan.call_args.args[0],level)
            self.assertEqual(build.call_count,2)
            self.assertEqual(build.call_args.kwargs['backend'],'auto')
            self.assertEqual(build.call_args.kwargs['workers'],2)
            self.assertEqual(build.call_args_list[0].args[0],build.call_args_list[1].args[0])
            stage.assert_not_called()
            self.assertEqual((level/'terrain.pak').read_bytes(),b'original terrain')
            self.assertEqual((level/'level.pak').read_bytes(),b'original level')

    def test_baked_level_regains_native_exposure_without_touching_linked_input(self):
        import os,zipfile
        from interior_exposure import convert
        from upgrade_map import read
        native=b'<Mission><TimeOfDay><Variable Name="EV Min" Value="7"><Spline Keys="0:7:36,"/></Variable></TimeOfDay></Mission>'
        with tempfile.TemporaryDirectory() as t:
            root=Path(t);(root/'game').mkdir();(root/'input').mkdir();(root/'baked').mkdir()
            def pak(path,mission):
                with zipfile.ZipFile(path,'w') as z:z.writestr('mission_mission0.xml',mission);z.writestr('levelinfo.xml',b'<Level/>')
            pak(root/'game/native.pak',native);pak(root/'input/level.pak',convert(native)[0])
            os.link(root/'input/level.pak',root/'baked/level.pak')  # the replacement package hardlinks its input
            report=restore_baked_exposure(root/'baked/level.pak',root/'game/native.pak')
            self.assertEqual(report,{'restored_exposure_profiles':1})
            with zipfile.ZipFile(root/'baked/level.pak') as z:
                self.assertIn(b'Value="7"',read(z,'mission_mission0.xml'));self.assertEqual(read(z,'levelinfo.xml'),b'<Level/>')
            with zipfile.ZipFile(root/'input/level.pak') as z:self.assertIn(b'Value="4"',read(z,'mission_mission0.xml'))
            # A level that was not capped from this native mission is not rewritten.
            pak(root/'other.pak',native.replace(b'7',b'3'));before=(root/'other.pak').read_bytes()
            self.assertEqual(restore_baked_exposure(root/'other.pak',root/'game/native.pak'),{'restored_exposure_profiles':0})
            self.assertEqual((root/'other.pak').read_bytes(),before)

    def test_upgrade_restores_exposure_once_in_packages_baked_before_the_restore(self):
        import zipfile
        from interior_exposure import convert
        from setup_baking import upgrade_baked_exposure
        from upgrade_map import read
        native=b'<Mission><TimeOfDay><Variable Name="EV Min" Value="7"><Spline Keys="0:7:36,"/></Variable></TimeOfDay></Mission>'
        with tempfile.TemporaryDirectory() as t:
            root=Path(t);level=root/'package/Data/Levels/kcd1_travel';level.mkdir(parents=True)
            (root/'game/Data/Levels/trosecko').mkdir(parents=True)
            with zipfile.ZipFile(root/'game/Data/Levels/trosecko/level.pak','w') as z:z.writestr('mission_mission0.xml',native)
            with zipfile.ZipFile(level/'level.pak','w') as z:z.writestr('mission_mission0.xml',convert(native)[0])
            receipt={'baking':{'levels':[{'level':'kcd1_travel','tiles':3}]}}
            self.assertEqual(upgrade_baked_exposure(root/'package',json.loads(json.dumps(receipt)),None),[])
            self.assertEqual(upgrade_baked_exposure(root/'package',receipt,root/'game'),['Data/Levels/kcd1_travel/level.pak'])
            self.assertEqual(receipt['baking']['levels'][0]['exposure'],{'restored_exposure_profiles':1})
            with zipfile.ZipFile(level/'level.pak') as z:self.assertIn(b'Value="7"',read(z,'mission_mission0.xml'))
            before=(level/'level.pak').read_bytes()
            self.assertEqual(upgrade_baked_exposure(root/'package',receipt,root/'game'),[])
            self.assertEqual((level/'level.pak').read_bytes(),before)
            self.assertEqual(upgrade_baked_exposure(root/'package',{},root/'game'),[])

if __name__=='__main__':unittest.main()
