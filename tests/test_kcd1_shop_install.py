"""The ported KCD1 shop conversation binds to the seven keepers and nothing else changes behaviour."""
from pathlib import Path
import sys
import unittest
import xml.etree.ElementTree as ET

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from kcd1_shop_install import (FOLDER, HOST, MODULE, REMOVE_NATIVE, generated, greeting_nodes, haggle_nodes,
                               haggle_roles, own_rule, port_rule, register, role_rows)
from region_travel_merchant import dialogue
from shop_roles import add_haggle_roles

CUSTOM = {'addShopRoles_essential_man': ['SMLOUVANI_MUZ', 'VYJEDNAVANI_MUZ'], 'addShopRoles_ending_man': ['OBCHODNIK_SE_LOUCI']}
METAROLES = {'SMLOUVANI_MUZ': 'SMLOUVANI', 'SMLOUVANI_ZENA': 'SMLOUVANI', 'VYJEDNAVANI_MUZ': 'VYJEDNAVANI',
             'GM_KCD1_SMLOUVANI_MUZ': 'SMLOUVANI', 'GM_KCD1_SMLOUVANI_ZENA': 'SMLOUVANI'}
RULE = (b'<storm><rules><rule name="gm_person_1_roles"><selectors><hasName name="ska_merchant1" /></selectors><operations>'
        b'<addRole name="gm_person_1_role" /><addRole name="SMLOUVANI_MUZ" /><addRole name="VYJEDNAVANI_MUZ" />'
        b'<addRole name="OBCHODNIK_Z_DIALOGU_MUZ" /><addShopRoles_ending_man /><addShopRoles_greeting_man /></operations></rule></rules></storm>')
NATIVE_MODULE = b'''<Database><Skald><Gameplay Name="bribe_haggle_negotiation_vyjednavani_smlouvani_podplaceni"><Nodes>
<Function Name="addbuff9" MethodName="wh::rpgmodule::AddBuff"><Edge From="smlouvani_v_obchode_muz.add_haggle_denial" To="Exec" /><Edge From="makearray10.Array" To="Souls" /></Function>
<MakeArray Name="makearray10" TypeT="wh::rpgmodule::Souls"><Edge From="smlouvani_v_obchode_muz.SMLOUVANI_MUZ" To="A"><Vertex>v1</Vertex></Edge></MakeArray>
<InstantSendMessage Name="theft" MessageType="crime:theftDetectedDuringHaggling"><Edge From="smlouvani_v_obchode_muz.create_theft" To="Exec" /></InstantSendMessage>
<Function Name="other" MethodName="x"><Edge From="smlouvani_v_obchode_zena_new.add_haggle_denial" To="Exec" /></Function>
<smlouvani_v_obchode_muz Name="smlouvani_v_obchode_muz" /><smlouvani_v_obchode_zena_new Name="smlouvani_v_obchode_zena_new" />
</Nodes></Gameplay></Skald></Database>'''


class InstallTests(unittest.TestCase):
    def test_keeper_rule_gains_the_ported_roles_and_loses_native_haggle_trade_greeting_and_farewell(self):
        root = ET.fromstring(RULE)
        rule = root.find('rules/rule')
        added, removed = port_rule(rule, 'man')
        operations = [(o.tag, o.get('name')) for o in rule.find('operations')]
        self.assertEqual(operations, [('addRole', 'gm_person_1_role'), ('addRole', 'VYJEDNAVANI_MUZ'),
                                      ('addRole', 'GM_KCD1_OBCHODNIK'), ('addRole', 'GM_KCD1_POZDRAV_MUZ'),
                                      ('addRole', 'GM_KCD1_SMLOUVANI_MUZ')] + [('removeRole', r) for r in REMOVE_NATIVE])
        self.assertEqual(sorted(removed), ['OBCHODNIK_Z_DIALOGU_MUZ', 'SMLOUVANI_MUZ', 'addShopRoles_ending_man',
                                           'addShopRoles_greeting_man'])
        self.assertEqual(haggle_roles(rule, METAROLES, CUSTOM), ['GM_KCD1_SMLOUVANI_MUZ'])
        self.assertEqual(port_rule(rule, 'man'), ([], []))

    def test_haggle_guard_sees_native_roles_hidden_in_custom_operations(self):
        root = ET.fromstring(RULE.replace(b'<addRole name="SMLOUVANI_MUZ" />', b'<addShopRoles_essential_man />'))
        rule = root.find('rules/rule')
        port_rule(rule, 'man')
        self.assertEqual(haggle_roles(rule, METAROLES, CUSTOM), ['SMLOUVANI_MUZ', 'GM_KCD1_SMLOUVANI_MUZ'])

    def test_role_rows_give_only_the_haggle_roles_the_smlouvani_metarole(self):
        rows = {r.get('role_name'): r.get('metarole_name') for r in ET.fromstring(role_rows()).iter('role')}
        self.assertEqual(rows, {'GM_KCD1_OBCHODNIK': 'NPC', 'GM_KCD1_POZDRAV_MUZ': 'NPC', 'GM_KCD1_POZDRAV_ZENA': 'NPC',
                                'GM_KCD1_SMLOUVANI_MUZ': 'SMLOUVANI', 'GM_KCD1_SMLOUVANI_ZENA': 'SMLOUVANI'})

    def test_haggle_wiring_is_cloned_onto_the_ported_dialog_and_role(self):
        nodes = haggle_nodes(NATIVE_MODULE, 'man')
        by_name = {n.get('Name'): n for n in nodes}
        self.assertEqual(sorted(by_name), ['gm_kcd1_smlouvani_muz', 'gm_kcd1_smlouvani_muz_addbuff9',
                                           'gm_kcd1_smlouvani_muz_makearray10', 'gm_kcd1_smlouvani_muz_theft'])
        edges = {(n.get('Name'), e.get('From'), e.get('To')) for n in nodes for e in n.findall('Edge')}
        self.assertIn(('gm_kcd1_smlouvani_muz_makearray10', 'gm_kcd1_smlouvani_muz.GM_KCD1_SMLOUVANI_MUZ', 'A'), edges)
        self.assertIn(('gm_kcd1_smlouvani_muz_addbuff9', 'gm_kcd1_smlouvani_muz_makearray10.Array', 'Souls'), edges)
        self.assertFalse(any(len(e) for n in nodes for e in n.findall('Edge')))

    def test_greeting_is_fed_by_the_kcd2_state_node_and_cooldown(self):
        nodes = {n.tag: n for n in greeting_nodes('woman', ['je_rano', 'reputace_dobra'])}
        dialog = nodes['gm_kcd1_pozdrav_zena']
        self.assertEqual([(e.get('From'), e.get('To')) for e in dialog.findall('Edge')],
                         [('gm_kcd1_pozdrav_zena_state.je_rano', 'je_rano'),
                          ('gm_kcd1_pozdrav_zena_state.reputace_dobra', 'reputace_dobra'),
                          ('gm_kcd1_pozdrav_zena_greeted.HasContext', 'uz_jsem_pozdravil')])
        self.assertEqual(nodes['timeandplayerstate'].get('Namespace'), 'utils.greetings_utils')
        self.assertEqual(nodes['addopenworldcooldown'].find('Constant').get('Value'), 'dialogPlayerGreeting')
        with self.assertRaisesRegex(ValueError, 'without a KCD2 state output'):
            greeting_nodes('man', ['hrac_je_rytir'])

    def test_module_registration_is_idempotent(self):
        host = (b'<Database><Skald><Gameplay Name="open_world" VoiceNamespace="true"><Definitions>'
                b'<Definition File="native/a.xml" /></Definitions><Nodes><a Name="a" /></Nodes></Gameplay></Skald></Database>')
        once = register(host)
        self.assertEqual(register(once), once)
        gameplay = ET.fromstring(once).find('Skald/Gameplay')
        self.assertIn('kcd1_shop/gm_kcd1_shop.xml', [d.get('File') for d in gameplay.find('Definitions')])
        self.assertEqual(len(gameplay.find('Nodes').findall(MODULE)), 1)
        self.assertTrue(FOLDER.startswith(HOST.rsplit('/', 1)[0]))

    def test_generated_dialog_shape_and_own_rule(self):
        self.assertEqual(generated(dialogue('ska_blanka', role='gm_tavern_dialog_508', name='gm_tavern_trade', diagnostics=False)),
                         ('ska_blanka', 'gm_tavern_dialog_508'))
        files = {'Libs/Storm/roles/gm_person_1.xml': RULE,
                 'Libs/Storm/roles/gm_tavern_dialog.xml': b'<storm><rules><rule name="gm_tavern_dialog_x"><selectors><hasName name="ska_merchant1" /></selectors><operations><addRole name="t" /></operations></rule></rules></storm>'}
        self.assertEqual(own_rule(files, 'ska_merchant1')[0], 'Libs/Storm/roles/gm_person_1.xml')
        self.assertIsNone(own_rule(files, 'ska_nobody'))

    def test_shop_roles_never_re_adds_the_native_haggle_to_a_ported_keeper(self):
        root = ET.fromstring(RULE)
        port_rule(root.find('rules/rule'), 'man')
        files = {'Libs/Storm/roles/gm_person_1.xml': ET.tostring(root)}
        changed, report = add_haggle_roles(files, {'ska_merchant1': 'man'})
        self.assertEqual((changed, report['ported_kcd1'], report['added']), ({}, ['ska_merchant1'], []))


if __name__ == '__main__':
    unittest.main()
