import sys
from pathlib import Path
import tempfile
import unittest
import xml.etree.ElementTree as ET

import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'tools'))
from npc_effects import (legacy_bg_mask, native_skin_material, native_vertex_features,
                         read_dds_family, bake_macro_diffuse, native_clothing_material, write_float_dds)
from clothing_regions import Skin
from test_clothing_assembly import garment_skin


class NPCEffectsTests(unittest.TestCase):
    def test_legacy_mask_channels_are_not_rebound_blindly(self):
        source = Image.new('RGBA',(1,1),(13,47,81,159))
        self.assertEqual(legacy_bg_mask(source).getpixel((0,0)),(159,47,0,255))
        self.assertEqual(source.getpixel((0,0)),(13,47,81,159))

    def test_native_skin_preserves_surface_and_source(self):
        source = ET.fromstring('<Material Shader="HumanSkin"><Textures><Texture Map="Diffuse" File="face.dds"/></Textures></Material>')
        ref = ET.fromstring('<Material><PublicParams BloodTintCenter="1,0,0" GrimeDiffuse="0.1,0.1,0.1" Melanin="9"/></Material>')
        result = native_skin_material(source,'bg.dds',ref)
        self.assertIsNone(source.find('PublicParams'))
        self.assertEqual(result.find('Textures/Texture[@Map="Diffuse"]').get('File'),'face.dds')
        self.assertEqual(result.find('Textures/Texture[@Map="Emittance"]').get('File'),'bg.dds')
        self.assertNotIn('Melanin', result.find('PublicParams').attrib)

    def test_vertex_conversion_preserves_geometry_and_skinning(self):
        source = garment_skin()
        a, b = Skin(source), Skin(native_vertex_features(source,3))
        self.assertEqual(a.faces,b.faces)
        self.assertEqual(a.remap,b.remap)
        for key,stream in a.streams.items():
            if key != 3: self.assertEqual(stream.data,b.streams[key].data)
        self.assertEqual(b.streams[3].data[24:],bytes((255,255,227,255))*a.vertex_count)
        self.assertEqual(native_vertex_features(native_vertex_features(source,3),3),native_vertex_features(source,3))
        with self.assertRaises(ValueError): native_vertex_features(source,27)

    def test_dds_roundtrip_and_incomplete_family(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'mask.dds'
            im=Image.new('RGBA',(4,4),(23,55,79,11)); im.save(path)
            self.assertEqual(read_dds_family(path).tobytes(),im.tobytes())
            (Path(tmp)/'mask.dds.2').write_bytes(b'bad')
            with self.assertRaisesRegex(ValueError,'Incomplete'): read_dds_family(path)

    def test_macro_conversion_compensates_native_sampling(self):
        source=Image.new('RGBA',(1,1),(128,64,32,99))
        result=bake_macro_diffuse(source,ET.Element('Material'))
        sampled=result[0,0,:3].astype(np.float32)**(1/2.2)
        original=np.array(source.getpixel((0,0))[:3])/255
        expected=np.where(original<=.04045,original/12.92,((original+.055)/1.055)**2.4)
        np.testing.assert_allclose(sampled,expected,atol=.0001)
        self.assertAlmostEqual(float(result[0,0,3]),99/255,places=3)
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'macro.dds';write_float_dds(path,result)
            payload=path.read_bytes()
            self.assertEqual(payload[84:88],b'DX10')
            np.testing.assert_array_equal(np.frombuffer(payload[148:],dtype='<f2'),result.reshape(-1))

    def test_srgb_dds_keeps_encoded_bytes_and_is_flagged(self):
        import struct
        def bc1(dxgi):
            header=bytearray(148); header[:4]=b'DDS '
            struct.pack_into('<7I',header,4,124,0x81007,4,4,8,0,1)
            struct.pack_into('<2I4s',header,76,32,4,b'DX10'); struct.pack_into('<I',header,108,0x1000)
            struct.pack_into('<5I',header,128,dxgi,3,0,1,0)
            return bytes(header)+struct.pack('<HHI',0x07e0,0x001f,0x55555555)
        with tempfile.TemporaryDirectory() as tmp:
            srgb,linear=Path(tmp)/'srgb.dds',Path(tmp)/'linear.dds'
            srgb.write_bytes(bc1(72)); linear.write_bytes(bc1(71))
            a,b=read_dds_family(srgb),read_dds_family(linear)
            self.assertEqual(a.tobytes(),b.tobytes())
            self.assertTrue(a.info['srgb']); self.assertFalse(b.info['srgb'])

    def test_colour_zone_mask_is_indexed_after_srgb_decoding(self):
        # Encoded 204 is zone 3 as stored but zone 2 once decoded (0.604).
        diffuse=Image.new('RGBA',(1,1),(200,200,200,255))
        mask=Image.new('RGBA',(1,1),(0,204,0,255))
        material=ET.fromstring('<Material StringGenMask="%COLORIZING_WITH_MASK">'
                               '<PublicParams MaskBrightness2="0.5" MaskBrightness3="1"/></Material>')
        stored=bake_macro_diffuse(diffuse,material,mask)
        # The engine's HSV matrix is only approximately the identity at neutral settings.
        np.testing.assert_allclose(stored,bake_macro_diffuse(diffuse,ET.Element('Material')),atol=.005)
        mask.info['srgb']=True
        decoded=bake_macro_diffuse(diffuse,material,mask)
        np.testing.assert_allclose(decoded[0,0,:3].astype(np.float32)**(1/2.2),
                                   stored[0,0,:3].astype(np.float32)**(1/2.2)*.5,rtol=.01)

    def test_float_textures_start_at_the_largest_mip_within_the_size_cap(self):
        import struct
        from npc_effects import MAX_FLOAT_SIZE
        self.assertEqual(MAX_FLOAT_SIZE, 2048)  # 32 MB pieces; 4096 (134 MB) crashed retail
        pixels=np.random.default_rng(3).random((8,16,4)).astype(np.float16)
        with tempfile.TemporaryDirectory() as tmp:
            full,capped=Path(tmp)/'full.dds',Path(tmp)/'capped.dds'
            write_float_dds(full,pixels,max_size=16); write_float_dds(capped,pixels,max_size=8)
            a,b=full.read_bytes(),capped.read_bytes()
            # height, width, pitch, depth, mip count
            self.assertEqual(struct.unpack_from('<IIIII',a,12),(8,16,128,0,5))
            self.assertEqual(struct.unpack_from('<IIIII',b,12),(4,8,64,0,4))
            self.assertEqual(a[32:148],b[32:148])  # the rest of the header is unchanged
            # The capped file is the full chain without its top level: the same remaining bytes.
            self.assertEqual(b[148:],a[148+16*8*8:])
            write_float_dds(full,pixels)  # the default cap keeps small textures whole
            self.assertEqual(full.read_bytes(),a)
            # The default cap applies: a 4096-wide source starts at 2048 (one row keeps it small).
            wide=Path(tmp)/'wide.dds'; write_float_dds(wide,np.zeros((1,4096,4),np.float16))
            self.assertEqual(struct.unpack_from('<IIIII',wide.read_bytes(),12),(1,2048,2048*8,0,12))

    def test_clothing_removes_conflicting_bindings(self):
        source=ET.fromstring('<Material Shader="Illum" StringGenMask="%COLORIZING%DETAIL_MAPPING%NORMAL_MAP"><Textures><Texture Map="Bumpmap" File="normal.dds"/><Texture Map="Custom" File="old_damage.dds"/></Textures></Material>')
        ref=ET.fromstring('<Material><PublicParams BloodBreakup="0.2"/></Material>')
        result=native_clothing_material(source,'macro.dds','bgs.dds',ref,'LegacySurface')
        self.assertEqual(result.get('StringGenMask'),'%CLOTHING_SYSTEM%NORMAL_MAP')
        self.assertEqual(result.find('FeatureSlots').get('Slot00'),'LegacySurface')
        self.assertEqual(result.find('Textures/Texture[@Map="Custom"]').get('File'),'bgs.dds')
        self.assertEqual(source.find('Textures/Texture[@Map="Custom"]').get('File'),'old_damage.dds')


if __name__=='__main__': unittest.main()
