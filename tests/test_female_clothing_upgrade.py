from contextlib import ExitStack
import hashlib
import os
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import xml.etree.ElementTree as ET
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from campaign_dependencies import ImportPlan
from setup_female_clothing import repair, upgrade
from static_assets import StagedAssets
from test_character_upgrade import sample_skin
from world_item_clothing import ClothingAdapter


def table(gender='Female', owned=True, keep='false'):
    name = 'worlditems_cloth_example' if owned else 'native_dress'
    return (f'<database><CharacterComponents><Component Name="{name}_root" Race="Human" '
            f'Gender="{gender}" FilePath="gluetravel/worlditems/example/">'
            f'<DerivedComponents><Clothing Name="{name}" ArmorType="F_SimpleDress">'
            f'<Elements><SkinElement EquipmentPart="torso" Model="torso.skin" KeepBodyLayer="{keep}" '
            'BodyLayerId="9" IsFinalLayer="true"/></Elements></Clothing></DerivedComponents>'
            '</Component></CharacterComponents></database>').encode()


class FemaleClothingUpgradeTests(unittest.TestCase):
    def test_pickup_converter_retains_female_body_and_keeps_male_replacement_policy(self):
        # Exercise the converter's emitted registration, not a parallel Boolean
        # assertion: female arms share torso while male arms live independently.
        with tempfile.TemporaryDirectory() as tmp, ExitStack() as stack:
            folder = Path(tmp)
            for gender, sex, role, region, expected in (
                    ('2', 'female', 'F_SimpleDress', 'torso', 'true'),
                    ('1', 'male', 'HoseJoined', 'legs', 'false')):
                with self.subTest(sex=sex):
                    cache = folder / sex
                    cache.mkdir()
                    emitted = StagedAssets(cache)
                    model = f'objects/characters/humans/cloth/s{gender}_p2_l1_v0.skin'
                    material = 'objects/characters/humans/cloth/source.mtl'
                    emitted['source.mtl'] = b'<Material Shader="Illum"/>'
                    assets = SimpleNamespace(index={model: None, material: None}, emitted=emitted,
                                             material=lambda path: 'source', mesh=lambda path: sample_skin())
                    adapter = object.__new__(ClothingAdapter)
                    adapter.assets = assets
                    adapter.native = SimpleNamespace(get=lambda path: (sample_skin(), []))
                    adapter.components = ET.fromstring(
                        f'<Component ArmorArchetypeId="native-role"><Clothing Name="{role}" ArmorType="{role}">'
                        f'<Elements><SkinElement EquipmentPart="{region}" BodyLayerId="9"/></Elements>'
                        '</Clothing></Component>')
                    adapter.parents = {c: p for p in adapter.components.iter() for c in p}
                    adapter.defer = False
                    part = dict(model=model, material=material, gender_id=gender, clothing_id='source-clothing')
                    plan = ImportPlan(source=dict(part=part, armor={}, role=role))
                    with patch('world_item_clothing.convert_character_materials', return_value={}):
                        name, files, _ = adapter.convert('item-id', plan, {})
                    registration = ET.fromstring(files['Libs/Tables/Character/CharacterComponent__' + name + '.xml'])
                    element = registration.find('.//Clothing/Elements/SkinElement')
                    self.assertEqual(element.get('EquipmentPart'), region)
                    self.assertEqual(element.get('KeepBodyLayer'), expected)
                    self.assertEqual(element.get('BodyLayerId'), '9')
                    self.assertEqual(element.get('IsFinalLayer'), 'true')

    def test_repair_changes_only_owned_female_torso_layer(self):
        original = table()
        updated, names = repair(original)
        self.assertEqual(names, ['worlditems_cloth_example'])
        before, after = ET.fromstring(original), ET.fromstring(updated)
        before.find('.//SkinElement').set('KeepBodyLayer', 'true')
        self.assertEqual(ET.tostring(before), ET.tostring(after))
        for blob in (table(gender='Male'), table(owned=False), table(keep='true'),
                     table().replace(b'EquipmentPart="torso"', b'EquipmentPart="head"'),
                     table().replace(b'gluetravel/worlditems/', b'native/')):
            self.assertEqual(repair(blob), (blob, []))

    def test_upgrade_is_idempotent_and_preserves_other_archive_entries(self):
        with tempfile.TemporaryDirectory() as tmp:
            package = Path(tmp)
            (package / 'Data').mkdir()
            relative = 'Data/source-items.pak'
            path = package / relative
            member = 'Libs/Tables/Character/CharacterComponent__worlditems_cloth_example.xml'
            with zipfile.ZipFile(path, 'w') as z:
                z.writestr(member, table())
                z.writestr('unrelated.bin', b'original unrelated bytes')
            original = path.read_bytes()
            checkpoint = package / 'saved-checkpoint.pak'
            os.link(path, checkpoint)
            receipt = dict(files={relative: hashlib.sha256(original).hexdigest()})
            changes, report = upgrade(package, receipt)
            self.assertEqual(set(changes), {relative})
            self.assertEqual(len(report['corrected_components']), 1)
            self.assertEqual(checkpoint.read_bytes(), original)
            with zipfile.ZipFile(path) as z:
                self.assertEqual(z.read('unrelated.bin'), b'original unrelated bytes')
                self.assertEqual(ET.fromstring(z.read(member)).find('.//SkinElement').get('KeepBodyLayer'), 'true')
            receipt['files'].update(changes)
            repaired = path.read_bytes()
            self.assertEqual(upgrade(package, receipt)[0], {})
            self.assertEqual(path.read_bytes(), repaired)
            # An old marker cannot hide newly restored, but verified, output.
            path.write_bytes(original)
            receipt['files'][relative] = hashlib.sha256(original).hexdigest()
            receipt['female_clothing'] = report
            self.assertEqual(set(upgrade(package, receipt)[0]), {relative})

    def test_upgrade_rejects_unverified_archive_before_writing(self):
        with tempfile.TemporaryDirectory() as tmp:
            package = Path(tmp)
            (package / 'Data').mkdir()
            path = package / 'Data/items.pak'
            with zipfile.ZipFile(path, 'w') as z:
                z.writestr('Libs/Tables/Character/CharacterComponent__source.xml', table())
            original = path.read_bytes()
            with self.assertRaisesRegex(ValueError, 'changed package'):
                upgrade(package, dict(files={'Data/items.pak': 'wrong-hash'}))
            self.assertEqual(path.read_bytes(), original)


if __name__ == '__main__':
    unittest.main()
