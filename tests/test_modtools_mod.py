"""SDK compatibility metadata must never modify the retail package."""
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'tools'))
from prepare_modtools_mod import MARKER, is_junction, junction, prepare


@unittest.skipUnless(os.name == 'nt', 'Windows SDK junctions')
class ModtoolsModTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1])
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        self.sdk = root/'SDK with spaces'
        exe = self.sdk/'Bin/Win64ReleaseSteamLTO_DLL/KingdomCome.exe'
        exe.parent.mkdir(parents=True); exe.write_bytes(b'exe')
        (self.sdk/'system.cfg').write_text('wh_sys_version = "1.5.5"')
        self.source = root/'retail/Mods/example'
        (self.source/'Data').mkdir(parents=True)
        (self.source/'Data/example.pak').write_bytes(b'assets')
        self.manifest = b'<kcd_mod><info><modid>example</modid></info><supports><version>1.5.6</version></supports></kcd_mod>'
        (self.source/'mod.manifest').write_bytes(self.manifest)
        self.view = self.sdk/'Mods/example'

    def test_sdk_version_is_private_and_refresh_tracks_sdk_update(self):
        report = prepare(self.sdk, self.source)
        self.assertFalse(report['runtime_verified'])
        self.assertEqual(ET.parse(self.view/'mod.manifest').findtext('supports/version'), '1.5.5')
        self.assertFalse(os.path.samefile(self.source/'mod.manifest', self.view/'mod.manifest'))
        self.assertTrue(os.path.samefile(self.source/'Data/example.pak', self.view/'Data/example.pak'))
        (self.sdk/'system.cfg').write_text('wh_sys_version = "1.5.7"')
        prepare(self.sdk, self.source)
        self.assertEqual(ET.parse(self.view/'mod.manifest').findtext('supports/version'), '1.5.7')
        self.assertEqual((self.source/'mod.manifest').read_bytes(), self.manifest)

    def test_whole_mod_junction_is_detached_without_touching_retail(self):
        self.view.parent.mkdir()
        junction(self.view, self.source)
        prepare(self.sdk, self.source)
        self.assertFalse(is_junction(self.view))
        self.assertEqual((self.source/'mod.manifest').read_bytes(), self.manifest)
        self.assertEqual((self.source/'Data/example.pak').read_bytes(), b'assets')

    def test_unowned_directory_and_different_link_are_rejected(self):
        self.view.mkdir(parents=True)
        (self.view/'keep').write_bytes(b'keep')
        with self.assertRaisesRegex(ValueError, 'unowned'):
            prepare(self.sdk, self.source)
        self.assertEqual((self.view/'keep').read_bytes(), b'keep')
        other = self.sdk/'Mods/another'
        junction(other, self.source)
        (self.source/'mod.manifest').write_bytes(self.manifest.replace(b'example', b'another'))
        different = self.source.parent/'different'
        different.mkdir()
        other.rmdir(); junction(other, different)
        with self.assertRaisesRegex(ValueError, 'different source'):
            prepare(self.sdk, self.source)

    def test_linked_mods_root_is_rejected_before_writes(self):
        junction(self.sdk/'Mods', self.source.parent)
        with self.assertRaisesRegex(ValueError, 'local directory'):
            prepare(self.sdk, self.source)
        self.assertFalse((self.source/MARKER).exists())
        self.assertEqual((self.source/'mod.manifest').read_bytes(), self.manifest)


if __name__ == '__main__':
    unittest.main()
