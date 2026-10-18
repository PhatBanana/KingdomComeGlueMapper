import io
import struct
import sys
import unittest
import zlib
from pathlib import Path
import xml.etree.ElementTree as E
from PIL import Image
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from item_icon_atlas import atlas_index, texture
from item_icons import convert, resolve


def tag(code,payload=b''):
    return struct.pack('<H',code*64+63)+struct.pack('<I',len(payload))+payload


def atlas():
    external=struct.pack('<5H',0,9,14,64,64)+b'\x01x\x05x.dds\0'
    rect=struct.pack('<6H',7,0,2,3,12,23)
    shape=struct.pack('<H',8)+b'\0\x01\x41'+struct.pack('<H',7)
    empty=struct.pack('<HH',9,1)+tag(1)+tag(0)
    sprite=struct.pack('<HH',10,1)+tag(26,b'\x02\x01\0\x08\0')+tag(1)+tag(0)
    timeline=struct.pack('<HH',11,101)+tag(26,b'\x02\x01\0\x09\0')+tag(1)+tag(28,b'\x01\0')+tag(26,b'\x02\x01\0\x0a\0')+tag(1)*100+tag(0)
    body=b'\0\0\0\x01\0'+tag(1009,external)+tag(1008,rect)+tag(2,shape)+tag(39,empty)+tag(39,sprite)+tag(39,timeline)+tag(0)
    return b'CFX\x08'+struct.pack('<I',len(body)+8)+zlib.compress(body)


class IconTests(unittest.TestCase):
    def test_source_frames_are_one_based_and_empty_is_explicit(self):
        index=atlas_index(atlas())
        self.assertEqual(index['1'],(None,None))
        self.assertEqual(index['2'],('Libs/UI/x.dds',(2,3,12,23)))
        self.assertNotIn('0',index)

    def test_truncated_gfx_rejected(self):
        with self.assertRaises((ValueError,zlib.error)): atlas_index(atlas()[:-8])

    def test_texture_preserves_pixels_alpha_and_aspect(self):
        im=Image.new('RGBA',(32,32),(12,34,56,127))
        result=Image.open(io.BytesIO(texture(im,(2,3,12,23))))
        self.assertEqual(result.size,(64,64))
        self.assertEqual(result.getpixel((32,32)),(12,34,56,127))
        self.assertEqual(result.getpixel((0,0))[3],0)
        with self.assertRaises(ValueError): texture(im,(0,0,40,40))

    def test_mapping_updates_only_icon_and_is_idempotent(self):
        blob=b'<Items><ItemClasses><MiscItem Id="source" Name="imported" IconId="wrong" Weight="7"/></ItemClasses></Items>'
        players={'source':dict(icon_id='2')}
        index={'2':('atlas',(0,0,8,16))}
        files={'items.xml':blob}
        loader=lambda _:Image.new('RGBA',(16,16),(200,100,50,255))
        changes,assets,report=convert(files,players,{},index,loader)
        row=E.fromstring(changes['items.xml']).find('ItemClasses/MiscItem')
        self.assertEqual(row.attrib,dict(Id='source',Name='imported',IconId='gm_kcd1_item_2',Weight='7'))
        self.assertEqual(len(assets),1)
        files.update(changes)
        c,a,r=convert(files,players,{},index,loader)
        self.assertEqual(c,{})
        self.assertEqual(a,assets)
        self.assertEqual(r,[])

    def test_missing_dependency_is_not_replaced_by_category_guess(self):
        files={'items.xml':b'<Items><ItemClasses><Food Id="source"/></ItemClasses></Items>'}
        with self.assertRaisesRegex(ValueError,'Missing source inventory icon'):
            convert(files,{'source':dict(icon_id='99')},{},{},lambda _:None)

    def test_namespaced_garment_requires_name_and_localization_identity(self):
        players={'a':dict(icon_id='12',ui_name='shirt_label')}
        names={'a':'source_shirt'}
        row=E.Element('Armor',Id='generated',Name='npc_source_shirt',UIName='npc_shirt_label')
        self.assertEqual(resolve(row,players,names),'12')
        row.set('UIName','different')
        self.assertIsNone(resolve(row,players,names))

    def test_non_source_items_are_unchanged(self):
        files={'items.xml':b'<Items><ItemClasses><Food Id="native" IconId="native_icon"/></ItemClasses></Items>'}
        self.assertEqual(convert(files,{}, {}, {},lambda _:None),({},{},[]))
