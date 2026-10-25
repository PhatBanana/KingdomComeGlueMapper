import sys
import tempfile
from pathlib import Path
import unittest
from unittest.mock import patch
import xml.etree.ElementTree as ET

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from test_clothing_assembly import garment_skin
from clothing_regions import Skin
from clothing_native_composition import compose_source_regions, merge_feature_slots


class NativeCompositionTests(unittest.TestCase):
    def test_feature_slots_are_unique_across_the_native_multimaterial(self):
        material=ET.fromstring('<Material><SubMaterials><Material><FeatureSlots Slot00="Fabric"/></Material><Material><FeatureSlots Slot00="Fabric" Slot01="Leather"/></Material></SubMaterials></Material>')
        self.assertEqual(merge_feature_slots(material), {'Slot00':'Fabric','Slot01':'Leather'})
        self.assertEqual([dict(n.attrib) for n in material.iter('FeatureSlots')], [{'Slot00':'Fabric'},{'Slot01':'Leather'}])
        ET.SubElement(material.find('SubMaterials/Material'), 'FeatureSlots', Slot00='Different')
        with self.assertRaisesRegex(ValueError, 'Conflicting native feature slot'):
            merge_feature_slots(material)

    def test_selected_native_region_contains_both_layers_at_every_lod(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            folder = root / 'objects/characters/test'
            folder.mkdir(parents=True)
            material = '<Material><SubMaterials>' + '<Material Shader="Illum"/>' * 10 + '</SubMaterials></Material>'
            for stem in ('inner', 'outer', 'shoes'):
                (folder / (stem + '.skin')).write_bytes(garment_skin())
                (folder / (stem + '.mtl')).write_text(material)
            (folder / 'outer_lod1.skin').write_bytes(garment_skin())
            component = ET.fromstring('''<Component FilePath="test"><DerivedComponents>
                <Clothing Name="inner" ArmorType="Dress"><Elements><SkinElement EquipmentPart="torso" BodyLayerId="8" Model="inner.skin" Material="inner.mtl"/></Elements></Clothing>
                <Clothing Name="outer" ArmorType="Dress" HidingGroups="outer_hides"><Elements><SkinElement EquipmentPart="torso" BodyLayerId="5" Model="outer.skin" Material="outer.mtl" KeepBodyLayer="true"/></Elements></Clothing>
                <Clothing Name="shoes" ArmorType="Shoes"><Elements><SkinElement EquipmentPart="feet" BodyLayerId="5" Model="shoes.skin" Material="shoes.mtl"/></Elements></Clothing>
                <Clothing Name="underwear"><Elements><SkinElement EquipmentPart="torso" BodyLayerId="8" Model="inner.skin" Material="inner.mtl"/></Elements></Clothing>
                </DerivedComponents></Component>''')
            component.find('.//Clothing').set('HidingGroups', 'inner_hides')
            items = ET.fromstring('<ItemClasses><Armor Id="i" Clothing="inner"/><Armor Id="o" Clothing="outer"/><Armor Id="s" Clothing="shoes"/></ItemClasses>')
            preset = ET.fromstring('<clothing_preset><Items><Guid>i</Guid><Guid>o</Guid><Guid>s</Guid></Items></clothing_preset>')
            # Palette canonicalization is tested separately with real skeletons.
            with patch('clothing_native_composition.canonicalize_skin_skeletons', side_effect=lambda blobs: blobs):
                report = compose_source_regions(root, component, items, preset, {'8': 1, '5': 5})
            self.assertEqual(report[0]['sources'], ['inner', 'outer'])
            self.assertEqual(report[0]['triangles_by_lod'], {0: 8, 1: 8})
            for name in ('outfit_torso.skin', 'outfit_torso_lod1.skin'):
                self.assertEqual(len(Skin((folder / name).read_bytes()).faces), 8)
            self.assertEqual([n.get('Clothing') for n in items], ['outer', 'shoes'])
            self.assertEqual([n.text for n in preset.find('Items')], ['o', 's'])
            owner = component.find(".//Clothing[@Name='outer']")
            self.assertEqual(owner.get('HidingGroups'), 'inner_hides outer_hides')
            self.assertEqual(owner.find('Elements/SkinElement').get('Model'), 'outfit_torso.skin')
            self.assertEqual(component.find(".//Clothing[@Name='underwear']/Elements/SkinElement").get('Model'), 'inner.skin')
            self.assertIsNone(component.find(".//Clothing[@Name='inner']"))
            self.assertEqual(compose_source_regions(root, component, items, preset, {'8': 1, '5': 5}), [])


if __name__ == '__main__':
    unittest.main()
