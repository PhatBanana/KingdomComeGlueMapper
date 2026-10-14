import struct
import sys
import tempfile
from pathlib import Path
import unittest
import xml.etree.ElementTree as ET
import zipfile
import zlib
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from dialogue_dubbing import DEPOT, ogg_duration, dubbing_index, bind_soul_voice
from build_english_audio_test import merge_audio_strings


def ogg():
    def page(payload,flags,granule):
        return (b'OggS'+bytes([0,flags])+struct.pack('<Q',granule)+struct.pack('<III',42,0,0)
                +bytes([1,len(payload)])+payload)
    header=b'\x01vorbis'+struct.pack('<I',0)+bytes([1])+struct.pack('<I',48000)
    return page(header,2,0)+page(b'audio',4,72000)


class DubbingTests(unittest.TestCase):
    def test_vorbis_timing_uses_samples(self):
        self.assertEqual(ogg_duration(ogg()),1.5)
        for data in (b'RIFF',ogg()[:-1],ogg()[:44]):
            with self.assertRaises(ValueError):ogg_duration(data)

    def test_native_rows_and_case_sensitive_hashes_survive_merge(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);(root/'Localization').mkdir()
            table=ET.Element('database',name='barbora')
            rows=ET.SubElement(table,'DialogueDubbingData',version='1')
            samples=[f'tmck_native_line_{i}_aBcD' for i in range(32)]
            for stem in samples:ET.SubElement(rows,'DialogueDubbing',FileHash=str(zlib.crc32(stem.encode())),Duration='2.0')
            ET.SubElement(rows,'DialogueDubbing',FileHash=rows[0].get('FileHash'),Duration='3.0')
            with zipfile.ZipFile(root/'Localization/english-part0.pak','w') as archive:
                archive.writestr(DEPOT,ET.tostring(table))
                for stem in samples:archive.writestr('dialog/native/'+stem+'.ogg',ogg())
            media={'dialog/gm/tmck_new_line_aBcD.ogg':ogg()}
            blob,report=dubbing_index(root,media)
            newrows=ET.fromstring(blob).find('DialogueDubbingData')
            self.assertEqual([r.attrib for r in list(newrows)[:33]],[r.attrib for r in rows])
            self.assertEqual(report['native_entries'],33)
            self.assertEqual(newrows[-1].get('FileHash'),str(zlib.crc32(b'tmck_new_line_aBcD')))
            again,_=dubbing_index(root,media,blob)
            self.assertEqual(blob,again)

    def test_imported_soul_gets_own_character_voice(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);(root/'Data').mkdir()
            with zipfile.ZipFile(root/'Data/Tables.pak','w') as archive:
                archive.writestr('Libs/Tables/skald/voice.xml',b'<database><voices><voice voice_id="68" voice_technical_name="abigailRice"/></voices></database>')
                archive.writestr('Libs/Tables/skald/skald_character.xml',b'<database><skald_characters><skald_character skald_character_name="native" voice_id="68" gender="1"/></skald_characters></database>')
            path='Libs/Tables/rpg/soul__test.xml'
            resources={path:b'<database><souls><soul soul_name="seller"/><soul soul_name="other"/></souls></database>'}
            result,report=bind_soul_voice(resources,root,'test','seller','abigailRice','SELLER','seller_name')
            self.assertEqual(report['voice_id'],68)
            souls=ET.fromstring(result[path])
            self.assertEqual(souls.find(".//soul[@soul_name='seller']").get('skald_character_name'),'gm_voice_seller')
            self.assertIsNone(souls.find(".//soul[@soul_name='other']").get('skald_character_name'))
            again,_=bind_soul_voice(result,root,'test','seller','abigailRice','SELLER','seller_name')
            self.assertEqual(result,again)

    def test_rebuilding_preserves_original_subtitles(self):
        text=b'<Table><Row><Cell>line</Cell><Cell>Hello.</Cell><Cell>Hello.</Cell></Row></Table>'
        self.assertEqual(len(ET.fromstring(merge_audio_strings(text,text))),1)
        row = b'<Row><Cell>new</Cell><Cell>Item</Cell><Cell>Item</Cell></Row>'
        self.assertEqual(len(ET.fromstring(merge_audio_strings(text,b'<Table>'+row+row+b'</Table>'))),2)
        with self.assertRaises(ValueError):
            merge_audio_strings(text,b'<Table>'+row+row.replace(b'Item',b'Other')+b'</Table>')
        with self.assertRaises(ValueError):merge_audio_strings(text,text.replace(b'Hello.',b'Goodbye.'))


if __name__=='__main__':unittest.main()
