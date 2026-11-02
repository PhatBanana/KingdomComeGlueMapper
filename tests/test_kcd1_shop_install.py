"""The ported KCD1 shop conversation binds to the seven keepers and nothing else changes behaviour."""
from pathlib import Path
import os
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from kcd1_shop_install import (AUDIO_SCOPE, CRIME_HOST, ENTRY, FOLDER, HOST, MODULE, OLD_FOLDER, PROJECT, REMOVE_NATIVE,
                               generated, greeting_nodes, haggle_nodes, haggle_roles, hosted, old_layout, own_rule,
                               port_rule, register, role_rows)
from region_travel_merchant import dialogue
from shop_roles import add_haggle_roles
from world_gameplay_basis import SYSTEMS

GAME = Path(os.environ.get('KCD2_ROOT', 'D:/SteamLibrary/steamapps/common/KingdomComeDeliverance2'))
SOURCE = Path(os.environ.get('KCD1_ROOT', 'D:/SteamLibrary/steamapps/common/KingdomComeDeliverance'))
INSTALLED = GAME / 'Mods/kingdomcomegluemapper'

PROJECT_XML = (b'<Database><Skald><Project Name="GlueTravel_kcd1"><Definitions><Definition File="entry/kcd1_travel.xml" />'
               b'<Definition File="smithing_voice/open_world.xml" /></Definitions><Assets>'
               b'<SoulAsset Name="player" SharedSoulGuids="g1" /><SoulAsset Name="player_any" SharedSoulGuids="g2" /></Assets>'
               b'<Types><Type TypeName="wh::rpgmodule::Souls" Kind="array" /></Types>'
               b'<Nodes><kcd1_travel Name="kcd1_travel" /><open_world Name="open_world" /></Nodes></Project></Skald></Database>')
WRAPPER_XML = (b'<Database><Skald><Gameplay Name="open_world" VoiceNamespace="true"><Definitions>'
               b'<Definition File="minihry.xml" /><Definition File="../level_barrier_speech/stavy_hrace_unavahlad.xml" />'
               b'</Definitions><Nodes><minihry Name="minihry" /><stavy_hrace_unavahlad Name="stavy_hrace_unavahlad" />'
               b'</Nodes></Gameplay></Skald></Database>')
ENTRY_XML = (b'<Database><Skald><Level Name="kcd1_travel"><Definitions><Definition File="world/open_world.xml" />'
             b'</Definitions><Nodes><open_world Name="open_world" /></Nodes></Level></Skald></Database>')
CRIME_XML = (b'<Database><Skald><Gameplay Name="open_world"><Definitions><Definition File="native/utils.xml" /></Definitions>'
             b'<Assets /><Nodes>' + b''.join(f'<{s} Name="{s}" />'.encode() for s in (*SYSTEMS, 'utils')) +
             b'</Nodes></Gameplay></Skald></Database>')
NATIVE_PROJECT = (b'<Database><Skald><Project Name="Barbora"><Assets><SoulAsset Name="player" SharedSoulGuids="g1" />'
                  b'<SoulAsset Name="player_any" SharedSoulGuids="g2" /></Assets><Types>'
                  b'<Type TypeName="wh::rpgmodule::Souls" Kind="array" /><Type TypeName="RPGStatInterval" Kind="enum" />'
                  b'<Type TypeName="unused" Kind="enum" /></Types></Project></Skald></Database>')
BUILTINS = b'<Definitions><Nodes><Definition TypeName="MakeArray" /><Definition TypeName="Function" /></Nodes></Definitions>'


def graph(tag, name, body=b'', attrs=b''):
    return b'<Database><Skald><%s Name="%s"%s>%s</%s></Skald></Database>' % (tag, name.encode(), attrs, body, tag)


def folder_graphs():
    """A module shaped like the port's: a dialog, a namespaced utils node with an asset, and its private utils shell."""
    return {
        FOLDER + MODULE + '.xml': graph(b'Gameplay', MODULE, b'<Definitions><Definition File="gm_kcd1_obchod.xml" />'
                                        b'<Definition File="native/utils.xml" /></Definitions><Nodes>'
                                        b'<timeandplayerstate Name="s" Namespace="utils.greetings_utils">'
                                        b'<Asset Name="player" Alias="player_any" /></timeandplayerstate>'
                                        b'<MakeArray Name="a" TypeT="wh::rpgmodule::Souls" /><gm_kcd1_obchod Name="gm_kcd1_obchod" />'
                                        b'<utils Name="utils" /></Nodes>', b' VoiceNamespace="true"'),
        FOLDER + 'gm_kcd1_obchod.xml': graph(b'FaderDialog', 'gm_kcd1_obchod'),
        FOLDER + 'native/utils.xml': graph(b'Module', 'utils', b'<Definitions><Definition File="utils_greetings_utils.xml" />'
                                           b'</Definitions><Nodes><greetings_utils Name="greetings_utils" /></Nodes>'),
        FOLDER + 'native/utils_greetings_utils.xml': graph(b'Module', 'greetings_utils', b'<Definitions>'
                                                           b'<Definition File="abc.xml" /></Definitions><Nodes>'
                                                           b'<timeandplayerstate Name="timeandplayerstate" /></Nodes>'),
        FOLDER + 'native/abc.xml': graph(b'Module', 'timeandplayerstate', b'<Nodes><Function Name="f" Type="RPGStatInterval" />'
                                         b'<Function Name="g"><Asset Name="Receiver" Alias="player" /></Function></Nodes>'),
    }


def travel_fixture():
    return {PROJECT: PROJECT_XML, HOST: WRAPPER_XML, ENTRY: ENTRY_XML, CRIME_HOST: CRIME_XML}


def crime_check(wrapper_blob):
    """world_crime_graphs.prepare's registration check."""
    nodes = ET.fromstring(wrapper_blob).find('Skald')[0].find('Nodes')
    return {n.tag for n in nodes} == set(SYSTEMS) | {'utils'}

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
        once = register(WRAPPER_XML)
        self.assertEqual(register(once), once)
        gameplay = ET.fromstring(once).find('Skald/Gameplay')
        self.assertEqual([d.get('File') for d in gameplay.find('Definitions')][-1], '../kcd1_shop/gm_kcd1_shop.xml')
        self.assertEqual([n.tag for n in gameplay.find('Nodes')], ['minihry', 'stavy_hrace_unavahlad', MODULE])
        self.assertEqual(HOST, 'Quests/GlueTravel/smithing_voice/open_world.xml')
        self.assertFalse(FOLDER.startswith(CRIME_HOST.rsplit('/', 1)[0]))

    def test_registration_refuses_another_wrapper_host_or_a_conflicting_registration(self):
        for host in (CRIME_XML, WRAPPER_XML.replace(b' VoiceNamespace="true"', b''),
                     WRAPPER_XML.replace(b'Gameplay', b'Module')):
            with self.assertRaisesRegex(ValueError, 'wrapper changed'):
                register(host)
        for conflict in (b'<Definition File="../entry/world/kcd1_shop/gm_kcd1_shop.xml" />', b''):
            node = b'<gm_kcd1_shop Name="other" />' if not conflict else b''
            host = WRAPPER_XML.replace(b'</Definitions>', conflict + b'</Definitions>').replace(b'</Nodes>', node + b'</Nodes>')
            with self.assertRaisesRegex(ValueError, 'requires review'):
                register(host)

    def test_port_then_crime_in_build_order_leaves_the_crime_wrapper_alone(self):
        """Regression for -7: the port ran before crime and registered inside the crime-owned wrapper."""
        travel = travel_fixture()
        desired, audit = hosted({PROJECT: travel[PROJECT], HOST: travel[HOST]}, folder_graphs(), NATIVE_PROJECT, BUILTINS)
        self.assertNotIn(CRIME_HOST, desired)
        package = Path(self.enterContext(tempfile.TemporaryDirectory())) / 'travel.pak'
        with zipfile.ZipFile(package, 'w') as archive:
            for name, blob in {**travel, **desired}.items():
                archive.writestr(name, blob)
        with zipfile.ZipFile(package) as archive:
            after = archive.read(CRIME_HOST)
            project = ET.fromstring(archive.read(PROJECT))
            wrapper = ET.fromstring(archive.read(HOST))
        self.assertEqual(after, CRIME_XML)
        self.assertTrue(crime_check(after))
        self.assertEqual(audit, dict(validated_graphs=5, asset_checked_graphs=5, project_added=['type:RPGStatInterval']))
        self.assertEqual([t.get('TypeName') for t in project.iter('Type')], ['wh::rpgmodule::Souls', 'RPGStatInterval'])
        self.assertEqual(len(wrapper.findall('Skald/Gameplay/Nodes/' + MODULE)), 1)
        again, audit = hosted({PROJECT: desired[PROJECT], HOST: desired[HOST]}, folder_graphs(), NATIVE_PROJECT, BUILTINS)
        self.assertEqual((again, audit['project_added']), (desired, []))

    def test_hosting_audits_types_assets_and_project_bindings(self):
        folder = folder_graphs()
        broken = dict(folder)
        broken[FOLDER + 'native/utils.xml'] = broken[FOLDER + 'native/utils.xml'].replace(b'greetings_utils', b'general')
        with self.assertRaisesRegex(ValueError, 'Missing literal dependency|Unresolved'):
            hosted({PROJECT: PROJECT_XML, HOST: WRAPPER_XML}, broken, NATIVE_PROJECT, BUILTINS)
        unbound = dict(folder)
        unbound[FOLDER + 'native/abc.xml'] = unbound[FOLDER + 'native/abc.xml'].replace(b'Alias="player"', b'Alias="horse"')
        with self.assertRaisesRegex(ValueError, "Unbound assets .*horse"):
            hosted({PROJECT: PROJECT_XML, HOST: WRAPPER_XML}, unbound, NATIVE_PROJECT, BUILTINS)
        missing = PROJECT_XML.replace(b'<SoulAsset Name="player_any" SharedSoulGuids="g2" />', b'')
        desired, audit = hosted({PROJECT: missing, HOST: WRAPPER_XML}, folder, NATIVE_PROJECT, BUILTINS)
        self.assertIn('asset:player_any', audit['project_added'])
        conflicting = PROJECT_XML.replace(b'SharedSoulGuids="g2"', b'SharedSoulGuids="other"')
        with self.assertRaisesRegex(ValueError, 'Conflicting native player binding'):
            hosted({PROJECT: conflicting, HOST: WRAPPER_XML}, folder, NATIVE_PROJECT, BUILTINS)
        with self.assertRaisesRegex(ValueError, 'Conflicting inherited native type'):
            hosted({PROJECT: PROJECT_XML.replace(b'Kind="array"', b'Kind="list"'), HOST: WRAPPER_XML}, folder,
                   NATIVE_PROJECT, BUILTINS)
        with self.assertRaisesRegex(ValueError, 'Expected one project voice namespace instance'):
            hosted({PROJECT: PROJECT_XML.replace(b'<open_world Name="open_world" />', b''), HOST: WRAPPER_XML}, folder,
                   NATIVE_PROJECT, BUILTINS)
        with self.assertRaisesRegex(ValueError, 'outside'):
            hosted({PROJECT: PROJECT_XML, HOST: WRAPPER_XML}, {**folder, CRIME_HOST: CRIME_XML}, NATIVE_PROJECT, BUILTINS)

    def test_pre_release_layout_is_detected_everywhere_it_could_be(self):
        crime = CRIME_XML.replace(b'</Nodes>', b'<gm_kcd1_shop Name="gm_kcd1_shop" /></Nodes>')
        found = old_layout([OLD_FOLDER + 'gm_kcd1_shop.xml', HOST], crime,
                           ['dialog/kcd1_travel/open_world/gm_kcd1_shop/rpro_x.ogg', AUDIO_SCOPE + 'rpro_x.ogg'])
        self.assertEqual(found, [OLD_FOLDER + 'gm_kcd1_shop.xml', CRIME_HOST + ' registers ' + MODULE,
                                 'dialog/kcd1_travel/open_world/gm_kcd1_shop/rpro_x.ogg'])
        self.assertEqual(old_layout([HOST], CRIME_XML, [AUDIO_SCOPE + 'rpro_x.ogg']), [])

    @unittest.skipUnless((INSTALLED / 'Data/gluemappertravel.pak').is_file() and (SOURCE / 'Data').is_dir(),
                         'installed package and both games required')
    def test_plan_on_the_installed_package_is_rehosted_and_audited(self):
        from kcd1_shop_install import TRAVEL, plan
        changes, removed, report = plan(INSTALLED, SOURCE, GAME)
        self.assertGreater(report['validated_graphs'], 0)
        self.assertGreater(report['asset_checked_graphs'], 0)
        self.assertEqual(report['audio_scope'], AUDIO_SCOPE)
        self.assertNotIn(CRIME_HOST, changes[TRAVEL])
        self.assertTrue({'general', 'greetings_utils'} <= set(report['utils_libraries']))
        # Every ported line has its KCD1 facial track, whether this run adds them or the package already has them.
        self.assertEqual(report['facial_lines'], 510)
        if report['changed']:
            self.assertIn(HOST, changes[TRAVEL])
            self.assertEqual(len(report['recordings_added']), 510)
        else:
            # Already ported: the audits above still ran; plan writes and removes nothing.
            self.assertEqual({a: c for a, c in changes.items() if c}, {})
            self.assertEqual(removed, [])
            self.assertEqual(report['recordings_added'], [])
            self.assertEqual(report['facial_tracks_added'], 0)
            self.assertEqual(report['project_added'], [])

    def test_mixed_case_recordings_find_their_lowercase_source_facial_track(self):
        from kcd1_shop_install import facial_selection
        trader = AUDIO_SCOPE + 'akem_t23606_s45918_4_smlouvani__E7MY.ogg'
        henry = AUDIO_SCOPE + 'tmck_t22069_s1_1_obchod__Ab3x.ogg'
        silent = AUDIO_SCOPE + 'rpro_t25570_s2_1_pozdrav__ZZ.ogg'
        ported = {trader: b'a', henry: b'h', silent: b's'}
        headers = {'akem_t23606_s45918_4_smlouvani__e7my': [('x', 'r')], 'tmck_t22069_s1_1_obchod__ab3x': [('y', 'r')]}
        tracked, added = facial_selection(ported, headers, {})
        self.assertEqual(tracked, {trader, henry})
        self.assertEqual(sorted(added), sorted([trader, henry]))
        # A rerun, or a package installed with the case-sensitive lookup, adds only the tracks still missing.
        indexed = {'animations/humans/facials/' + trader[:-4].lower() + '.caf': None}
        self.assertEqual(facial_selection(ported, headers, indexed)[1], {henry: b'h'})
        headers['rpro_t25570_s2_1_pozdrav__zz'] = [('a', 'r'), ('b', 'r')]
        with self.assertRaisesRegex(ValueError, 'Ambiguous'):
            facial_selection(ported, headers, {})

    @unittest.skipUnless((GAME / 'Data/Scripts.pak').is_file(), 'KCD2 required')
    def test_crime_prepare_accepts_the_ported_entry_after_the_port(self):
        import world_crime_graphs
        from upgrade_map import xml
        entry = ET.fromstring(ENTRY_XML)
        level = entry.find('Skald/Level')
        ET.SubElement(level.find('Definitions'), 'Definition', File='gm_tavern_trade.xml')
        desired, _ = hosted({PROJECT: PROJECT_XML, HOST: WRAPPER_XML}, folder_graphs(), NATIVE_PROJECT, BUILTINS)
        self.assertNotIn(CRIME_HOST, desired)
        with zipfile.ZipFile(GAME / 'Data/Scripts.pak') as scripts:
            graphs, _ = world_crime_graphs.prepare(xml(entry), CRIME_XML, ENTRY, CRIME_HOST, scripts, 'gm_test_faction')
        self.assertFalse(any(p.startswith(FOLDER) for p in graphs))

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
