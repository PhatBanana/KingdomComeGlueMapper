import sys
from pathlib import Path
import tempfile
import unittest
import zipfile
import zlib

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'tools'))
from world_speech_audio import relocation, select, upgrade
from dialogue_dubbing import DEPOT


def fixture():
    return {
        'Quests/demo.xml': b'<Database><Skald><Project Name="demo"><Definitions><Definition File="entry/test.xml"/></Definitions><Nodes><test Name="test"/></Nodes></Project></Skald></Database>',
        'Quests/entry/test.xml': b'<Database><Skald><Level Name="test"><Definitions><Definition File="world/open_world.xml"/></Definitions><Nodes><open_world Name="open_world"/></Nodes></Level></Skald></Database>',
        'Quests/entry/world/open_world.xml': b'<Database><Skald><Gameplay Name="open_world" VoiceNamespace="true"><Definitions><Definition File="native.xml"/></Definitions><Nodes><speech Name="renamed_but_native"/></Nodes></Gameplay></Skald></Database>',
        'Quests/entry/world/native.xml': b'<Database><Skald><Dialog Name="speech"><Dialogue><Response><Text StringName="greet_Test"/></Response></Dialogue></Dialog></Skald></Database>'}


class SpeechTests(unittest.TestCase):
    def test_scope_comes_from_level_not_archive_path(self):
        native, dest, keys = relocation(fixture(),'Quests/entry/world/open_world.xml')
        self.assertEqual((native,dest),('dialog/open_world/','dialog/test/open_world/'))
        selected = select(['dialog/open_world/hello/abc_greet_Test.ogg',
                           'dialog/open_world/hello/xyz_greet_Test.ogg',
                           'dialog/open_world/hello/abc_unused.ogg',
                           'dialog/another/abc_greet_Test.ogg'],native,dest,keys)
        self.assertEqual(len(selected),2)
        self.assertIn('dialog/test/open_world/hello/abc_greet_test.ogg',selected)

    def test_atomic_upgrade_preserves_recording_case_index_and_is_idempotent(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory); package=root/'mod'; target=root/'game'
            def pak(path,entries):
                path.parent.mkdir(parents=True,exist_ok=True)
                with zipfile.ZipFile(path,'w') as z:
                    for n,b in entries.items():z.writestr(n,b)
            stem='abc_greet_Test'; key=zlib.crc32(stem.encode())
            index=f'<Root><DialogueDubbingData><DialogueDubbing FileHash="{key}" Duration="1"/></DialogueDubbingData></Root>'.encode()
            pak(package/'Data/gluemappertravel.pak',fixture())
            pak(package/'Localization/English.pak',{DEPOT:index,'dialog/custom/keep.ogg':b'OggSkeep'})
            source='dialog/open_world/hello/'+stem+'.ogg'
            pak(target/'Localization/English.pak',{source:b'OggSoriginal'})
            changed,report=upgrade(package,target)
            self.assertEqual(report['changed'],1)
            self.assertIn('Localization/English.pak',changed)
            with zipfile.ZipFile(package/'Localization/English.pak') as z:
                self.assertEqual(z.read('dialog/test/open_world/hello/'+stem+'.ogg'),b'OggSoriginal')
                self.assertEqual(z.read(DEPOT),index)
                self.assertEqual(z.read('dialog/custom/keep.ogg'),b'OggSkeep')
            before=(package/'Localization/English.pak').read_bytes()
            changed,report=upgrade(package,target)
            self.assertFalse(changed)
            self.assertEqual(before,(package/'Localization/English.pak').read_bytes())
            self.assertEqual(report['recordings'],1)

    def test_missing_dependency_fails(self):
        graphs=fixture();del graphs['Quests/entry/world/native.xml']
        with self.assertRaisesRegex(ValueError,'Missing speech dependency'):
            relocation(graphs,'Quests/entry/world/open_world.xml')
