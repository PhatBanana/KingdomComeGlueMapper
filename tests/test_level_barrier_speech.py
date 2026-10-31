"""Henry's native level-barrier bark joins the project voice namespace with retail's own audio scope."""
from pathlib import Path
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from campaign_dialogue_runtime import voice_namespace
from level_barrier_speech import DEFINITION, DIALOG, FOLDER, HOST, MODULE, PARENT, SCOPE, STORM, TRAVEL, WRAPPER, plan, upgrade
from setup_campaign import digest

PROJECT = (b'<Database><Skald><Project Name="GlueTravel_kcd1"><Assets/><Definitions>'
           b'<Definition File="smithing_voice/open_world.xml"/></Definitions>'
           b'<Nodes><open_world Name="open_world"/></Nodes></Project></Skald></Database>')
OPEN_WORLD = (b'<Database><Skald><Gameplay Name="open_world" VoiceNamespace="true"><Definitions>'
              b'<Definition File="minihry.xml"/><Definition File="../church_prayer/perky.xml"/></Definitions>'
              b'<Nodes><minihry Name="minihry"/><perky Name="perky"/></Nodes></Gameplay></Skald></Database>')
STORM_XML = b'<storm><tasks><task name="roles" class="roles"><source path="roles\\dude.xml"/></task></tasks></storm>'
NATIVE = 'Quests/Final/Barbora/open_world/'
PARENT_XML = b'''<?xml version="1.0" encoding="utf-8"?>
<Database Name="brambora"><Skald><Gameplay Name="stavy_hrace_unavahlad" VoiceNamespace="true">
<Ports><Port Name="m03_socky" Direction="In" Type="wh::questmodule::QuestProgress"/></Ports>
<Definitions><Definition File="stavy_hrace_unavahlad/hlad.xml"/><Definition File="stavy_hrace_unavahlad/narazeni_na_barieru_voda_level.xml"/></Definitions>
<Nodes><hlad Name="hlad"/><narazeni_na_barieru_voda_level Name="narazeni_na_barieru_voda_level"><Edge From="m03_socky" To="m03_socky"/></narazeni_na_barieru_voda_level></Nodes>
</Gameplay></Skald></Database>'''
MODULE_XML = b'''<Database Name="brambora"><Skald><Module Name="narazeni_na_barieru_voda_level">
<Ports><Port Name="m03_socky" Direction="In" Type="wh::questmodule::QuestProgress"/></Ports>
<Definitions><Definition File="narazeni_na_barieru_voda_level/jindrich_narazil_na_level_barieru.xml"/><Definition File="narazeni_na_barieru_voda_level/jindrich_narazil_na_hlubokou_vodu.xml"/></Definitions>
<Nodes><jindrich_narazil_na_hlubokou_vodu Name="jindrich_narazil_na_hlubokou_vodu"><Edge From="stancecheck1.IsInStance" To="onhorse"/></jindrich_narazil_na_hlubokou_vodu>
<jindrich_narazil_na_level_barieru Name="jindrich_narazil_na_level_barieru"/>
<Function Name="stancecheck1" MethodName="wh::xgenaimodule::StanceCheck"><Asset Name="Souls" Alias="player_any"/></Function></Nodes>
</Module></Skald></Database>'''
DIALOG_XML = b'''<?xml version="1.0" encoding="utf-8"?>
<Database Name="brambora"><Skald><Dialog Name="jindrich_narazil_na_level_barieru">
<Text StringName="jindrich_narazi_na_level__w49Q" Text="design note"/>
<Dialogue Type="ingame monolog" TechnicalStatus="Enabled" Initiator="NonPlayer" ForceMood="noScope">
<Decision Name="dec1" Priority="General"><Sequences><Sequence EndType="Decision" Name="seq1"><Elements><Response Role="JINDRICH_NEMUZE_Z_MAPY"/></Elements>
<Decision Name="dec2" Priority="General" Autoselect="true"><Sequences>
<Sequence EndType="EndDialogue" Name="seq2"><Elements><Response Role="JINDRICH_NEMUZE_Z_MAPY"><Parenthetical><Text StringName="jind_jindrich__pro_sebe_65HE" Text="pro sebe"/></Parenthetical><Text StringName="jind_jindrich__variace_1_YMnp" Text="Ne."/></Response></Elements></Sequence>
<Sequence EndType="EndDialogue" Name="seq3"><Elements><Response Role="JINDRICH_NEMUZE_Z_MAPY"><Text StringName="jind_jindrich__variace_2_xzY0" Text="Zpet."/></Response></Elements></Sequence>
</Sequences></Decision></Sequence></Sequences></Decision></Dialogue></Dialog></Skald></Database>'''
SURFACES = (b'<SurfaceTypes><SurfaceType name="mat_default"/><SurfaceType name="mat_level_barrier"><Physics friction="0.5"/>'
            b'<Barrier distance="10" slowdown="1" monologMetaroleId="HRAC_NEMUZE_Z_MAPY"/></SurfaceType></SurfaceTypes>')
DUDE = (b'<storm><rules><rule name="player"><selectors><isPlayer/></selectors><operations><addRole name="HRAC"/></operations></rule>'
        b'<rule name="player_henry"><selectors><isPlayerHenry/></selectors><operations><addRole name="HENRY"/>'
        b'<addRole name="JINDRICH_NEMUZE_Z_MAPY"/></operations></rule></rules></storm>')
METAROLES = (b'<database name="barbora"><metaroles version="2"><metarole metarole_name="HRAC_NEMUZE_DO_HLUBOKE_VODY"/>'
             b'<metarole metarole_name="HRAC_NEMUZE_Z_MAPY"/></metaroles></database>')
RECORDINGS = ('dialog/open_world/stavy_hrace_unavahlad/tmck_jind_jindrich__variace_1_YMnp.ogg',
              'dialog/open_world/stavy_hrace_unavahlad/tmck_jind_jindrich__variace_2_xzY0.ogg',
              'dialog/open_world/stavy_hrace_unavahlad/emac_jind_jindrich__variace_2_xzY0.ogg',
              # A nested module's recording and another scope's copy never satisfy the barrier line.
              'dialog/open_world/stavy_hrace_unavahlad/hlad/tmck_jind_jindrich__variace_1_YMnp.ogg',
              'dialog/kcd1_travel/open_world/stavy_hrace_unavahlad/tmck_jind_jindrich__variace_1_YMnp.ogg')


def pak(path, entries):
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, 'w') as z:
        for name, blob in entries.items():
            z.writestr(name, blob)


class LevelBarrierSpeechTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        self.package, self.game = root / 'mod', root / 'game'
        self.travel = {HOST: PROJECT, WRAPPER: OPEN_WORLD, STORM: STORM_XML, 'Libs/keep.xml': b'<keep/>'}
        self.scripts = {NATIVE + 'stavy_hrace_unavahlad.xml': PARENT_XML,
                        NATIVE + 'stavy_hrace_unavahlad/narazeni_na_barieru_voda_level.xml': MODULE_XML,
                        NATIVE + 'stavy_hrace_unavahlad/narazeni_na_barieru_voda_level/jindrich_narazil_na_level_barieru.xml': DIALOG_XML}
        self.gamedata = {'Libs/MaterialEffects/SurfaceTypes.xml': SURFACES, 'Libs/Storm/roles/dude.xml': DUDE}
        self.tables = {'Libs/Tables/rpg/metarole.xml': METAROLES}
        self.recordings = dict.fromkeys(RECORDINGS, b'OggS')

    def write(self):
        pak(self.package / TRAVEL, self.travel)
        pak(self.game / 'Data/Scripts.pak', self.scripts)
        pak(self.game / 'Data/IPL_GameData.pak', self.gamedata)
        pak(self.game / 'Data/Tables.pak', self.tables)
        pak(self.game / 'Localization/IPL_English.pak', self.recordings)
        return (self.package / TRAVEL).read_bytes()

    def entries(self):
        with zipfile.ZipFile(self.package / TRAVEL) as z:
            return {n: z.read(n) for n in z.namelist()}

    def test_registers_reduced_hierarchy_under_the_project_voice_namespace(self):
        self.write()
        progress = []
        files, report = upgrade(self.package, self.game, notify=lambda *a: progress.append(a))
        self.assertEqual(files, {TRAVEL: digest(self.package / TRAVEL)})
        self.assertEqual([(p[1], p[2]) for p in progress], [(0, 1), (1, 1)])
        self.assertEqual(report['status'], 'registered')
        self.assertEqual(report['voices'], ['emac', 'tmck'])
        self.assertEqual([line['text'] for line in report['lines']],
                         ['jind_jindrich__variace_1_YMnp', 'jind_jindrich__variace_2_xzY0'])
        self.assertEqual(report['lines'][0]['recordings'], [RECORDINGS[0].lower()])
        self.assertEqual(report['barrier'], {'distance': '10', 'slowdown': '1', 'monologMetaroleId': 'HRAC_NEMUZE_Z_MAPY'})
        self.assertEqual(report['voice_scope'], 'dialog/open_world/stavy_hrace_unavahlad/')
        self.assertFalse(report['runtime_verified'])
        entries = self.entries()
        self.assertEqual(entries['Libs/keep.xml'], b'<keep/>')
        self.assertEqual(entries[HOST], PROJECT)
        wrapper = ET.fromstring(entries[WRAPPER]).find('Skald/Gameplay')
        self.assertEqual(wrapper.get('VoiceNamespace'), 'true')
        self.assertEqual([d.get('File') for d in wrapper.findall('Definitions/Definition')],
                         ['minihry.xml', '../church_prayer/perky.xml', DEFINITION])
        self.assertEqual([(n.tag, n.get('Name')) for n in wrapper.find('Nodes')],
                         [('minihry', 'minihry'), ('perky', 'perky'), (PARENT, PARENT)])
        # The native dialog is copied byte for byte; the two containers are reduced to it.
        self.assertEqual(entries[FOLDER + DIALOG + '.xml'], DIALOG_XML)
        parent = ET.fromstring(entries[FOLDER + PARENT + '.xml']).find('Skald/Gameplay')
        self.assertEqual((parent.get('Name'), parent.get('VoiceNamespace')), (PARENT, 'true'))
        self.assertEqual([d.get('File') for d in parent.findall('Definitions/Definition')], [MODULE + '.xml'])
        module = ET.fromstring(entries[FOLDER + MODULE + '.xml']).find('Skald/Module')
        self.assertIsNone(module.get('VoiceNamespace'))
        self.assertIsNone(module.find('Ports'))
        self.assertEqual([d.get('File') for d in module.findall('Definitions/Definition')], [DIALOG + '.xml'])
        self.assertEqual([(n.tag, n.get('Name'), len(n)) for n in module.find('Nodes')], [(DIALOG, DIALOG, 0)])
        graphs = {n: b for n, b in entries.items() if n.startswith('Quests/')}
        self.assertEqual(voice_namespace(graphs, FOLDER + DIALOG + '.xml'), ('open_world', PARENT))
        self.assertEqual('dialog/' + '/'.join(voice_namespace(graphs, FOLDER + DIALOG + '.xml')) + '/', SCOPE)
        before = (self.package / TRAVEL).read_bytes()
        files, report = upgrade(self.package, self.game)
        self.assertEqual((files, report['status'], report['changed']), ({}, 'present', []))
        self.assertEqual((self.package / TRAVEL).read_bytes(), before)

    def test_missing_native_recording_fails_before_writing(self):
        self.recordings = {n: b'OggS' for n in RECORDINGS if 'variace_2' not in n}
        before = self.write()
        with self.assertRaisesRegex(ValueError, 'Missing native level barrier recording for jind_jindrich__variace_2_xzY0'):
            upgrade(self.package, self.game)
        self.assertEqual((self.package / TRAVEL).read_bytes(), before)

    def test_changed_retail_hook_role_or_metarole_fails(self):
        self.gamedata['Libs/MaterialEffects/SurfaceTypes.xml'] = SURFACES.replace(b'HRAC_NEMUZE_Z_MAPY', b'HRAC_JINY')
        self.write()
        with self.assertRaisesRegex(ValueError, 'no longer requests'):
            plan(self.package, self.game)
        self.gamedata['Libs/MaterialEffects/SurfaceTypes.xml'] = SURFACES
        self.gamedata['Libs/Storm/roles/dude.xml'] = DUDE.replace(b'<addRole name="JINDRICH_NEMUZE_Z_MAPY"/>', b'')
        self.write()
        with self.assertRaisesRegex(ValueError, 'no longer gives Henry'):
            plan(self.package, self.game)
        self.gamedata['Libs/Storm/roles/dude.xml'] = DUDE
        self.tables['Libs/Tables/rpg/metarole.xml'] = METAROLES.replace(b'<metarole metarole_name="HRAC_NEMUZE_Z_MAPY"/>', b'')
        self.write()
        with self.assertRaisesRegex(ValueError, 'metarole table lacks'):
            plan(self.package, self.game)

    def test_native_dialog_with_inputs_or_other_roles_is_rejected(self):
        path = NATIVE + 'stavy_hrace_unavahlad/narazeni_na_barieru_voda_level/jindrich_narazil_na_level_barieru.xml'
        self.scripts[path] = DIALOG_XML.replace(b'<Dialogue ', b'<Ports><Port Name="onhorse" Direction="In" Type="bool"/></Ports><Dialogue ')
        self.write()
        with self.assertRaisesRegex(ValueError, 'depends on inputs'):
            plan(self.package, self.game)
        self.scripts[path] = DIALOG_XML.replace(b'Role="JINDRICH_NEMUZE_Z_MAPY"><Text StringName="jind_jindrich__variace_2_xzY0"',
                                                b'Role="BOHUTA_NEMUZE_Z_MAPY"><Text StringName="jind_jindrich__variace_2_xzY0"')
        self.write()
        with self.assertRaisesRegex(ValueError, 'other roles'):
            plan(self.package, self.game)

    def test_changed_native_layout_is_rejected(self):
        self.scripts[NATIVE + 'stavy_hrace_unavahlad.xml'] = PARENT_XML.replace(
            b'<Definition File="stavy_hrace_unavahlad/narazeni_na_barieru_voda_level.xml"/>', b'')
        self.write()
        with self.assertRaisesRegex(ValueError, 'layout changed'):
            plan(self.package, self.game)

    def test_missing_project_registration_or_player_roles_fails(self):
        del self.travel[WRAPPER]
        self.write()
        with self.assertRaisesRegex(ValueError, 'Project voice namespace registration missing'):
            plan(self.package, self.game)
        self.travel[WRAPPER] = OPEN_WORLD
        self.travel[STORM] = b'<storm><tasks><task name="roles" class="roles"><source path="roles\\world\\base.xml"/></task></tasks></storm>'
        self.write()
        with self.assertRaisesRegex(ValueError, 'native player roles'):
            plan(self.package, self.game)

    def test_existing_registration_with_wiring_requires_review(self):
        self.travel[WRAPPER] = OPEN_WORLD.replace(
            b'<perky Name="perky"/>', b'<perky Name="perky"/><stavy_hrace_unavahlad Name="stavy_hrace_unavahlad"><Constant Name="x" Value="1"/></stavy_hrace_unavahlad>')
        self.write()
        with self.assertRaisesRegex(ValueError, 'requires review'):
            plan(self.package, self.game)

    def test_game_folder_is_required(self):
        self.write()
        with self.assertRaisesRegex(ValueError, 'Game folder required'):
            upgrade(self.package, None)


if __name__ == '__main__':
    unittest.main()
