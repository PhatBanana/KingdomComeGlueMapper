import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
import xml.etree.ElementTree as ET
import zipfile

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from setup_cutscenes import install_media, run
from setup_mods import checked_config, worker
from setup_campaign import MOD_ID, RECEIPT, digest, verify_package


class OpeningSetupTests(unittest.TestCase):
    def test_optional_choice_and_non_map_operations(self):
        raw=dict(mods=['map'],kcd1='source',kcd2='target',workspace='work',action='build_only')
        self.assertEqual(checked_config(raw)['cutscenes'],'none')
        self.assertEqual(checked_config(dict(raw,cutscenes='opening'))['cutscenes'],'opening')
        self.assertEqual(checked_config(dict(raw,mods=['fishing'],cutscenes='opening'))['cutscenes'],'none')
        self.assertEqual(checked_config(dict(raw,action='install',cutscenes='opening'))['cutscenes'],'none')
        with self.assertRaises(ValueError):checked_config(dict(raw,cutscenes='unknown'))

    def test_cancel_does_not_start_encoder(self):
        with patch('setup_cutscenes.subprocess.Popen') as child:
            with self.assertRaises(InterruptedError):run(['encoder'],'unused',lambda *a:None,lambda:True,'Encode')
            child.assert_not_called()

    def test_failed_or_cancelled_encoding_never_installs_map(self):
        for error,code in ((ValueError('Encode failed'),1),(InterruptedError('Cancelled'),2)):
            with self.subTest(code=code), tempfile.TemporaryDirectory() as temp:
                root=Path(temp)
                config=dict(mods=['map'],action='build_install',kcd1='source',kcd2='target',
                            workspace=str(root),cutscenes='opening',converter='radvideo64.exe')
                (root/'job.json').write_text(json.dumps(config))
                def converted(path):
                    (Path(path).parent/'package').mkdir()
                    return 0
                with patch('setup_mods.preflight'),patch('setup_mods.legacy.worker',side_effect=converted), \
                     patch('setup_mods.build_opening',side_effect=error),patch('setup_mods.legacy.install_transaction') as install:
                    self.assertEqual(worker(root/'job.json'),code)
                    install.assert_not_called()

    def test_installs_movie_preserves_native_entries_and_merges_subtitles(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);package=root/'map';work=root/'work';work.mkdir()
            (package/'Data').mkdir(parents=True);(package/'Localization').mkdir()
            (package/'mod.manifest').write_text(f'<kcd_mod><info><modid>{MOD_ID}</modid></info></kcd_mod>')
            (package/'campaign-audit.json').write_text('{}')
            (package/f'Data/{MOD_ID}.pak').write_bytes(b'unchanged')
            with zipfile.ZipFile(package/'Localization/English_xml.pak','w') as z:
                z.writestr('text_ui_dialog.xml','<Table><Row><Cell>existing</Cell><Cell>Keep</Cell><Cell>Keep</Cell></Row></Table>')
                z.writestr('other.xml',b'unchanged')
            receipt=dict(schema=1,owner=MOD_ID,kind='retail-loader-probe',files={p.relative_to(package).as_posix():digest(p) for p in package.rglob('*') if p.is_file()})
            (package/RECEIPT).write_text(json.dumps(receipt))
            encoded=work/'movie.bik';encoded.write_bytes(b'test-movie')
            source=root/'English_xml.pak'
            with zipfile.ZipFile(source,'w') as z:z.writestr('strings.xml','<Table><Row><Cell>place</Cell><Cell>Skalitz</Cell><Cell>Skalitz</Cell></Row></Table>')
            native=b'<database><Cutscenes><RenderedCutscene Name="keep" Root="keep"/><RenderedCutscene Name="intro_new_game" Root="old"><Events><Event/></Events></RenderedCutscene></Cutscenes></database>'
            install_media(package,encoded,native,[dict(key='place',scale=1000,start=0,duration=1000)],source,work)
            verify_package(package)
            with zipfile.ZipFile(package/'Data/gluemapper_opening.pak') as z:
                table=ET.fromstring(z.read('Libs/Tables/ui/cutscene.xml'))
                self.assertEqual(table.find(".//*[@Name='keep']").get('Root'),'keep')
                intro=table.find(".//*[@Name='intro_new_game']")
                self.assertIsNone(intro.find('Events'))
                self.assertEqual(z.read(intro.get('Root')+'/cinematic.bk2'),b'test-movie')
                self.assertIn(b'gm_cin_',z.read(intro.get('Root')+'/cinematic.srt'))
            with zipfile.ZipFile(package/'Localization/English_xml.pak') as z:
                self.assertEqual(z.read('other.xml'),b'unchanged')
                self.assertIn(b'existing',z.read('text_ui_dialog.xml'))
                self.assertIn(b'gm_cin_',z.read('text_ui_dialog.xml'))


if __name__=='__main__':unittest.main()
