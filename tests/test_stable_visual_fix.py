import sys
from pathlib import Path
import tempfile
import unittest
import xml.etree.ElementTree as ET

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from character_female_body import complete_female_body
from merchant_stash import apply_stash_placement


class StableVisualTests(unittest.TestCase):
    def test_complete_body_keeps_native_uv_texture_pair_and_source_colour(self):
        class Assets:
            index = {}
            def get(self, path):
                if path.endswith('.skin'):
                    return b'native body geometry', []
                return b'<Material Diffuse="1,1,1"><Textures><Texture Map="Diffuse" File="./native.dds"/></Textures><PublicParams Melanin="0"/></Material>', []
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            folder = root / 'objects/characters/test'
            folder.mkdir(parents=True)
            (folder / 'source.mtl').write_text('<Material Diffuse=".8,.7,.6"><Textures><Texture Map="Diffuse" File="source.dds"/></Textures><PublicParams Melanin=".2"/></Material>')
            component = ET.fromstring('<Component Race="Human" Gender="Female" FilePath="test/"><DerivedComponents><Body Name="any_person"><Elements><SkinElement Model="limbs.skin" Material="source.mtl"/></Elements></Body></DerivedComponents></Component>')
            complete_female_body(root, component, Assets())
            element = component.find('.//SkinElement')
            self.assertEqual(element.get('Model'), 'native_body.skin')
            self.assertEqual((folder / 'native_body.skin').read_bytes(), b'native body geometry')
            material = ET.parse(folder / 'native_body.mtl').getroot()
            self.assertEqual(material.get('Diffuse'), '.8,.7,.6')
            self.assertEqual(material.find('PublicParams').get('Melanin'), '.2')
            self.assertEqual(material.find('.//Texture').get('File'), 'objects/characters/humans/female/body/native.dds')

    def test_stash_uses_authored_placement_without_losing_shop_stock_or_identity(self):
        stash = ET.fromstring('<Entity Pos="1,2,30" EntityGuid="stable-id"><Properties><Database sGeneratedInventory="shop-stock"/><Lock bLocked="1"/></Properties><EntityLinks><Link Name="shop"/></EntityLinks></Entity>')
        authored = ET.fromstring('<Entity Pos="4,5,6" Rotate="1,0,0,0"><Properties object_Model="objects/chest.cga" fUseDistance="2.5"><Animation anim_Open="open"/><Physics bRigidBody="1" bPhysicalize="1"/></Properties></Entity>')
        apply_stash_placement(stash, authored, 'objects/imported/')
        self.assertEqual(stash.get('Pos'), '4,5,6')
        self.assertEqual(stash.get('EntityGuid'), 'stable-id')
        self.assertEqual(stash.find('Properties/Database').get('sGeneratedInventory'), 'shop-stock')
        self.assertEqual(stash.find('Properties').get('object_Model'), 'objects/imported/chest.cga')
        self.assertIsNotNone(stash.find('EntityLinks/Link'))
        self.assertEqual(stash.find('Properties/Physics').get('bRigidBody'), '0')


if __name__ == '__main__':
    unittest.main()
