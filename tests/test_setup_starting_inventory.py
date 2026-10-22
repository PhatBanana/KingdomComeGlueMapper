import sys
from pathlib import Path
import unittest
import xml.etree.ElementTree as E
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'tools'))
from setup_starting_inventory import bind, torch


class StartingInventoryTests(unittest.TestCase):
    def test_new_game_only_unequipped_and_idempotent(self):
        graph=b'''<Database><Skald><Project><Assets><SoulAsset Name="travel_player"/></Assets><Nodes>
          <Function Name="gm_source_baseline_stat_agility"><Edge From="gm_source_initial_loadout_4_equip.OnExec" To="Exec"/></Function>
          <Function Name="restore"><Edge From="load.OnLoad" To="Exec"/></Function>
          </Nodes></Project></Skald></Database>'''
        definitions=b'''<Definitions>
          <Definition TypeName="EventMemberFunction"><Properties><Property Name="MethodName" Value="CreateItems"/></Properties></Definition>
          <Definition TypeName="MemberFunction"><Properties><Property Name="MethodName" Value="EquipPlayersItem"/></Properties></Definition>
          </Definitions>'''
        updated=bind(graph,'native-torch',definitions)
        nodes=E.fromstring(updated).find('Skald/Project/Nodes')
        create=nodes.find("EventMemberFunction[@MethodName='CreateItems']")
        self.assertEqual(create.find("Constant[@Name='Amount']").get('Value'),'1')
        self.assertEqual(create.find("Constant[@Name='ItemClass']").get('Value'),'native-torch')
        self.assertEqual(create.find("Edge[@To='Exec']").get('From'),'gm_source_initial_loadout_4_equip.OnExec')
        self.assertEqual(nodes.find("Function[@Name='restore']/Edge").get('From'),'load.OnLoad')
        self.assertFalse(nodes.findall("MemberFunction[@MethodName='EquipPlayersItem']"))
        self.assertEqual(bind(updated,'native-torch',definitions),updated)
        with self.assertRaises(ValueError):bind(updated,'different-item',definitions)
        with self.assertRaises(ValueError):bind(graph.replace(b'gm_source_initial_loadout_4_equip.OnExec',b'load.OnLoad'),'native-torch',definitions)

    def test_native_player_torch_not_tool_or_cutscene_prop(self):
        rows={str(i):E.Element(tag,Name=name,Id=str(i),EntityScript='Torch',Model='torch') for i,(tag,name) in enumerate([
            ('NPCTool','torch_tool'),('MeleeWeapon','cutscene_torch'),('MeleeWeapon','torch_weapon')])}
        with patch('setup_starting_inventory.native_items',return_value=rows):
            self.assertEqual(torch(None),'2')
            rows['2'].set('Model','preproduction/traffic_cone/cone')
            with self.assertRaises(ValueError):torch(None)


if __name__=='__main__':unittest.main()
