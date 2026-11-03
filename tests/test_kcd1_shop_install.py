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
GENERIC_CUSTOM = {
    'addShopRoles_essential_man': ['SMLOUVANI_MUZ', 'VYJEDNAVANI_MUZ', 'OBCHODNIK_Z_CHATU', 'OBCHODNIK_Z_DIALOGU_MUZ'],
    'addShopRoles_essential_woman': ['SMLOUVANI_ZENA', 'VYJEDNAVANI_ZENA', 'OBCHODNICE_Z_CHATU', 'OBCHODNICE_Z_DIALOGU_ZENA'],
    'addShopRoles_greeting_man': ['OBCHODNIK_ZDRAVI'], 'addShopRoles_greeting_woman': ['OBCHODNICE_ZDRAVI'],
    'addShopRoles_ending_man': ['OBCHODNIK_SE_LOUCI'], 'addShopRoles_ending_woman': ['OBCHODNICE_SE_LOUCI']}
GENERIC_SHOP_XML = b'<storm><rules>' + b''.join(
    f'<rule name="shop_{kind}{sex}"><selectors><isWoman /></selectors><operations>'
    f'<addShopRoles_essential_{sex} />{"<addShopRoles_greeting_%s /><addShopRoles_ending_%s />" % (sex, sex) if not kind else ""}'
    f'</operations></rule>'.encode()
    for sex in ('man', 'woman') for kind in ('', 'isLightTrader_', 'isVeryLightTrader_', 'isUltraLightTrader_')) + b'</rules></storm>'
ZORA_RULE = (b'<storm><rules><rule name="gm_neuhof_zora_roles"><selectors><hasName name="neu_zdena" /></selectors><operations>'
             b'<addRole name="GM_NEUHOF_HORSE_TRADER" /><addRole name="SMLOUVANI_ZENA" /><addRole name="VYJEDNAVANI_ZENA" />'
             b'<addShopRoles_ending_woman /></operations></rule></rules></storm>')
METAROLES = {'SMLOUVANI_MUZ': 'SMLOUVANI', 'SMLOUVANI_ZENA': 'SMLOUVANI', 'VYJEDNAVANI_MUZ': 'VYJEDNAVANI',
             'GM_KCD1_SMLOUVANI_MUZ': 'SMLOUVANI', 'GM_KCD1_SMLOUVANI_ZENA': 'SMLOUVANI',
             'ROZLOUCENI_S_HRACEM_COMMON_MUZ': 'ROZLOUCENI', 'GM_KCD1_ROZLOUCENI_MUZ': 'ROZLOUCENI',
             'VYJEDNAVANI_ZENA': 'VYJEDNAVANI', 'GM_KCD1_ROZLOUCENI_ZENA': 'ROZLOUCENI'}
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
                                      ('addRole', 'GM_KCD1_SMLOUVANI_MUZ'), ('addRole', 'GM_KCD1_ROZLOUCENI_MUZ'),
                                      ('addRole', 'GM_KCD1_LOUCENI_PO_NAKUPU_ZADNY_MUZ'),
                                      ('addRole', 'GM_KCD1_LOUCENI_PO_NAKUPU_BEZNY_MUZ'),
                                      ('addRole', 'GM_KCD1_LOUCENI_PO_NAKUPU_VELKY_MUZ')]
                         + [('removeRole', r) for r in REMOVE_NATIVE])
        self.assertEqual(sorted(removed), ['OBCHODNIK_Z_DIALOGU_MUZ', 'SMLOUVANI_MUZ', 'addShopRoles_ending_man',
                                           'addShopRoles_greeting_man'])
        self.assertEqual(haggle_roles(rule, METAROLES, CUSTOM), ['GM_KCD1_SMLOUVANI_MUZ'])
        # KCD2's common farewell is removed, so the KCD1 one is the keeper's only ROZLOUCENI role.
        self.assertEqual(haggle_roles(rule, METAROLES, CUSTOM, 'ROZLOUCENI'), ['GM_KCD1_ROZLOUCENI_MUZ'])
        self.assertEqual(port_rule(rule, 'man'), ([], []))

    def test_generic_trader_roles_are_removed_and_the_keeper_keeps_one_haggle_and_one_trade(self):
        from kcd1_shop_install import TRADE_STYLE, generic_shop_roles, keeper_roles
        generic = generic_shop_roles(GENERIC_SHOP_XML, GENERIC_CUSTOM, METAROLES)
        self.assertEqual(generic['woman'], ['OBCHODNICE_SE_LOUCI', 'OBCHODNICE_ZDRAVI', 'OBCHODNICE_Z_CHATU',
                                            'OBCHODNICE_Z_DIALOGU_ZENA', 'SMLOUVANI_ZENA'])
        rule = ET.fromstring(ZORA_RULE).find('rules/rule')
        # Before the port the generic rule hands her a second haggle and KCD2's spoken and chat trade.
        before = keeper_roles(rule, GENERIC_CUSTOM, generic['woman'])
        self.assertEqual([r for r in before if TRADE_STYLE.fullmatch(r)], ['OBCHODNICE_Z_CHATU', 'OBCHODNICE_Z_DIALOGU_ZENA'])
        added, removed = port_rule(rule, 'woman', generic['woman'])
        self.assertEqual(removed, ['SMLOUVANI_ZENA', 'addShopRoles_ending_woman'])
        roles = keeper_roles(rule, GENERIC_CUSTOM, generic['woman'])
        self.assertEqual([r for r in roles if r == 'GM_KCD1_OBCHODNIK' or TRADE_STYLE.fullmatch(r)], ['GM_KCD1_OBCHODNIK'])
        self.assertEqual([r for r in roles if METAROLES.get(r) == 'SMLOUVANI'], ['GM_KCD1_SMLOUVANI_ZENA'])
        # Negotiation and the maintainer's own role stay; nothing generic but VYJEDNAVANI survives.
        self.assertIn('VYJEDNAVANI_ZENA', roles)
        self.assertIn('GM_NEUHOF_HORSE_TRADER', roles)
        self.assertFalse(set(generic['woman']) & set(roles))
        # Removing a role the keeper never had is a no-op, so the result is the same without the generic rule.
        self.assertEqual(keeper_roles(rule, GENERIC_CUSTOM, []), [r for r in roles if r not in generic['woman']])
        self.assertEqual(port_rule(rule, 'woman', generic['woman']), ([], []))
        with self.assertRaisesRegex(ValueError, 'generic shop rules changed'):
            generic_shop_roles(GENERIC_SHOP_XML.replace(b'shop_isUltraLightTrader_man', b'renamed'), GENERIC_CUSTOM, METAROLES)

    @unittest.skipUnless((GAME / 'Data/Tables.pak').is_file(), 'KCD2 required')
    def test_a_keeper_on_a_retail_character_takes_its_voice_from_kcd2s_character_table(self):
        from kcd1_shop_install import keeper_voices
        souls = (b'<database><souls><soul soul_name="neu_zdena" skald_character_name="char_GENERIC_WOMAN_MERCHANT_CZECH_03" />'
                 b'</souls></database>')
        files = {'Libs/Tables/rpg/soul__x.xml': souls}
        voices, groups = keeper_voices(files, files.get, GAME, ['neu_zdena'])
        self.assertEqual(voices, {'neu_zdena': 'aric'})
        self.assertIn('Merchants', groups['neu_zdena'])
        with self.assertRaisesRegex(ValueError, 'Cannot resolve the voice'):
            keeper_voices(files, files.get, GAME, ['nobody'])

    @unittest.skipUnless((GAME / 'Data/Tables.pak').is_file(), 'KCD2 required')
    def test_on_a_fresh_build_the_native_head_keepers_get_world_actor_contracts_character_first(self):
        from kcd1_shop_install import keeper_voices, pin_characters
        from upgrade_map import xml
        # The unified-7 job's rows: world_actor_contracts has not run yet, so no character.
        fresh = (b'<database><souls>'
                 b'<soul soul_name="neu_zdena" soul_archetype_id="1" social_class_id="6" voice_group_name="Merchants" '
                 b'soul_id="4ab79da2-dd95-a2e2-2672-554b62118681" />'
                 b'<soul soul_name="rato_innkeeper1" soul_archetype_id="0" social_class_id="22" voice_group_name="Merchants" '
                 b'soul_id="4ec32e5c-86c6-c8d8-8202-d41774882b80" />'
                 b'<soul soul_name="rat_pesek" soul_archetype_id="0" social_class_id="25" voice_group_name="Merchants" '
                 b'soul_id="40a95fd2-2055-9bd7-b5b9-06ef87aba2aa" />'
                 b'<soul soul_name="someone_else" soul_archetype_id="0" social_class_id="25" soul_id="1" />'
                 b'</souls></database>')
        path = 'Libs/Tables/rpg/soul__kingdomcomegluemapper.xml'
        people = ['neu_zdena', 'rato_innkeeper1', 'rat_pesek']
        # Unpinned, every keeper is named with the real reason, not just the first.
        with self.assertRaisesRegex(ValueError, r'neu_zdena: soul row has no skald_character_name; '
                                                r'rato_innkeeper1: .*; rat_pesek: '):
            keeper_voices({path: fresh}, {path: fresh}.get, GAME, people)
        tables = {path: ET.fromstring(fresh)}
        changed, report = pin_characters(tables, GAME, people)
        # The same characters the installed package carries after world_actor_contracts.
        self.assertEqual({r['person']: r['character'] for r in report},
                         {'neu_zdena': 'char_GENERIC_WOMAN_MERCHANT_CZECH_03',
                          'rato_innkeeper1': 'char_GENERIC_MAN_COMMONER_19', 'rat_pesek': 'char_GENERIC_MAN_COMMONER_07'})
        files = {path: xml(changed[path])}
        voices, _ = keeper_voices(files, files.get, GAME, people)
        self.assertEqual(voices, {'neu_zdena': 'aric', 'rato_innkeeper1': 'rlaz', 'rat_pesek': 'dosg'})
        # Souls outside the port stay for world_actor_contracts; a pinned soul is not pinned again.
        self.assertIsNone(next(s for s in tables[path].iter('soul') if s.get('soul_name') == 'someone_else').get('skald_character_name'))
        self.assertEqual(pin_characters(tables, GAME, people), ({}, []))

    def test_a_keeper_switches_to_its_kcd1_voice_on_a_copy_of_its_own_character(self):
        from kcd1_shop_install import CHARACTER_TABLE, switch_voices
        souls = {'Libs/Tables/rpg/soul__x.xml': ET.fromstring(
            b'<database><souls><soul soul_name="rat_pesek" skald_character_name="char_GENERIC_MAN_COMMONER_07" />'
            b'<soul soul_name="other" skald_character_name="char_GENERIC_MAN_COMMONER_07" /></souls></database>')}
        voices = {'149': ('dosg', ['Guards']), '86': ('ccla', ['Merchants']), '100105': ('rpro', [''])}
        characters = {'char_GENERIC_MAN_COMMONER_07': [dict(skald_character_name='char_GENERIC_MAN_COMMONER_07', age='2',
                                                          gender='0', voice_categories='generic christian', voice_id='149')]}
        changed, report = switch_voices(souls, None, voices, characters, {'rat_pesek': 'ccla'})
        rows = [s.attrib for s in ET.fromstring(changed['Libs/Tables/rpg/soul__x.xml']).iter('soul')]
        self.assertEqual([r['skald_character_name'] for r in rows], ['gm_voice_rat_pesek', 'char_GENERIC_MAN_COMMONER_07'])
        character = ET.fromstring(changed[CHARACTER_TABLE]).find('skald_characters/skald_character').attrib
        # Only the name and the voice change; the rest of the character is the keeper's own.
        self.assertEqual(character, dict(characters['char_GENERIC_MAN_COMMONER_07'][0],
                                         skald_character_name='gm_voice_rat_pesek', voice_id='86'))
        self.assertEqual((report[0]['previous_voice'], report[0]['voice']), ('dosg', 'ccla'))
        self.assertEqual(switch_voices(souls, None, voices, characters, {}), ({}, []))
        with self.assertRaisesRegex(ValueError, 'not a single KCD2 or imported voice'):
            switch_voices(souls, None, voices, characters, {'rat_pesek': 'nobody'})

    def test_a_keeper_whose_own_rule_opens_its_shop_keeps_that_as_its_one_trade_option(self):
        from kcd1_shop_install import own_trade, shop_dialog_roles
        miller = (b'<Database><Skald><FaderDialog Name="rattay_miller"><Dialogue NonSpeakerRoles="GM_RATTAY_MILLER">'
                  b'<Decision><Sequences><Sequence Name="trade" Type="Shop"><Decision><Sequences>'
                  b'<Sequence Name="open_shop" Type="OpenShop" /></Sequences></Decision></Sequence></Sequences>'
                  b'</Decision></Dialogue></FaderDialog></Skald></Database>')
        horses = miller.replace(b'Type="OpenShop"', b'Type="Horses"').replace(b'GM_RATTAY_MILLER', b'GM_NEUHOF_HORSE_TRADER')
        quests = {'Quests/GlueTravel/rattay_miller.xml': miller, 'Quests/GlueTravel/horse.xml': horses,
                  FOLDER + 'gm_kcd1_obchod.xml': miller.replace(b'GM_RATTAY_MILLER', b'GM_KCD1_OBCHODNIK')}
        roles = shop_dialog_roles(quests, {FOLDER + 'gm_kcd1_obchod.xml'})
        self.assertEqual(roles, {'GM_RATTAY_MILLER'})
        rule = ET.fromstring(RULE.replace(b'gm_person_1_role', b'GM_RATTAY_MILLER')).find('rules/rule')
        self.assertEqual(own_trade(rule, CUSTOM, roles), ['GM_RATTAY_MILLER'])
        port_rule(rule, 'man', trade=False)
        self.assertNotIn(('addRole', 'GM_KCD1_OBCHODNIK'), [(o.tag, o.get('name')) for o in rule.find('operations')])

    @unittest.skipUnless((SOURCE / 'Data/Tables.pak').is_file(), 'KCD1 required')
    def test_kcd1_voices_come_from_kcd1s_own_tables(self):
        from kcd1_shop_install import source_voices
        self.assertEqual(source_voices(SOURCE, ['rato_innkeeper1', 'rat_pesek', 'neu_zdena', 'ska_merchant1']),
                         {'rato_innkeeper1': 'rpro', 'rat_pesek': 'ccla', 'neu_zdena': 'aric', 'ska_merchant1': 'rpro'})

    def test_haggle_guard_sees_native_roles_hidden_in_custom_operations(self):
        root = ET.fromstring(RULE.replace(b'<addRole name="SMLOUVANI_MUZ" />', b'<addShopRoles_essential_man />'))
        rule = root.find('rules/rule')
        port_rule(rule, 'man')
        self.assertEqual(haggle_roles(rule, METAROLES, CUSTOM), ['SMLOUVANI_MUZ', 'GM_KCD1_SMLOUVANI_MUZ'])

    def test_role_rows_give_only_the_haggle_roles_the_smlouvani_metarole(self):
        rows = {r.get('role_name'): r.get('metarole_name') for r in ET.fromstring(role_rows()).iter('role')}
        self.assertEqual(rows, {'GM_KCD1_OBCHODNIK': 'NPC', 'GM_KCD1_POZDRAV_MUZ': 'NPC', 'GM_KCD1_POZDRAV_ZENA': 'NPC',
                                'GM_KCD1_SMLOUVANI_MUZ': 'SMLOUVANI', 'GM_KCD1_SMLOUVANI_ZENA': 'SMLOUVANI',
                                'GM_KCD1_ROZLOUCENI_MUZ': 'ROZLOUCENI', 'GM_KCD1_ROZLOUCENI_ZENA': 'ROZLOUCENI',
                                **{f'GM_KCD1_LOUCENI_PO_NAKUPU_{k}_{s}': f'POZDRAV_PO_NAKUPU_{k}'
                                   for k in ('ZADNY', 'BEZNY', 'VELKY') for s in ('MUZ', 'ZENA')}})

    def test_keepers_own_talk_dialogs_allow_the_farewell(self):
        from kcd1_shop_install import allow_farewell
        talk = (b'<Database><Skald><FaderDialog Name="rattay_miller"><Dialogue Initiator="Player" '
                b'NonSpeakerRoles="GM_RATTAY_MILLER" AllowGreeting="false" AllowFarewell="false" /></FaderDialog>'
                b'</Skald></Database>')
        opened = ET.fromstring(allow_farewell(talk, {'GM_RATTAY_MILLER'})).find('Skald/FaderDialog/Dialogue')
        self.assertEqual((opened.get('AllowFarewell'), opened.get('AllowGreeting')), ('true', 'false'))
        # A dialog of a role outside the keepers' own (retail negotiation) and an already open one stay.
        self.assertIsNone(allow_farewell(talk.replace(b'GM_RATTAY_MILLER', b'VYJEDNAVANI_MUZ'), {'GM_RATTAY_MILLER'}))
        self.assertIsNone(allow_farewell(talk.replace(b'AllowFarewell="false"', b'AllowFarewell="true"'), {'GM_RATTAY_MILLER'}))

    def test_farewell_is_fed_by_the_kcd2_state_node_and_declared_in_the_module(self):
        from kcd1_shop_install import farewell_nodes, module
        state, dialog = farewell_nodes('woman', ['reputace_dobra', 'reputace_nizka'])
        self.assertEqual((state.tag, state.get('Namespace')), ('timeandplayerstate', 'utils.greetings_utils'))
        self.assertEqual([e.attrib for e in state.findall('Edge')],
                         [{'From': 'gm_kcd1_rozlouceni_zena.GM_KCD1_ROZLOUCENI_ZENA', 'To': 'npc'}])
        self.assertEqual([(e.get('From'), e.get('To')) for e in dialog.findall('Edge')],
                         [('gm_kcd1_rozlouceni_zena_state.reputace_dobra', 'reputace_dobra'),
                          ('gm_kcd1_rozlouceni_zena_state.reputace_nizka', 'reputace_nizka')])
        with self.assertRaisesRegex(ValueError, 'Farewell port without'):
            farewell_nodes('man', ['npc_zna_jindricha'])
        graph = ET.fromstring(module(NATIVE_MODULE, {'man': [], 'woman': []}, {'man': ['reputace_dobra'], 'woman': []}))
        files = [d.get('File') for d in graph.iter('Definition')]
        self.assertIn('gm_kcd1_rozlouceni_muz.xml', files)
        self.assertIn('gm_kcd1_rozlouceni_zena.xml', files)
        self.assertEqual(len(graph.find('Skald/Gameplay/Nodes').findall('gm_kcd1_rozlouceni_muz')), 1)

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
        # Every ported line has its KCD1 facial track, whether this run adds them or the package already has them:
        # 510 conversation and 110 farewell lines, and rat_pesek's 127 ccla lines.
        self.assertEqual(report['facial_lines'], 747)
        self.assertEqual(report['facial_missing'], [])
        # Every keeper speaks in its KCD1 voice and drops the generic trader roles.
        keepers = {k['person']: k for k in report['keepers']}
        self.assertEqual({p: k['voice'] for p, k in keepers.items() if p in ('neu_zdena', 'rato_innkeeper1', 'rat_pesek')},
                         {'neu_zdena': 'aric', 'rato_innkeeper1': 'rpro', 'rat_pesek': 'ccla'})
        self.assertTrue(all('OBCHODNIK_Z_DIALOGU_MUZ' in k['generic_removed'] or 'OBCHODNICE_Z_DIALOGU_ZENA' in k['generic_removed']
                            for k in keepers.values()))
        # The innkeeper and the miller keep the maintainer's shop dialog as their one Trade option.
        self.assertEqual((keepers['rato_innkeeper1']['trade'], keepers['rat_pesek']['trade']),
                         ('GMTRAVEL_RATTAY_INNKEEPER', 'GM_RATTAY_MILLER'))
        if report['changed']:
            if HOST in changes[TRAVEL]:
                # Unported install: the whole port.
                self.assertEqual(len(report['recordings_added']), 747)
            else:
                # A v2 port (no farewell) adds the 110 farewell recordings, every port before the innkeeper
                # and the miller adds Pesek's 127 ccla lines.
                self.assertIn(len(report['recordings_added']), (237, 127))
                self.assertEqual(report['facial_tracks_added'], len(report['recordings_added']))
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
