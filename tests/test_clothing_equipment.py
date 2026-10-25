from pathlib import Path
import sys
from types import SimpleNamespace
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from clothing_equipment import NativeEquipment
from clothing_lab.validation import validate
from test_clothing_lab import FakeCatalog, part, mesh


def equipment():
    return NativeEquipment(dict(
        armor_archetype=[dict(armor_archetype_id='51', armor_archetype_name='Inner'),
                         dict(armor_archetype_id='72', armor_archetype_name='Outer'),
                         dict(armor_archetype_id='99', armor_archetype_name='OtherInner')],
        equipment_part=[dict(equipment_part_id='90', equipment_part_name='torso')],
        body_subpart=[dict(body_subpart_id='42', equipment_part_id='90')],
        armor_archetype2body_subpart=[dict(armor_archetype_id=i, body_subpart_id='42',
            body_layer_id=l, is_exclusive='true') for i,l in [('51','5'),('72','6'),('99','5')]]))


class EquipmentTests(unittest.TestCase):
    def test_resolves_names_and_native_layers_not_source_numbers(self):
        native = equipment()
        for source_id, name, expected in [('1','Inner',('51','5')), ('2','Outer',('72','6'))]:
            tables=SimpleNamespace(row=lambda *args: dict(armor_archetype_name=name))
            result=native.source_contract(dict(armor_archetype_id=source_id), tables, '51', 'torso')
            self.assertEqual((result['archetype'], result['layer']), expected)
            self.assertEqual(result['resolution'], 'source_archetype_name')

    def test_fallback_is_reported_and_missing_or_ambiguous_region_fails(self):
        native=equipment();tables=SimpleNamespace(row=lambda *args:dict(armor_archetype_name='Renamed'))
        result=native.source_contract(dict(armor_archetype_id='1'),tables,'51','torso')
        self.assertEqual(result['resolution'],'native_visual_family_default')
        with self.assertRaisesRegex(ValueError,'ambiguous'):
            native.source_contract(dict(armor_archetype_id='1'),tables,'51','feet')
        native.layers['51'].add(('torso','6'))
        with self.assertRaisesRegex(ValueError,'ambiguous'):
            native.source_contract(dict(armor_archetype_id='1'),tables,'51','torso')

    def test_validator_checks_real_equipment_slots_separately_from_visual_family(self):
        c=FakeCatalog();c.equipment=equipment()
        c.parts['dress']['attributes']['ArmorArchetypeId']='51'
        c.parts['outer']=part('outer',layer='6')
        c.parts['outer']['attributes']['ArmorArchetypeId']='72'
        c.meshes['outer.skin']=mesh(.06)
        result=validate(c,['body','dress','outer'])
        self.assertEqual(result['status'],'checked')
        # Different archetype numbers can still occupy one exclusive slot.
        c.parts['outer']['attributes']['ArmorArchetypeId']='99'
        codes={f['code'] for f in validate(c,['body','dress','outer'])['findings']}
        self.assertIn('exclusive_equipment_overlap',codes)
        self.assertIn('native_layer_difference',codes)
        c.parts['outer']['attributes']['ArmorArchetypeId']='unknown'
        self.assertIn('native_role_mismatch',{f['code'] for f in validate(c,['body','dress','outer'])['findings']})


if __name__ == '__main__': unittest.main()
