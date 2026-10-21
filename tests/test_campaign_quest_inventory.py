import copy
import sys
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'tools'))
from campaign_quest_inventory import split, quest_item_roles
from container_loot import compile_inventory


def roles_rule(person, *roles):
    return ('<storm><rules><rule><selectors><hasName name="%s"/></selectors><operations>%s</operations></rule></rules></storm>'
            % (person, ''.join('<addRole name="%s"/>' % r for r in roles))).encode()


def role_table(*roles):
    return ('<database><roles>%s</roles></database>' % ''.join('<role role_name="%s" metarole_name="NPC"/>' % r for r in roles)).encode()


class QuestItemRoleTests(unittest.TestCase):
    SOULS = {'collier': 'soul-collier', 'grocer': 'soul-grocer'}

    def test_package_roles_resolve_to_their_single_soul(self):
        resources = {'Libs/Tables/rpg/role__gm_debt_results.xml': role_table('gm_debt_results_470'),
                     'Libs/Storm/roles/gm_debt_results.xml': roles_rule('collier', 'gm_debt_results_470'),
                     'Libs/Storm/roles/world/levelSwitch.xml': roles_rule('coachman', 'GM_COACHMAN')}
        self.assertEqual(quest_item_roles(resources, self.SOULS.get), {'dc.gm_debt_results_470': 'soul-collier'})

    def test_shared_native_roles_are_not_quest_item_holders(self):
        # Every male shopkeeper carries the native haggle roles; they must not make a second upgrade fail.
        resources = {'Libs/Tables/rpg/role__gm_person_a.xml': role_table('gm_person_a_role'),
                     'Libs/Storm/roles/gm_person_a.xml': roles_rule('collier', 'gm_person_a_role', 'SMLOUVANI_MUZ', 'VYJEDNAVANI_MUZ'),
                     'Libs/Storm/roles/gm_person_b.xml': roles_rule('grocer', 'SMLOUVANI_MUZ', 'VYJEDNAVANI_MUZ')}
        self.assertEqual(quest_item_roles(resources, self.SOULS.get), {'dc.gm_person_a_role': 'soul-collier'})

    def test_package_role_on_two_souls_is_rejected(self):
        resources = {'Libs/Tables/rpg/role__gm_x.xml': role_table('gm_x_1'),
                     'Libs/Storm/roles/gm_x.xml': roles_rule('collier', 'gm_x_1'),
                     'Libs/Storm/roles/gm_y.xml': roles_rule('grocer', 'gm_x_1')}
        with self.assertRaisesRegex(ValueError, 'Ambiguous quest item role: dc.gm_x_1'):
            quest_item_roles(resources, self.SOULS.get)


class QuestInventoryTests(unittest.TestCase):
    def inventory(self):
        return dict(source_id='inventory-x', status='resolved', definition={},
                    item_dependencies=['reward', 'food'], preset_choices=[], direct_items=[
            dict(item_id='reward', amount='1', amount_random_add='2', health='1'),
            dict(item_id='food', amount='4', amount_random_add='0', health='1')])

    def test_split_keeps_normal_loot_and_source_immutable(self):
        source = self.inventory(); before = copy.deepcopy(source)
        regular, rows = split(source, {'reward'})
        self.assertEqual(source, before)
        self.assertEqual([r['item_id'] for r in rows], ['reward'])
        root, _, _ = compile_inventory(regular, {'food':'food'}, {'food':'bread'})
        self.assertEqual([r.get('Name') for r in root.iter('PresetItem')], ['bread'])

    def test_unsupported_weighted_quest_selection_rejected(self):
        source = self.inventory()
        source['preset_choices'] = [dict(items=[dict(item_id='reward')])]
        with self.assertRaisesRegex(ValueError, 'weighted'):
            split(source, {'reward'})

    def test_unsupported_quantity_and_health_rejected(self):
        for field,value in [('amount','0'), ('amount','1.5'), ('health_offset','0.1')]:
            source = self.inventory(); source['direct_items'][0][field] = value
            with self.assertRaises(ValueError): split(source, {'reward'})


if __name__ == '__main__': unittest.main()
