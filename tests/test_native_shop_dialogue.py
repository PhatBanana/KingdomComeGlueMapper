"""Converted shopkeepers keep the generated trade dialog and gain the native shop greeting."""
from pathlib import Path
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from native_shop_dialogue import ENTRY, LEVEL, TRAVEL, generated, plan, upgrade
from region_travel_merchant import dialogue
from setup_campaign import digest

READY_ID, IDLE_ID = 'aaaaaaaa-0000-0000-0000-000000000001', 'bbbbbbbb-0000-0000-0000-000000000002'
MISSION = f'''<Objects>
<Entity Name="shop_1" EntityClass="Shop" EntityGuid="000000a1-0000-0000"/>
<Entity Name="shop_2" EntityClass="Shop" EntityGuid="000000a2-0000-0000"/>
<Entity Name="shop_3" EntityClass="Shop" EntityGuid="000000a3-0000-0000"/>
<Entity Name="trader" EntityClass="NPC" EntityGuid="000000b1-0000-0000"><EntityLinks><Link Name="shopKeeper" TargetGuid="000000a1-0000-0000"/></EntityLinks></Entity>
<Entity Name="grocer" EntityClass="NPC_Female" EntityGuid="000000b2-0000-0000"><EntityLinks><Link Name="shopKeeper" TargetGuid="000000a2-0000-0000"/></EntityLinks></Entity>
<Entity Name="idler" EntityClass="NPC" EntityGuid="000000b3-0000-0000"><EntityLinks><Link Name="shopKeeper" TargetGuid="000000a3-0000-0000"/></EntityLinks></Entity>
<Entity Name="gm_schedule_trader_1" EntityClass="SmartObjectHolder"><Properties guidSmartObjectType="{READY_ID}"/></Entity>
<Entity Name="gm_schedule_grocer_2" EntityClass="SmartObjectHolder"><Properties guidSmartObjectType="{READY_ID.upper()}"/></Entity>
<Entity Name="gm_schedule_idler_3" EntityClass="SmartObjectHolder"><Properties guidSmartObjectType="{IDLE_ID}"/></Entity>
</Objects>'''.encode()
TEMPLATES = f'''<database><SmartEntityTemplates>
<SmartEntityTemplate DatabaseId="{READY_ID}"><BehaviorTemplates><SmartBehaviorTemplate Name="seller"><TreeLocation FileName="profession/seller/so_seller.xml" TreeName="seller"/></SmartBehaviorTemplate></BehaviorTemplates></SmartEntityTemplate>
<SmartEntityTemplate DatabaseId="{IDLE_ID}"><BehaviorTemplates><SmartBehaviorTemplate Name="idle"><TreeLocation FileName="idle/stand.xml" TreeName="stand"/></SmartBehaviorTemplate></BehaviorTemplates></SmartEntityTemplate>
</SmartEntityTemplates></database>'''.encode()
SELLER_TREE = b'<BehaviorTrees><BehaviorTree name="seller"><Root><Sequence><EntityContextElement context="shop_sellerReadyToSell"/></Sequence></Root></BehaviorTree></BehaviorTrees>'
IDLE_TREE = b'<BehaviorTrees><BehaviorTree name="stand"><Root><Wait/></Root></BehaviorTree></BehaviorTrees>'


def native_dialog(role):
    return (f'<Database><Skald><FaderDialog Name="n"><Dialogue><Decision Name="d" Priority="Shop"><Sequences>'
            f'<Sequence Name="s" Type="Shop" EntryCondition="!Port(\'shop_denied\') AND Port(\'seller_in_shop\')"><Elements>'
            f'<Response Role="HRAC"><Text StringName="merc_henry_x"/></Response><Response Role="{role}"><Text StringName="merc_y"/></Response>'
            f'</Elements></Sequence></Sequences></Decision></Dialogue></FaderDialog></Skald></Database>').encode()


OPERATIONS = (b'<storm><customOperations>'
              b'<customOperation name="addShopRoles_greeting_man"><addRole name="OBCHODNIK_ZDRAVI_JINDRU_NEBO_BOHUTU"/></customOperation>'
              b'<customOperation name="addShopRoles_greeting_woman"><addRole name="OBCHODNICE_ZDRAVI_JINDRU_NEBO_BOHUTU"/></customOperation>'
              b'</customOperations></storm>')


def rule(stem, person):
    return (f'<storm><rules><rule name="{stem}_roles"><selectors><hasName name="{person}"/></selectors><operations>'
            f'<addRole name="{stem}_role"/><addRole name="SMLOUVANI_MUZ"/></operations></rule></rules></storm>').encode()


def entry(names):
    definitions = ''.join(f'<Definition File="{n}.xml"/>' for n in names)
    nodes = ''.join(f'<{n} Name="{n}"/>' for n in names)
    return (f'<Database><Skald><Level Name="kcd1_travel"><Definitions><Definition File="world/open_world.xml"/>{definitions}</Definitions>'
            f'<Nodes><open_world Name="open_world"/>{nodes}</Nodes></Level></Skald></Database>').encode()


def pak(path, entries):
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, 'w') as z:
        for name, blob in entries.items():
            z.writestr(name, blob)


class NativeShopDialogueTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        self.package, self.game = root / 'mod', root / 'game'
        names = ['gm_source_shop_1_trade', 'gm_source_shop_2_trade', 'gm_source_shop_3_trade', 'gm_tavern_trade']
        folder = ENTRY.rsplit('/', 1)[0] + '/'
        self.travel = {
            ENTRY: entry(names),
            folder + 'gm_source_shop_1_trade.xml': dialogue('trader', role='p1_role', name='gm_source_shop_1_trade', diagnostics=False),
            folder + 'gm_source_shop_2_trade.xml': dialogue('grocer', role='p2_role', name='gm_source_shop_2_trade', diagnostics=False),
            folder + 'gm_source_shop_3_trade.xml': dialogue('idler', role='p3_role', name='gm_source_shop_3_trade', diagnostics=False),
            folder + 'gm_tavern_trade.xml': dialogue('innkeeper', role='p4_role', name='gm_tavern_trade', diagnostics=False),
            'Libs/Storm/roles/p1.xml': rule('p1', 'trader'), 'Libs/Storm/roles/p2.xml': rule('p2', 'grocer'),
            'Libs/Storm/roles/p3.xml': rule('p3', 'idler'),
            'Libs/Tables/ai/smartEntity/SmartEntity__gm_work.xml': TEMPLATES, 'AI/idle/stand.xml': IDLE_TREE}
        self.scripts = {'Quests/Final/Barbora/open_world/shop/nakupovani_z_dialogu_muz.xml': native_dialog('OBCHODNIK_Z_DIALOGU_MUZ'),
                        'Quests/Final/Barbora/open_world/shop/nakupovani_z_dialogu_zena.xml': native_dialog('OBCHODNICE_Z_DIALOGU_ZENA'),
                        'AI/profession/seller/so_seller.xml': SELLER_TREE}
        self.gamedata = {'Libs/Storm/common/roles_operations.xml': OPERATIONS}

    def write(self):
        pak(self.package / TRAVEL, self.travel)
        pak(self.package / LEVEL, {'objects_mission0.xml': MISSION})
        pak(self.game / 'Data/Scripts.pak', self.scripts)
        pak(self.game / 'Data/IPL_GameData.pak', self.gamedata)
        pak(self.game / 'Data/Tables.pak', {'Libs/Tables/ai/smartEntity/empty.xml': b'<database/>'})
        return (self.package / TRAVEL).read_bytes()

    def entries(self):
        with zipfile.ZipFile(self.package / TRAVEL) as z:
            return {n: z.read(n) for n in z.namelist()}

    def operations(self, entries, name):
        return [(o.tag, o.get('name')) for o in ET.fromstring(entries[name]).find('rules/rule/operations')]

    def test_generated_shape_is_recognised_and_a_spoken_dialog_is_not(self):
        self.assertEqual(generated(dialogue('trader', role='p1_role', name='x', diagnostics=False)), ('trader', 'p1_role'))
        self.assertIsNone(generated(native_dialog('OBCHODNIK_Z_DIALOGU_MUZ')))

    def test_ready_keepers_greet_and_keep_the_generated_trade_dialog(self):
        before = self.write()
        progress = []
        files, report = upgrade(self.package, self.game, notify=lambda *a: progress.append(a))
        self.assertEqual(files, {TRAVEL: digest(self.package / TRAVEL)})
        self.assertEqual([(p[1], p[2]) for p in progress], [(0, 1), (1, 1)])
        self.assertEqual(report['greeted'], ['grocer', 'trader'])
        status = {row['dialog']: row['status'] for row in report['dialogs']}
        self.assertEqual(status, {'gm_source_shop_1_trade': 'greeting', 'gm_source_shop_2_trade': 'greeting',
                                  'gm_source_shop_3_trade': 'no_ready_to_sell_job', 'gm_tavern_trade': 'out_of_scope'})
        self.assertFalse(report['runtime_verified'])
        entries = self.entries()
        folder = ENTRY.rsplit('/', 1)[0] + '/'
        # Trade must not depend on shop_sellerReadyToSell: every generated dialog stays registered.
        self.assertEqual(sorted(entries), sorted(self.travel))
        self.assertEqual(entries[ENTRY], self.travel[ENTRY])
        for number, person in (('1', 'trader'), ('2', 'grocer')):
            blob = entries[folder + f'gm_source_shop_{number}_trade.xml']
            body = ET.fromstring(blob).find('Skald/FaderDialog/Dialogue')
            self.assertEqual(body.get('AllowGreeting'), 'true')
            self.assertEqual(body.get('AllowFarewell'), 'false')
            self.assertEqual(generated(blob), (person, f'p{number}_role'))
            self.assertEqual(len([s for s in body.iter('Sequence') if s.get('Type') == 'OpenShop']), 1)
        for name in ('gm_source_shop_3_trade.xml', 'gm_tavern_trade.xml'):
            self.assertEqual(entries[folder + name], self.travel[folder + name])
        self.assertEqual(self.operations(entries, 'Libs/Storm/roles/p1.xml'),
                         [('addRole', 'p1_role'), ('addRole', 'SMLOUVANI_MUZ'), ('addShopRoles_greeting_man', None)])
        self.assertEqual(self.operations(entries, 'Libs/Storm/roles/p2.xml'),
                         [('addRole', 'p2_role'), ('addRole', 'SMLOUVANI_MUZ'), ('addShopRoles_greeting_woman', None)])
        self.assertEqual(entries['Libs/Storm/roles/p3.xml'], rule('p3', 'idler'))
        after = (self.package / TRAVEL).read_bytes()
        self.assertNotEqual(after, before)
        files, report = upgrade(self.package, self.game)
        self.assertEqual((files, report['changed']), ({}, []))
        self.assertEqual((self.package / TRAVEL).read_bytes(), after)

    def test_spoken_trade_role_from_version_1_is_removed(self):
        self.travel['Libs/Storm/roles/p1.xml'] = self.travel['Libs/Storm/roles/p1.xml'].replace(
            b'</operations>', b'<addRole name="OBCHODNIK_Z_DIALOGU_MUZ"/><addShopRoles_greeting_man/></operations>')
        self.write()
        changes, report = plan(self.package, self.game)
        row = {r['person']: r for r in report['dialogs']}['trader']
        self.assertEqual((row['added'], row['removed_roles']), ([], ['OBCHODNIK_Z_DIALOGU_MUZ']))
        self.assertEqual(self.operations(changes, 'Libs/Storm/roles/p1.xml'),
                         [('addRole', 'p1_role'), ('addRole', 'SMLOUVANI_MUZ'), ('addShopRoles_greeting_man', None)])

    def test_keeper_without_own_roles_rule_keeps_the_generated_dialog(self):
        del self.travel['Libs/Storm/roles/p1.xml']
        self.write()
        _, report = plan(self.package, self.game)
        self.assertEqual({r['person']: r['status'] for r in report['dialogs'] if r['person'] in ('trader', 'grocer')},
                         {'trader': 'no_roles_rule', 'grocer': 'greeting'})

    def test_wired_generated_dialog_is_left_alone(self):
        self.travel[ENTRY] = self.travel[ENTRY].replace(b'<open_world Name="open_world"/>',
            b'<open_world Name="open_world"><Edge From="gm_source_shop_1_trade.dialog_started" To="x"/></open_world>')
        self.write()
        changes, report = plan(self.package, self.game)
        self.assertEqual({r['dialog']: r['status'] for r in report['dialogs']}['gm_source_shop_1_trade'], 'wired_dialog')
        self.assertNotIn(ENTRY.rsplit('/', 1)[0] + '/gm_source_shop_1_trade.xml', changes)

    def test_changed_native_dialog_or_greeting_operation_fails_before_writing(self):
        self.scripts['Quests/Final/Barbora/open_world/shop/nakupovani_z_dialogu_zena.xml'] = native_dialog('JINA_ROLE')
        before = self.write()
        with self.assertRaisesRegex(ValueError, 'Native spoken trade dialog changed'):
            upgrade(self.package, self.game)
        self.assertEqual((self.package / TRAVEL).read_bytes(), before)
        self.scripts['Quests/Final/Barbora/open_world/shop/nakupovani_z_dialogu_zena.xml'] = native_dialog('OBCHODNICE_Z_DIALOGU_ZENA')
        self.gamedata['Libs/Storm/common/roles_operations.xml'] = OPERATIONS.replace(b'OBCHODNICE_ZDRAVI', b'JINA_ZDRAVI')
        self.write()
        with self.assertRaisesRegex(ValueError, 'greeting operation changed'):
            plan(self.package, self.game)

    def test_game_folder_is_required(self):
        self.write()
        with self.assertRaisesRegex(ValueError, 'Game folder required'):
            upgrade(self.package, None)


if __name__ == '__main__':
    unittest.main()
