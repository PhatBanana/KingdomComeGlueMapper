"""Imported potions reference a shipped buff or a converted source buff."""
from pathlib import Path
import sys
import unittest
import xml.etree.ElementTree as E
sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'tools'))
from test_campaign_dependencies import Tables
from campaign_dependencies import DependencyImporter, ImportPlan
from item_buffs import ItemBuffs, MODIFIER_NAMES, NOT_A_POISON, TEMPLATES, UNPORTED, translate
from world_item_definitions import WorldItemAdapter

ITEM = '00000000-0000-0000-0000-0000000000a1'
LOVE, LAZARUS, TIPPLER, DIGESTIVE = (
    '2edf8a8e-7eba-49e9-aa29-d3149d78c7fd', '7690a860-a843-4609-8a67-9868b87b32b5',
    '3f915710-1ccf-41a0-bc7f-67c8cc1a8e7b', 'f0dc09dd-322b-4d01-824f-677c387e6f76')
WORMWOOD, POISON, WEAPON_POISON, WEAPON_WITCH, PRESERVER = (
    'cdeed798-e09e-45c5-8523-8df75e8791a6', 'f405cbea-2a3f-4363-9e6a-23417e4e2a14',
    '56f66d97-43c6-45d1-a463-05ec76fac01c', '84561de3-32db-4fd2-a5be-db79e40ecf09',
    '1fc6b4cb-cd36-448f-a8ec-9f5513cccbc6')
RETAINED, UNKNOWN = '11111111-1111-1111-1111-111111111111', '22222222-2222-2222-2222-222222222222'


def shipped(identity, name, **fields):
    return dict(dict(buff_id=identity, buff_name=name, buff_class_id='13', buff_exclusivity_id='1',
                     buff_lifetime_id='0', buff_ui_type_id='1', buff_ui_visibility_id='3',
                     icon_id=name, is_persistent='true', implementation='Cpp:NonHealingPotionBasicTimed',
                     duration='30', buff_ui_name='native_'+name), **fields)


def contract():
    template = lambda source: (TEMPLATES[source]['template'], TEMPLATES[source]['name'])
    return dict(implementations=['Cpp:Instant', 'Cpp:TipplerPotion'], records=[
        shipped(*template(LOVE), buff_params='alp+1,speech+3', buff_family_id='6', buff_ui_order='-170'),
        shipped(*template(LAZARUS), buff_params='alp+1,health+15/t,hod*0.75', implementation='Cpp:PotionHealth'),
        shipped(*template(TIPPLER), buff_params='alp+1,apa+0.05,'),
        shipped(*template(DIGESTIVE), buff_params='hunger-20,', buff_class_id='9', buff_exclusivity_id='3',
                buff_family_id='24', implementation='Cpp:BasicTimed'),
        shipped(*template(WORMWOOD), buff_params='alp+1,strength+2'),
        shipped(*template(POISON), buff_params='poi=1,health-110/t', buff_class_id='7', buff_ai_tag_id='3',
                implementation='Cpp:PoisoningBasicTimed', visual_effect='player_poison'),
        shipped(*template(WEAPON_POISON), buff_params='poi=1,health-110/t', buff_class_id='7',
                buff_exclusivity_id='3', implementation='Cpp:PoisoningBasicTimed'),
        shipped(RETAINED.upper(), 'potion_kept', buff_params='charisma+3,fencing+1')])


def source(identity, name, params, duration, **fields):
    return dict(dict(buff_id=identity, buff_name=name, params=params, duration=duration,
                     buff_class_id='13', buff_exclusivity_id='1', buff_ui_type_id='1', buff_ui_visibility_id='3',
                     implementation='Cpp:BasicTimed', icon_id='71', visual_effect='',
                     buff_ui_name='buff_'+name, buff_desc='buff_'+name+'_desc', slot_buff_ui_name=''), **fields)


SOURCE = [
    source(LOVE, 'potion_love', 'cha+5', '600'),
    source(LAZARUS, 'potion_lazarus', 'health+100/t', '300', buff_class_id='17', buff_exclusivity_id='3',
           implementation='Cpp:PotionHealth'),
    source(TIPPLER, 'potion_tippler', 'cha-2', '3600', buff_class_id='10', buff_ui_type_id='2',
           implementation='Cpp:TipplerPotion'),
    source(DIGESTIVE, 'potion_digestive', '', '-1', buff_class_id='14', buff_exclusivity_id='3',
           buff_ui_type_id='', implementation='Cpp:Instant'),
    source(WORMWOOD, 'potion_wormwood_spirit', 'str+5,fencing+5', '180', visual_effect='player_wormwood'),
    source(POISON, 'potion_poison', 'poi=1,health-50/t', '25', buff_class_id='7', visual_effect='player_poison'),
    source(WEAPON_POISON, 'weapon_poison', 'poi=1,health-12/t', '25', buff_class_id='7',
           buff_ui_name='', buff_desc=''),
    source(WEAPON_WITCH, 'weapon_witch', '', '300'),
    source(PRESERVER, 'potion_preserver', '', '-1', implementation='Cpp:Instant'),
    source(UNKNOWN, 'potion_unreviewed', 'cha+1', '60')]


def resolver():
    return ItemBuffs(Tables({'rpg/buff': SOURCE}), contract(), 'Test')


class Strings:
    def plan(self, identity): return ImportPlan()
    def convert(self, identity, plan, registered): return 'test_'+identity, {}, {}


def convert(drink='', weapon='', subtype='', native=None, buffs=True):
    tables = Tables({
        'item/item': [dict(item_id=ITEM, item_category_id='7')],
        'item/item_category': [dict(item_category_id='7', item_category_name='potion')],
        'item/pickable_item': [dict(item_id=ITEM, weight='0.5')],
        'item/food': [dict(item_id=ITEM, health_benefit='4', alcohol_content='20', food_type_id='3',
                           food_subtype_id=subtype)],
        'item/food_subtype': [dict(food_subtype_id='5', food_subtype_name='poison'),
                              dict(food_subtype_id='9', food_subtype_name='preserver')],
        'item/consumable_item': [dict(item_id=ITEM, buff_id=drink)],
        'item/potion': [dict(item_id=ITEM, weapon_buff_id=weapon)],
        'rpg/buff': SOURCE})
    adapter = WorldItemAdapter(tables, 'test', native or {}, {}, native_buffs=contract() if buffs else None)
    importer = DependencyImporter({'items': adapter, 'buff_strings': Strings()})
    importer.ensure('items', ITEM)
    job = importer.jobs['items', ITEM]
    if job['status'] != 'imported':
        raise AssertionError(job.get('error'))
    rows = {name: E.fromstring(data)[0][0] for name, data in importer.files.items()}
    item = next(row for name, row in rows.items() if '/item/' in name)
    return item, {row.get('buff_id'): row for name, row in rows.items() if '/rpg/' in name}, job['evidence']


class ParamTests(unittest.TestCase):
    def test_source_stat_names_take_their_target_spelling(self):
        vocabulary = set(MODIFIER_NAMES.values()) | {'fencing', 'health', 'poi', 'wat', 'LimitRun'}
        self.assertEqual(translate('cha+5', vocabulary), 'charisma+5')
        self.assertEqual(translate('str+5,fencing+5', vocabulary), 'strength+5,fencing+5')
        self.assertEqual(translate('poi=1,LimitRun,health-50/t', vocabulary), 'poi=1,LimitRun,health-50/t')
        self.assertEqual(translate('wat*1.1;str+1, agi-2', vocabulary), 'wat*1.1;strength+1, agility-2')
        self.assertEqual(translate('', vocabulary), '')

    def test_modifier_unknown_to_the_target_is_refused(self):
        with self.assertRaisesRegex(ValueError, 'no native counterpart: weapon_bow'):
            translate('weapon_bow+5', {'charisma'})

    def test_reviewed_tables_do_not_contradict_each_other(self):
        self.assertFalse(set(TEMPLATES) & set(UNPORTED))
        self.assertEqual({k for k in list(TEMPLATES)+list(UNPORTED) if k != k.lower()}, set())


class ResolveTests(unittest.TestCase):
    def test_retained_source_identity_references_the_shipped_row(self):
        resolved = resolver().resolve(RETAINED)
        self.assertEqual((resolved['mode'], resolved['target']), ('native', RETAINED.upper()))

    def test_template_supplies_contract_and_source_supplies_strength_and_duration(self):
        resolved = resolver().resolve(LOVE)
        row = resolved['row']
        self.assertEqual((row['buff_params'], row['duration']), ('charisma+5', '600'))
        self.assertEqual((row['buff_class_id'], row['implementation'], row['icon_id'], row['buff_ui_order']),
                         ('13', 'Cpp:NonHealingPotionBasicTimed', 'potion_bard', '-170'))
        # The template's potion family would make this potion replace the template potion.
        self.assertNotIn('buff_family_id', row)
        self.assertNotIn('buff_ui_name', row)
        self.assertEqual(row['buff_id'], LOVE)
        self.assertEqual(resolved['strings'], dict(buff_ui_name='buff_potion_love', buff_desc='buff_potion_love_desc'))

    def test_hangover_cure_is_spelled_as_the_target_modifier(self):
        row = resolver().resolve(LAZARUS)['row']
        self.assertEqual((row['buff_params'], row['duration'], row['implementation']),
                         ('health+100/t,hod=0', '300', 'Cpp:PotionHealth'))
        self.assertEqual((row['buff_class_id'], row['buff_exclusivity_id']), ('13', '1'))

    def test_implementation_only_cure_keeps_its_registered_source_implementation(self):
        row = resolver().resolve(TIPPLER)['row']
        self.assertEqual((row['implementation'], row['buff_params'], row['duration'], row['buff_ui_type_id']),
                         ('Cpp:TipplerPotion', 'charisma-2', '3600', '2'))
        records = contract()
        records['implementations'].remove('Cpp:TipplerPotion')
        with self.assertRaisesRegex(ValueError, 'Unsupported buff implementation: Cpp:TipplerPotion'):
            ItemBuffs(Tables({'rpg/buff': SOURCE}), records, 'test').resolve(TIPPLER)

    def test_instant_cure_keeps_source_class_and_the_shipped_cure_family(self):
        row = resolver().resolve(DIGESTIVE)['row']
        self.assertEqual((row['implementation'], row['buff_class_id'], row['buff_exclusivity_id'],
                          row['buff_family_id'], row['duration']), ('Cpp:Instant', '14', '3', '24', '-1'))
        self.assertNotIn('buff_params', row)

    def test_visual_effect_missing_from_the_target_is_dropped_and_reported(self):
        resolved = resolver().resolve(WORMWOOD)
        self.assertNotIn('visual_effect', resolved['row'])
        self.assertEqual(resolved['dropped'], ['visual_effect=player_wormwood'])
        self.assertEqual(resolver().resolve(POISON)['row']['visual_effect'], 'player_poison')

    def test_unreviewed_or_inexpressible_buffs_are_reported_not_guessed(self):
        self.assertEqual(resolver().resolve(UNKNOWN)['reason'], 'No reviewed native buff template')
        self.assertIn('freshness', resolver().resolve(PRESERVER)['reason'])
        self.assertEqual(resolver().resolve('33333333-3333-3333-3333-333333333333')['reason'],
                         'Missing source buff row')

    def test_changed_template_blocks_conversion(self):
        records = contract()
        records['records'][0]['buff_name'] = 'renamed'
        with self.assertRaisesRegex(ValueError, 'template changed: potion_bard'):
            ItemBuffs(Tables({'rpg/buff': SOURCE}), records, 'test').resolve(LOVE)


class ItemTests(unittest.TestCase):
    def test_potion_references_converted_buff_and_keeps_unported_coating_pending(self):
        item, buffs, evidence = convert(LOVE, '99999999-9999-9999-9999-999999999999')
        self.assertEqual((item.tag, item.get('BuffDefinitionId')), ('Food', LOVE))
        self.assertIsNone(item.get('WeaponBuffDefinitionId'))
        self.assertEqual(buffs[LOVE].get('buff_ui_name'), 'test_buff_potion_love')
        self.assertEqual(buffs[LOVE].get('buff_name'), 'test_item_buff_'+LOVE.replace('-', ''))
        self.assertEqual(set(evidence['secondary_gameplay_pending']), {'potion'})
        self.assertEqual(evidence['item_buffs']['weapon']['reason'], NOT_A_POISON)
        self.assertNotIn('row', evidence['item_buffs']['consumable'])
        self.assertFalse(evidence['item_buffs_runtime_validated'])

    def test_retained_buff_needs_no_table(self):
        item, buffs, evidence = convert(RETAINED)
        self.assertEqual(item.get('BuffDefinitionId'), RETAINED.upper())
        self.assertEqual((buffs, evidence['secondary_gameplay_pending']), ({}, {}))

    def test_source_poison_becomes_a_coating_poison_with_shipped_charges(self):
        native = {'bane': E.Element('Poison', Id='bane', WeaponChargeCount='4', AmmoApplyCount='5',
                                    WeaponBuffDefinitionId=TEMPLATES[WEAPON_POISON]['template'].upper())}
        item, buffs, evidence = convert(POISON, WEAPON_POISON, '5', native)
        self.assertEqual((item.tag, item.get('BuffDefinitionId'), item.get('WeaponBuffDefinitionId')),
                         ('Poison', POISON, WEAPON_POISON))
        self.assertEqual((item.get('WeaponChargeCount'), item.get('AmmoApplyCount')), ('4', '5'))
        self.assertEqual([item.get(k) for k in ('HealthBenefit', 'AlcoholContent', 'Type', 'SubType')], [None]*4)
        self.assertEqual(item.get('Weight'), '0.5')
        self.assertEqual((buffs[POISON].get('buff_params'), buffs[WEAPON_POISON].get('buff_params'),
                          buffs[WEAPON_POISON].get('buff_exclusivity_id')),
                         ('poi=1,health-50/t', 'poi=1,health-12/t', '3'))
        self.assertIsNone(buffs[WEAPON_POISON].get('buff_ui_name'))
        self.assertEqual((evidence['category'], evidence['secondary_gameplay_pending']), ('Poison', {}))

    def test_poison_without_a_single_charge_contract_stays_a_drink(self):
        for native in ({}, {str(i): E.Element('Poison', WeaponChargeCount=str(i), AmmoApplyCount='4',
                            WeaponBuffDefinitionId=TEMPLATES[WEAPON_POISON]['template']) for i in (4, 8)}):
            item, buffs, evidence = convert(POISON, WEAPON_POISON, '5', native)
            self.assertEqual((item.tag, item.get('HealthBenefit'), set(buffs)), ('Food', '4', {POISON}))
            self.assertIn('charges', evidence['item_buffs']['weapon']['reason'])
            self.assertEqual(set(evidence['secondary_gameplay_pending']), {'potion'})

    def test_coating_of_other_subtypes_and_reviewed_exclusions_stay_pending(self):
        item, buffs, evidence = convert(LOVE, WEAPON_POISON, '9')
        self.assertEqual((item.tag, set(buffs)), ('Food', {LOVE}))
        item, buffs, evidence = convert(PRESERVER, WEAPON_WITCH, '5')
        self.assertEqual((item.tag, item.get('BuffDefinitionId'), buffs), ('Food', None, {}))
        self.assertEqual(set(evidence['secondary_gameplay_pending']), {'consumable_item', 'potion'})
        self.assertIn('Poison item class', evidence['item_buffs']['weapon']['reason'])

    def test_without_the_shipped_contract_the_data_stays_pending(self):
        item, buffs, evidence = convert(LOVE, WEAPON_POISON, '5', buffs=False)
        self.assertEqual((item.tag, item.get('BuffDefinitionId'), buffs), ('Food', None, {}))
        self.assertEqual(set(evidence['secondary_gameplay_pending']), {'consumable_item', 'potion'})
        self.assertNotIn('item_buffs', evidence)


if __name__ == '__main__':
    unittest.main()
