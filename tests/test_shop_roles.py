"""Converted shopkeepers get the native haggle and shop-ending roles, and nothing that opens a second trade."""
from pathlib import Path
import sys
import unittest
import xml.etree.ElementTree as ET

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from shop_roles import add_haggle_roles, keepers

MISSION = b'''<Objects>
  <Entity Name="shop_a" EntityClass="Shop" EntityGuid="000000a1-0000-0000"/>
  <Entity Name="shop_b" EntityClass="Shop" EntityGuid="000000a2-0000-0000"/>
  <Entity Name="collier" EntityClass="NPC" EntityGuid="000000b1-0000-0000"><EntityLinks><Link Name="shopKeeper" TargetGuid="000000a1-0000-0000"/></EntityLinks></Entity>
  <Entity Name="grocer" EntityClass="NPC_Female" EntityGuid="000000b2-0000-0000"><EntityLinks><Link Name="shopKeeper" TargetGuid="000000a2-0000-0000"/></EntityLinks></Entity>
  <Entity Name="guard" EntityClass="NPC" EntityGuid="000000b3-0000-0000"><EntityLinks><Link Name="home" TargetGuid="000000a1-0000-0000"/></EntityLinks></Entity>
  <Entity Name="orphan" EntityClass="NPC" EntityGuid="000000b4-0000-0000"><EntityLinks><Link Name="shopKeeper" TargetGuid="000000ff-0000-0000"/></EntityLinks></Entity>
</Objects>'''


def rule(person, role, name=None):
    return (f'<storm><rules><rule name="{name or person + "_roles"}"><selectors><hasName name="{person}" /></selectors>'
            f'<operations><addRole name="{role}" /></operations></rule></rules></storm>').encode()


def operations(blob):
    return [(o.tag, o.get('name')) for o in ET.fromstring(blob).find('rules/rule/operations')]


class ShopRoleTests(unittest.TestCase):
    def test_keepers_are_npcs_linked_to_a_shop_entity(self):
        self.assertEqual(keepers(MISSION), {'collier': 'man', 'grocer': 'woman'})

    def test_haggle_and_ending_roles_are_added_by_sex_without_trade_openers(self):
        files = {'Libs/Storm/roles/collier.xml': rule('collier', 'collier_role'),
                 'Libs/Storm/roles/grocer.xml': rule('grocer', 'grocer_role'),
                 'Libs/Storm/roles/guard.xml': rule('guard', 'guard_role'),
                 'Libs/Storm/storm.xml': b'<storm/>'}
        changed, report = add_haggle_roles(files, keepers(MISSION))
        self.assertEqual(set(changed), {'Libs/Storm/roles/collier.xml', 'Libs/Storm/roles/grocer.xml'})
        self.assertEqual(operations(changed['Libs/Storm/roles/collier.xml']), [
            ('addRole', 'collier_role'), ('addRole', 'SMLOUVANI_MUZ'), ('addRole', 'VYJEDNAVANI_MUZ'),
            ('addShopRoles_ending_man', None)])
        self.assertEqual(operations(changed['Libs/Storm/roles/grocer.xml'])[1:], [
            ('addRole', 'SMLOUVANI_ZENA'), ('addRole', 'VYJEDNAVANI_ZENA'), ('addShopRoles_ending_woman', None)])
        for blob in changed.values():  # the native trade openers would add a second Trade option
            self.assertNotIn(b'addShopRoles_essential', blob); self.assertNotIn(b'OBCHODNI', blob)
        self.assertEqual((report['keepers'], report['added'], report['without_roles_rule']),
                         (2, ['collier', 'grocer'], []))
        # Running it again on its own output changes nothing.
        again, report = add_haggle_roles({**files, **changed}, keepers(MISSION))
        self.assertEqual((again, report['added']), ({}, []))

    def test_a_keeper_without_its_own_roles_rule_is_reported(self):
        changed, report = add_haggle_roles({'Libs/Storm/roles/collier.xml': rule('collier', 'collier_role')},
                                           keepers(MISSION))
        self.assertEqual(report['without_roles_rule'], ['grocer'])
        self.assertEqual(list(changed), ['Libs/Storm/roles/collier.xml'])

    def test_dialogue_namespace_rules_selecting_a_keeper_are_left_alone(self):
        # Like ska_blanka: her person rule in gm_person_<id>.xml and a dialogue rule in
        # gm_tavern_dialog.xml. The dialogue file here sorts first, so file order cannot pick it.
        files = {'Libs/Storm/roles/gm_person_b2.xml': rule('grocer', 'gm_person_b2_role', 'gm_person_b2_roles'),
                 'Libs/Storm/roles/a_tavern_dialog.xml': rule('grocer', 'a_tavern_dialog_508', 'a_tavern_dialog_b2')}
        changed, report = add_haggle_roles(files, keepers(MISSION))
        self.assertEqual(list(changed), ['Libs/Storm/roles/gm_person_b2.xml'])
        self.assertEqual(operations(changed['Libs/Storm/roles/gm_person_b2.xml'])[1:], [
            ('addRole', 'SMLOUVANI_ZENA'), ('addRole', 'VYJEDNAVANI_ZENA'), ('addShopRoles_ending_woman', None)])
        self.assertEqual((report['added'], report['without_roles_rule']), (['grocer'], ['collier']))


if __name__ == '__main__':
    unittest.main()
