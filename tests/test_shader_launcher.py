"""Exercise real NTFS links and launcher refresh without starting a game."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'tools'))
from setup_shaders import stage_for_mod
from shader_fixture import package_shaders


@unittest.skipUnless(os.name == 'nt', 'Windows junction/hardlink launcher')
class ShaderLauncherTests(unittest.TestCase):
    def setUp(self):
        # Keep test data in the repository drive, not the system temp drive.
        self.temp = tempfile.TemporaryDirectory(prefix='.shader-test-', dir=Path(__file__).resolve().parents[1])
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.game = self.root/'game with spaces'
        self.mod = self.game/'Mods/example'
        self.view = self.game/'Mods/.example-runtime'
        self.inputs = {
            'Engine/Shaders.pak': b'native shaders', 'Engine/Engine.pak': b'engine',
            'Data/Tables.pak': b'tables', 'Data/pak.cfg': b'pak list',
            'Localization/English_xml.pak': b'text',
            'Bin/Win64MasterMasterSteamPGO/KingdomCome.exe': b'exe',
            'Bin/Win64Shared/steam_api64.dll': b'dll',
            'Bin/Win64MasterMasterSteamPGO/kcd_launcher.log': b'original log',
            'system.cfg': b'config', 'user.cfg': b'user config',
            'Mods/example/mod.manifest': b'<kcd_mod><info><modid>example</modid></info></kcd_mod>',
            'Mods/example/Data/mod.pak': b'mod',
            'Mods/other/mod.manifest': b'<kcd_mod/>', 'Mods/other/Data/other.pak': b'other',
            'Mods/mod_order.txt': b'example\nother\n',
        }
        for name, blob in self.inputs.items():
            path=self.game/name; path.parent.mkdir(parents=True,exist_ok=True); path.write_bytes(blob)
        compiled=self.root/'compiled'; compiled.mkdir(); package_shaders(compiled)
        stage_for_mod(compiled,self.mod,consume=True)

    def prepare(self, success=True):
        result=subprocess.run(['powershell.exe','-NoProfile','-ExecutionPolicy','Bypass',
            '-File',str(Path(__file__).resolve().parents[1]/'runtime/launch_with_shaders.ps1'),'-ModDirectory',str(self.mod),'-PrepareOnly'],capture_output=True,text=True)
        if success:
            self.assertEqual(result.returncode,0,result.stderr)
            return json.loads(result.stdout)
        self.assertNotEqual(result.returncode,0,result.stdout)
        return result.stderr

    def unchanged(self):
        for name, blob in self.inputs.items(): self.assertEqual((self.game/name).read_bytes(),blob,name)

    def test_native_assets_are_linked_shaders_are_mod_owned_and_config_is_private(self):
        report=self.prepare()
        self.assertTrue(os.path.samefile(self.view/'Data/Tables.pak',self.game/'Data/Tables.pak'))
        self.assertTrue(os.path.samefile(self.view/'Engine/Shaders.pak',self.mod/'ShaderCache/Engine/Shaders.pak'))
        self.assertFalse(os.path.samefile(self.view/'Engine/Shaders.pak',self.game/'Engine/Shaders.pak'))
        self.assertTrue(os.path.samefile(self.view/'Mods/example/Data/mod.pak',self.mod/'Data/mod.pak'))
        self.assertEqual((self.view/'Mods/mod_order.txt').read_bytes(),self.inputs['Mods/mod_order.txt'])
        self.assertFalse((self.view/'Bin/Win64MasterMasterSteamPGO/kcd_launcher.log').exists())
        (self.view/'user.cfg').write_bytes(b'private change')
        self.assertEqual(report['native_files_replaced'],0)
        self.assertFalse(report['runtime_verified'])
        self.unchanged()

    def test_refresh_detaches_junctions_and_uses_updated_native_binaries(self):
        self.prepare()
        binary=self.game/'Bin/Win64MasterMasterSteamPGO/KingdomCome.exe'
        update=binary.with_suffix('.new'); update.write_bytes(b'updated'); update.replace(binary)
        self.inputs[binary.relative_to(self.game).as_posix()]=b'updated'
        self.assertEqual((self.view/binary.relative_to(self.game)).read_bytes(),b'exe')
        self.prepare()
        self.assertTrue(os.path.samefile(self.view/binary.relative_to(self.game),binary))
        self.unchanged()
        self.assertEqual(len(list((self.game/'Mods').glob('.*-runtime'))),1)

    def test_changed_shaders_and_unowned_runtime_are_rejected_before_writes(self):
        self.view.mkdir(); (self.view/'keep').write_bytes(b'keep')
        self.assertIn('unowned',self.prepare(False))
        self.assertEqual((self.view/'keep').read_bytes(),b'keep')
        (self.mod/'ShaderCache/Engine/Shaders.pak').write_bytes(b'tampered')
        self.assertIn('Shader package changed',self.prepare(False))
        self.unchanged()

    def test_game_update_requires_recompiled_shader_package(self):
        (self.game/'Engine/Shaders.pak').write_bytes(b'new version')
        self.assertIn('Retail shaders changed',self.prepare(False))
        self.assertFalse(self.view.exists())


if __name__ == '__main__': unittest.main()
