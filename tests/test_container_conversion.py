import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from garment_contracts import clothing_role, source_variant
from container_loot import compile_inventory
from ordinary_containers import properties


class Tables:
    def __init__(self, name): self.name = name
    def row(self, *args): return {'armor_archetype_name': self.name}


class ContainerConversionTests(unittest.TestCase):
    def test_source_material_type_is_not_an_equipment_slot(self):
        part = {'armor_archetype_id': '1', 'gender_id': '1'}
        for name, material, expected in [('HeadPlateHelmFull', '5', 'BascinetVisor'),
                ('BodyChainShort', '4', 'MailShort'), ('HorseSaddle', '3', 'Saddle'),
                ('HandsGloves', '5', 'Gauntlets'), ('HandsGloves', '1', 'Gloves')]:
            self.assertEqual(clothing_role(Tables(name), {'armor_type_id': material}, part), expected)
        with self.assertRaises(ValueError): clothing_role(Tables('unknown'), {'armor_type_id':'1'}, part)

    def test_missing_variant_is_reported_without_substituting_another(self):
        self.assertEqual(source_variant('#v001', ['#V001']), ('#V001', None))
        self.assertEqual(source_variant('#V025', ['#V024']), (None, '#V025'))
        with self.assertRaises(ValueError): source_variant('#v001', ['#V001', '#v001'])

    def test_loot_references_require_registered_items_and_keep_quantity_bounds(self):
        inv = dict(source_id='test', status='requires_conversion', definition={}, preset_choices=[],
            direct_items=[dict(item_id='apple', amount='2', amount_random_add='4', health='.8', health_offset='.1')])
        with self.assertRaises(ValueError): compile_inventory(inv, {}, {})
        with self.assertRaises(ValueError): compile_inventory(inv, {'apple':'native-apple'}, {})
        root, name, policy = compile_inventory(inv, {'apple':'native-apple'}, {'native-apple':'apple'})
        leaf = root.find("InventoryPresets/InventoryPreset[@Name='"+name+"_direct_0']")
        self.assertEqual(leaf.get('ModeValue'), '4')
        self.assertEqual(leaf.get('ModeValueVariation'), '2')
        self.assertEqual(leaf.find('PresetItem').get('ItemClassId'), 'native-apple')
        self.assertEqual(leaf.find('PresetItem').get('Name'), 'apple')
        self.assertEqual(leaf.find('PresetItem').get('Amount'), '6')
        self.assertEqual(policy['restock_days'], 0)

    def test_populated_stash_preserves_key_and_emptying_model(self):
        record = dict(kind='sack_or_bag', model='sack.cgf',
            source_properties='<Properties><Animation anim_Open="open"/></Properties>',
            lock={'bLocked':'1','guidItemClassId':'key'}, phase={'bChangeAfterPlayerInteract':'1'})
        contract = dict(preset='loot', restock_days=2, read_only=False,
            registered_keys={'key'}, phase_model='empty.cgf')
        result = properties(record, 'full.cgf', contract)
        self.assertEqual(result.find('Database').get('sInventoryPreset'), 'loot')
        self.assertEqual(result.find('Database').get('nDestockPeriodDays'), '0')
        self.assertEqual(result.find('Lock').get('guidItemClassId'), 'key')
        self.assertEqual(result.find('Phase').get('object_PhaseModel'), 'empty.cgf')
        self.assertEqual(result.get('bOwnedByHome'), '0')
        contract['registered_keys'] = set()
        with self.assertRaises(ValueError): properties(record, 'full.cgf', contract)


if __name__ == '__main__': unittest.main()
