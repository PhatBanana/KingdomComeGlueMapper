import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from world_gameplay_basis import apply, NativeGraphs
from region_travel import guid


class WorldGameplayBasisTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        self.script_path = root / 'scripts.pak'
        self.native_path = root / 'level.pak'
        self.native_files = {
            'quests/final/barbora.xml': b'<Database><Skald><Project Name="Barbora"><Assets><SoulAsset Name="player" SharedSoulGuids="player-soul"/><SoulAsset Name="player_any" SharedSoulGuids="player-group"/></Assets></Project></Skald></Database>',
            'quests/final/barbora/open_world.xml': b'<Database><Skald><Gameplay Name="open_world"><Definitions><Definition File="open_world/combat.xml"/></Definitions><Nodes><combat Name="combat"/></Nodes><Assets><SmartObjectAsset Name="openworld"/></Assets></Gameplay></Skald></Database>',
            'quests/final/barbora/open_world/combat.xml': b'<Database><Skald><Gameplay Name="combat"><Assets><DialogueHolderAsset Name="surrenderDH"/></Assets><Nodes><LinkEffect Name="bind"><Asset Name="From" Alias="openworld"/><Asset Name="To" Alias="player_any"/></LinkEffect></Nodes></Gameplay></Skald></Database>'}
        self.write_scripts()
        with zipfile.ZipFile(self.native_path, 'w') as z:
            z.writestr('objects_mission0.xml', '<Objects><Entity Name="open_world" EntityClass="SmartObjectHolder" Pos="999,999,999"><EntityLinks><Link TargetId="999" Name="regional_service"/></EntityLinks></Entity><Entity Name="surrenderHolder" EntityClass="DialogueHolder" Pos="888,888,888"/></Objects>')
        self.files = {'objects_mission0.xml': b'<Objects><Entity Name="test_level" EntityClass="LevelHolder" EntityId="1" EntityGuid="00000001-0000-0000" Pos="10,20,30"/><Entity Name="sa_land" EntityClass="SmartAreaShape" EntityId="2" EntityGuid="00000002-0000-0000" Pos="0,0,-50"/></Objects>',
                      'waitinglinks.xml': b'<StaticLinksInfo version="1"><WaitingLinks/></StaticLinksInfo>', 'quest_state': b'preserve'}
        self.graphs = {'Quests/GlueTravel/entry/test_level.xml': b'<Database><Skald><Level Name="test_level"><Nodes><State Name="existing_quest"/></Nodes></Level></Skald></Database>', 'unrelated.xml': b'preserve'}

    def write_scripts(self):
        with zipfile.ZipFile(self.script_path, 'w') as z:
            for path, data in self.native_files.items(): z.writestr(path, data)

    def run_apply(self):
        with zipfile.ZipFile(self.script_path) as scripts, zipfile.ZipFile(self.native_path) as native, patch('world_gameplay_basis.SYSTEMS', ('combat',)):
            return apply(self.files, self.graphs, 'Quests/GlueTravel/project.xml', 'test_level', native, scripts, guid)

    def test_destination_binding_and_native_dependency_preservation(self):
        files, graphs, report = self.run_apply()
        self.assertEqual(files['quest_state'], b'preserve')
        self.assertEqual(graphs['unrelated.xml'], b'preserve')
        self.assertFalse(report['runtime_verified'])
        self.assertFalse(report['full_trosky_parity'])
        self.assertEqual(len(report['native_dependencies']), 1)
        self.assertFalse(any(p.lower().startswith('quests/final/') for p in graphs))
        mission = ET.fromstring(files['objects_mission0.xml'])
        for name in ('open_world', 'surrenderHolder'):
            entity = mission.find("Entity[@Name='" + name + "']")
            self.assertEqual(entity.get('Pos'), '10,20,30')
            self.assertNotIn('regional_service', ET.tostring(entity).decode())
        links = ET.fromstring(files['waitinglinks.xml'])
        self.assertEqual({n.text for n in links.iter('LinkDefinition')}, {'module', "asset['openworld']", "asset['surrenderDH']", 'punishment_openworldQSO'})
        entry = ET.fromstring(graphs['Quests/GlueTravel/entry/test_level.xml'])
        self.assertIsNotNone(entry.find("Skald/Level/Nodes/State[@Name='existing_quest']"))

    def test_missing_native_asset_fails_before_modifying_input(self):
        key = 'quests/final/barbora/open_world/combat.xml'
        self.native_files[key] = self.native_files[key].replace(b'Alias="openworld"', b'Alias="regional_guard"')
        self.write_scripts()
        with self.assertRaisesRegex(ValueError, 'regional_guard'): self.run_apply()
        self.assertNotIn(b'surrenderHolder', self.files['objects_mission0.xml'])

    def test_campaign_input_requires_adapter(self):
        key = 'quests/final/barbora/open_world/combat.xml'
        self.native_files[key] = self.native_files[key].replace(b'<Assets>', b'<Ports><Port Name="trosky_story" Direction="In" Type="bool"/></Ports><Assets>')
        self.write_scripts()
        with self.assertRaisesRegex(ValueError, 'trosky_story'): self.run_apply()

    def test_missing_transitive_definition_is_rejected(self):
        key = 'quests/final/barbora/open_world/combat.xml'
        self.native_files[key] = self.native_files[key].replace(b'<Assets>', b'<Definitions><Definition File="missing.xml"/></Definitions><Assets>')
        self.write_scripts()
        with self.assertRaisesRegex(ValueError, 'Missing native gameplay dependency'): self.run_apply()


if __name__ == '__main__': unittest.main()
