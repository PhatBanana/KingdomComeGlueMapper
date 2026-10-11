import struct
import sys
from pathlib import Path
import unittest
import tempfile
import zipfile
import xml.etree.ElementTree as ET
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from audio_mapping import EnglishRecordings, sqcb_index, scenes
from build_english_audio_test import bind_introduction, INTRO
from getting_started_dialogue import attach, PATH
from horse_trader_dialogue import dialogue, ROLE


class AudioMappingTests(unittest.TestCase):
    def test_recording_resolver_includes_dlc_but_not_hd_or_subtitles(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);(root/'Localization').mkdir()
            for pak,blob in [('English_DLC3.pak',b'OggSregular'),
                             ('English_HD-part0.pak',b'OggShd'),
                             ('English_xml.pak',b'not audio')]:
                with zipfile.ZipFile(root/'Localization'/pak,'w') as archive:
                    archive.writestr('Dialog/000611/test.ogg',blob)
            with EnglishRecordings(root) as resolver:
                self.assertEqual(resolver.extract('dialog/000611/test.ogg'),b'OggSregular')
                self.assertEqual(len(resolver.locations('dialog/000611/test.ogg')),1)
                with self.assertRaises(ValueError):resolver.extract('dialog/missing.ogg')

    def test_ambiguous_banks_fail_instead_of_picking_arbitrary_audio(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);(root/'Localization').mkdir()
            for pak,blob in [('English.pak',b'OggSone'),('IPL_English.pak',b'OggStwo')]:
                with zipfile.ZipFile(root/'Localization'/pak,'w') as archive:
                    archive.writestr('Dialog/000001/test.ogg',blob)
            with EnglishRecordings(root) as resolver:
                with self.assertRaisesRegex(ValueError,'Ambiguous'):resolver.extract('dialog/000001/test.ogg')

    def container(self,offset=None,payload=b'OggS1234'):
        header='SQCB1.00'.encode('utf-16le')+struct.pack('<I',1)
        name='TEST-1.ogg\0'.encode('utf-16le')
        return header+name+struct.pack('<II',len(header)+len(name)+8 if offset is None else offset,len(payload))+payload

    def test_music_segments_are_bounded_ogg_streams(self):
        self.assertEqual(sqcb_index(self.container())[0]['name'],'TEST-1.ogg')
        self.assertEqual(sqcb_index('SQCB1.00'.encode('utf-16le')+struct.pack('<I',0)),[])
        for blob in (self.container(0),self.container(99999),self.container(payload=b'RIFF1234'),self.container()[:30]):
            with self.assertRaises(ValueError):sqcb_index(blob)

    def test_scene_dependencies_are_not_silently_mapped(self):
        version,items=scenes(b'VERSION 1.18\nSCENE EXPLORATION/A\nE [%#night $on =]\nEND\n')
        self.assertEqual(items['exploration/a']['variables'],['%#night'])
        with self.assertRaises(ValueError):scenes(b'v\nSCENE A\nEND\nSCENE a\nEND\n')

    def test_voice_import_preserves_quest_and_shop_contracts(self):
        original,_=dialogue([dict(name='horse_a',display_name='Boxer')],'seller')
        resources,_=attach({PATH:original})
        rows=[dict(sequence_line_id=n,status='mapped',speaker='Henry' if i==0 else 'Zora',
              string_name='original_'+n,text='Original line '+n,
              target_voice='tomMcKay' if i==0 else 'abigailRice') for i,n in enumerate(INTRO)]
        blob,_,_,unvoiced=bind_introduction(resources[PATH],rows)
        root=ET.fromstring(blob)
        seq=root.find(".//Sequence[@Name='getting_started_intro']")
        self.assertEqual(seq.get('GoToDecision'),'horses')
        self.assertEqual(seq.get('EntryCondition'),"Port('getting_started_active')")
        self.assertEqual(seq.find('Triggers/Port').get('Name'),'getting_started_talked')
        self.assertEqual(len(seq.findall('Elements/Response/Text')),3)
        self.assertIn('DoMoneyTransaction',root.find(".//Sequence[@Name='buy_h00']").get('ExitScript'))
        self.assertEqual(root.find(".//SelectedSoul[@Role='"+ROLE+"']").get('Voice'),'abigailRice')
        self.assertEqual(len(unvoiced),2)
        repeat=root.find(".//Sequence[@Name='original_horse_introduction']")
        self.assertEqual(repeat.get('EntryCondition'),"!Port('getting_started_active')")
        self.assertIsNone(repeat.find('Triggers'))
        self.assertEqual(repeat.get('GoToDecision'),'horses')
        rows[0]['status']='missing_recording'
        with self.assertRaises(ValueError):bind_introduction(resources[PATH],rows)


if __name__=='__main__':unittest.main()
