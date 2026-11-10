"""Reading rewards of imported documents use the native reading tables."""
from pathlib import Path
import sys
import unittest
import xml.etree.ElementTree as E
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from campaign_dependencies import ImportPlan
from document_reading import convert_reading, source_reading
from region_travel_tables import managed_patches
from world_item_definitions import WorldItemAdapter
from test_campaign_dependencies import Tables

BOOK = '11111111-1111-4111-8111-111111111111'
OTHER = '22222222-2222-4222-8222-222222222222'
CONTRACT = dict(
    skills=[dict(skill_id='6', skill_name='alchemy', hidden='false'),
            dict(skill_id='14', skill_name='survival', hidden='false'),
            dict(skill_id='15', skill_name='defense', hidden='true')],
    stats=['strength', 'agility', 'vitality', 'speech'], recipes=['4'])
SOURCE_SKILLS = [dict(skill_id='6', skill_name='alchemy'), dict(skill_id='25', skill_name='herbalism'),
                 dict(skill_id='15', skill_name='defense'), dict(skill_id='21', skill_name='weapon_mace')]
REWARD = 'RPG.AddStatXP(event, soul, "vit", 350, oldProgress, newProgress);RPG.NotifyLevelXpGain("vit");'
REQUIREMENT = "if(playerSoul.soul:GetStatLevel('vit')<10)\nthen\nreturn \"@ui_playerCantStudy_lowSkill\";\nend"


def tables(document, **rpg):
    rows = {'item/document': [dict(item_id=BOOK, text_id='1', **document)], 'rpg/skill': SOURCE_SKILLS,
            'item/recipe': [dict(recipe_id='7', ui_name='recipe_potion_berserk_name')]}
    rows.update({'rpg/' + name: [dict(item_id=BOOK, **row)] for name, row in rpg.items()})
    return Tables(rows)


def convert(document, contract=CONTRACT, native=None, **rpg):
    """Convert one synthetic document through the world item adapter."""
    source = tables(document, **rpg)
    adapter = WorldItemAdapter(source, 'worlditems', native or {}, {}, native_reading=contract)
    rows = {name: {} for name in adapter.FIELDS}
    rows.update(item={}, document=source.row('item/document', 'item_id', BOOK))
    plan = ImportPlan([], dict(category='document', rows=rows, document_parts=[], document_images=[],
                               reading=source_reading(source, BOOK, rows['document'])))
    target, files, evidence = adapter.convert(BOOK, plan, {'assets': {}, 'strings': {}, 'document_images': {}})
    item = [E.fromstring(b).find('ItemClasses')[0] for n, b in files.items() if '/item/item__' in n]
    patches = {n.split('/')[-1].split('__')[0]: E.fromstring(b)[0][0] for n, b in files.items() if '/rpg/' in n}
    return target, item[0], patches, evidence


class DocumentReadingTests(unittest.TestCase):
    def test_skill_book_gets_a_native_skill_row_and_the_skill_book_type(self):
        target, item, patches, evidence = convert(dict(class_id='1', length_in_game_hours='8'),
            document_required_skill=dict(skill_id='6', skill_level_required='10', skill_xp_gained='350'))
        self.assertEqual(item.attrib | dict(Type='3', LengthInGameHours='8'), item.attrib)
        self.assertEqual(patches['document_required_skill'].attrib,
            dict(item_id=target, skill_id='6', skill_level_required='10', skill_xp_gained='350'))
        reading = evidence['reading_reward']
        self.assertEqual((reading['status'], reading['skill_mapping']['basis']), ('native_tables_emitted', 'same_name'))
        self.assertTrue(evidence['reading_rewards_verified'])
        self.assertFalse(reading['runtime_verified'])

    def test_renamed_source_skill_uses_the_native_successor_id(self):
        _, _, patches, evidence = convert(dict(class_id='1'),
            document_required_skill=dict(skill_id='25', skill_level_required='0', skill_xp_gained='70'))
        self.assertEqual(patches['document_required_skill'].get('skill_id'), '14')
        self.assertEqual(evidence['reading_reward']['skill_mapping'],
            dict(source_id='25', source_name='herbalism', target_id='14', target_name='survival',
                 basis='native_successor'))

    def test_hidden_or_missing_native_skill_leaves_the_book_unrewarded_and_flagged(self):
        for skill in ('15', '21'):
            _, item, patches, evidence = convert(dict(class_id='1'),
                document_required_skill=dict(skill_id=skill, skill_level_required='0', skill_xp_gained='70'))
            self.assertEqual((item.get('Type'), patches), ('1', {}))
            self.assertFalse(evidence['reading_rewards_verified'])
            self.assertIn('No visible native skill', evidence['reading_reward']['reason'])

    def test_stat_book_scripts_are_respelled_with_native_stat_names(self):
        target, item, patches, evidence = convert(dict(class_id='1'),
            document_reward=dict(script=REWARD), document_requirement=dict(script=REQUIREMENT))
        self.assertEqual(item.get('Type'), '3')
        self.assertEqual(patches['document_reward'].attrib, dict(item_id=target, script=REWARD.replace('vit', 'vitality')))
        self.assertEqual(patches['document_requirement'].get('script'), REQUIREMENT.replace("'vit'", "'vitality'"))
        self.assertTrue(evidence['reading_rewards_verified'])

    def test_unrecognized_script_is_not_copied_into_the_native_table(self):
        script = REWARD + 'player.soul:AddPerk("x")'
        _, item, patches, evidence = convert(dict(class_id='1'), document_reward=dict(script=script),
                                             document_requirement=dict(script=REQUIREMENT))
        self.assertEqual((item.get('Type'), patches), ('1', {}))
        self.assertEqual(evidence['reading_reward']['status'], 'unsupported')
        self.assertFalse(evidence['reading_rewards_verified'])
        for bad in (dict(document_reward=dict(script=REWARD.replace('vit', 'luck'))),
                    dict(document_requirement=dict(script=REQUIREMENT))):
            self.assertEqual(convert(dict(class_id='1'), **bad)[2], {})

    def test_recipe_without_a_native_recipe_stays_unverified_and_gets_no_recipe_id(self):
        _, item, patches, evidence = convert(dict(class_id='2', recipe_id='7'))
        self.assertEqual((item.get('Type'), item.get('RecipeId'), patches), ('2', None, {}))
        self.assertFalse(evidence['reading_rewards_verified'])
        self.assertIn('recipe 7 has no native AlchemyRecipe', evidence['reading_reward']['reason'])
        self.assertEqual(evidence['reading_reward']['source']['recipe']['ui_name'], 'recipe_potion_berserk_name')

    def test_document_without_a_source_reward_needs_nothing(self):
        _, item, patches, evidence = convert(dict(class_id='1'))
        self.assertEqual((item.get('Type'), patches), ('1', {}))
        self.assertEqual(evidence['reading_reward']['status'], 'no_source_reward')
        self.assertTrue(evidence['reading_rewards_verified'])

    def test_missing_native_contract_is_reported_instead_of_guessed(self):
        _, item, patches, evidence = convert(dict(class_id='1'), contract=None,
            document_required_skill=dict(skill_id='6', skill_level_required='0', skill_xp_gained='70'))
        self.assertEqual((item.get('Type'), patches), ('1', {}))
        self.assertFalse(evidence['reading_rewards_verified'])
        unjoined = convert_reading(BOOK, BOOK, None, CONTRACT, 'worlditems')
        self.assertEqual((unjoined[0], unjoined[2]['offline_supported']), ({}, False))

    def test_reward_follows_the_identity_of_a_replaced_native_placeholder(self):
        placeholder = E.Element('Document', Id=BOOK, Name='old', Model='preproduction/traffic_cone/traffic_cone')
        target, item, patches, _ = convert(dict(class_id='1'), native={BOOK: placeholder},
            document_required_skill=dict(skill_id='6', skill_level_required='0', skill_xp_gained='70'))
        self.assertNotEqual(target, BOOK)
        self.assertEqual((item.get('Id'), patches['document_required_skill'].get('item_id')), (target, target))

    def test_plan_joins_the_source_reading_rows(self):
        source = tables(dict(class_id='1'), document_reward=dict(script=REWARD))
        reading = source_reading(source, BOOK, source.row('item/document', 'item_id', BOOK))
        self.assertEqual(reading, {'document_reward': dict(item_id=BOOK, script=REWARD)})
        self.assertEqual(source_reading(source, OTHER, {}), {})

    def test_package_merge_keeps_one_reward_row_per_item(self):
        skill = dict(document_required_skill=dict(item_id=BOOK, skill_id='6', skill_level_required='0',
                                                  skill_xp_gained='70'), skill=SOURCE_SKILLS[0])
        files = {}
        for identity in (BOOK, OTHER):
            files.update(convert_reading(identity, identity, skill, CONTRACT, 'worlditems')[0])
        merged = managed_patches(files, 'mod')
        self.assertEqual(list(merged), ['Libs/Tables/rpg/document_required_skill__mod.xml'])
        rows = E.fromstring(merged['Libs/Tables/rpg/document_required_skill__mod.xml'])[0]
        self.assertEqual((rows.tag, rows.get('version'), [r.get('item_id') for r in rows]),
                         ('document_required_skills', '1', [BOOK, OTHER]))
        files.update(convert_reading(BOOK, BOOK, skill, CONTRACT, 'containeritems')[0])
        with self.assertRaisesRegex(ValueError, 'duplicate primary key'):
            managed_patches(files, 'mod')


if __name__ == '__main__':
    unittest.main()
