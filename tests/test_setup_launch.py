import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from setup_launch import launch, MOD_ID
from setup_web import SetupAPI
from setup_shaders import tool_root, TOOL_FILES
from steam_installations import discover


class SetupLaunchTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1])
        self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)

    def mod(self):
        mod=self.root/'game with spaces/Mods'/MOD_ID
        (mod/'ShaderCache').mkdir(parents=True)
        (mod/'mod.manifest').write_text('<kcd_mod/>')
        (mod/'ShaderCache/shader-build.json').write_text('{}')
        return mod.parent.parent

    @unittest.skipUnless(os.name=='nt','Windows launcher')
    def test_setup_uses_internal_helper_without_compiler_or_kcd1(self):
        game=self.mod()
        with patch('setup_launch.subprocess.run',return_value=Mock(returncode=0,stdout=json.dumps({'pid':123,'log':'game.log'}))) as run, patch('setup_shaders.tool_root',side_effect=AssertionError('SDK must not be needed to play')):
            self.assertEqual(launch(str(game))['pid'],123)
        args=run.call_args.args[0]
        self.assertEqual(args[-2:],['-ModDirectory',str(game/'Mods'/MOD_ID)])
        self.assertTrue(Path(args[args.index('-File')+1]).is_file())
        self.assertNotIn(str(game),args[args.index('-File')+1])
        self.assertEqual(run.call_args.kwargs['creationflags'],subprocess.CREATE_NO_WINDOW)
        self.assertEqual(list((game/'Mods'/MOD_ID).glob('*.ps1')),[])

    def test_missing_package_does_not_start_a_process(self):
        with patch('setup_launch.subprocess.run') as run:
            with self.assertRaises(ValueError):launch(str(self.root))
            run.assert_not_called()

    def test_api_blocks_launch_during_setup_and_releases_busy_after_error(self):
        api=SetupAPI();api._process=Mock();api._process.poll.return_value=None
        with patch('setup_web.launch_map') as start:
            self.assertFalse(api.launch_mod('game')['ok']);start.assert_not_called()
        api._process=None
        def fail(target):
            self.assertTrue(api._busy())
            self.assertFalse(api.start({})['ok'])
            raise ValueError('Retail shaders changed')
        with patch('setup_web.launch_map',side_effect=fail):
            self.assertIn('Retail shaders changed',api.launch_mod('game')['error'])
        self.assertFalse(api._busy())

    def test_success_and_installation_refresh_use_current_target(self):
        api=SetupAPI();game=self.mod()
        self.assertEqual(api.installed(str(game)),['map'])
        self.assertEqual(api.installed(str(self.root/'other')),[])
        with patch('setup_web.launch_map',return_value={'ok':True,'pid':42}) as start:
            self.assertEqual(api.launch_mod(str(game))['pid'],42)
            start.assert_called_once_with(str(game))

    def sdk(self,path):
        for relative in TOOL_FILES:
            p=path/relative;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(b'fixture')
        return path

    def test_sdk_in_another_steam_library_is_found_and_explicit_missing_sdk_fails(self):
        steam=self.root/'steam';library=self.root/'other-library'
        (steam/'steamapps').mkdir(parents=True)
        (steam/'steamapps/libraryfolders.vdf').write_text('"libraryfolders" { "0" { "path" "'+str(library).replace('\\','\\\\')+'" } }')
        sdk=self.sdk(library/'steamapps/common/KCD2Mod')
        (library/'steamapps/appmanifest_2429020.acf').write_text('"AppState" { "appid" "2429020" "installdir" "KCD2Mod" }')
        found,_=discover([steam]);self.assertEqual(found['mod_tools'],[str(sdk)])
        with patch.dict(os.environ,{'KCD2_MOD_TOOLS':''}),patch('steam_installations.discover',return_value=(found,[])):
            self.assertEqual(tool_root(self.root/'game'),sdk)
            with self.assertRaisesRegex(ValueError,'Modding Tools'):tool_root(self.root/'game',str(self.root/'incomplete'))
        (sdk/TOOL_FILES[-1]).unlink()
        with self.assertRaisesRegex(ValueError,'CryRenderD3D12'):tool_root(self.root/'game',str(sdk))

    def test_fresh_build_install_and_resume_require_tools_before_mutation(self):
        from desktop_setup import preflight
        from setup_resume import preflight as resume
        c=dict(kcd1='source',kcd2=str(self.root/'game'),workspace=str(self.root/'work'),mod_tools='missing',mods=['map'],action='install',resume_from=str(self.root))
        with patch('desktop_setup.validate_games',return_value='1.5.6'),patch('setup_shaders.tool_root',side_effect=ValueError('Modding Tools required')) as required,patch('setup_resume.map_receipt',return_value={'ready':True}):
            for action in ('install','build_only','build_install','build_travel'):
                with self.assertRaisesRegex(ValueError,'Modding Tools'):preflight(dict(c,action=action))
            with self.assertRaisesRegex(ValueError,'Modding Tools'):resume(dict(c,action='build_install'))
            self.assertEqual(required.call_count,5)

    def test_selected_sdk_reaches_worker_without_leaking_to_later_jobs(self):
        from desktop_setup import worker
        from setup_mods import checked_config
        c=checked_config(dict(kcd1='source',kcd2='target',workspace=str(self.root),mods=['map'],action='build_only',mod_tools='selected SDK'))
        path=self.root/'job.json';path.write_text(json.dumps(c))
        def checked(config):
            self.assertEqual(os.environ['KCD2_MOD_TOOLS'],'selected SDK')
            raise ValueError('Stop before conversion')
        with patch.dict(os.environ,{'KCD2_MOD_TOOLS':'original SDK'}),patch('desktop_setup.preflight',side_effect=checked):
            self.assertEqual(worker(path),1)
            self.assertEqual(os.environ['KCD2_MOD_TOOLS'],'original SDK')

    @unittest.skipUnless(os.name=='nt','Steam protocol on Windows')
    def test_install_button_opens_official_steam_app(self):
        with patch('setup_web.os.startfile') as open_steam:
            self.assertTrue(SetupAPI().mod_tools_link())
            open_steam.assert_called_once_with('steam://install/2429020')


if __name__=='__main__':unittest.main()
