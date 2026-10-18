import sys
from pathlib import Path
import unittest
import xml.etree.ElementTree as ET
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from campaign_initial_state import bind_before, source_stats, quest_start_states, upgrade_debug_initializers


class InitialStateTests(unittest.TestCase):
    def test_upgrade_preserves_lifecycle_and_values_and_is_idempotent(self):
        blob = b'''<Database><Skald><Project><Nodes><Function Name="init_stat_strength" MethodName="wh::rpgmodule::SetStatLevelDebug"><Asset Name="Soul" Alias="player"/><Constant Name="Stat" Value="strength"/><Constant Name="Value" Value="2"/><Edge From="once.B" To="Exec"/></Function><Next><Edge From="init_stat_strength.OnExec" To="start"/></Next></Nodes></Project></Skald></Database>'''
        defs = b'''<Definitions><Definition TypeName="MemberFunction"><Properties><Property Name="MethodName" Value="AdvanceToStatLevel"/><Property Name="DeclaringType" Value="wh::rpgmodule::I_Soul"/></Properties><Ports><RunTimePort Name="Level" Type="uint"/><RunTimePort Name="OnExec" Type="trigger"/></Ports></Definition></Definitions>'''
        result, report = upgrade_debug_initializers(blob, 'init', defs)
        root = ET.fromstring(result)
        node = root.find('.//MemberFunction')
        self.assertEqual(node.get('MethodName'), 'AdvanceToStatLevel')
        self.assertEqual(node.find("Constant[@Name='Level']").get('Value'), '2')
        self.assertEqual(node.find('Edge').get('From'), 'once.B')
        self.assertEqual(root.find('.//Next/Edge').get('From'), 'init_stat_strength.OnExec')
        self.assertEqual(report['level_policy'], 'advance_to_minimum')
        self.assertEqual(upgrade_debug_initializers(result, 'init', defs)[0], result)
        with self.assertRaisesRegex(ValueError, 'Missing retail initializer'):
            upgrade_debug_initializers(blob, 'init', b'<Definitions/>')

    def test_requires_exact_lifecycle_edge_and_sequences_native_calls(self):
        blob = b'<Database><Skald><Project><Assets><SoulAsset Name="actor"/></Assets><Nodes><Dialog Name="scene"><Edge From="once.C" To="EnqueueDialogue"/></Dialog></Nodes></Project></Skald></Database>'
        defs = b'''<Definitions><Type TypeName="wh::rpgmodule::SoulStat"><Enumeration Name="strength"/></Type><Type TypeName="wh::rpgmodule::SoulState"><Enumeration Name="hunger"/></Type><Definition TypeName="MemberFunction"><Properties><Property Name="MethodName" Value="AdvanceToStatLevel"/></Properties></Definition><Definition TypeName="MemberFunction"><Properties><Property Name="MethodName" Value="SetState"/></Properties></Definition></Definitions>'''
        args = ('scene','EnqueueDialogue','once.C','actor','init',{'strength':1},{},{'hunger':40},defs)
        result, _ = bind_before(blob, *args)
        root = ET.fromstring(result)
        self.assertEqual(root.find('.//Dialog/Edge').get('From'), 'init_state_hunger.OnExec')
        self.assertEqual(root.find(".//MemberFunction[@Name='init_stat_strength']/Edge").get('From'), 'once.C')
        self.assertEqual(root.find(".//MemberFunction[@Name='init_state_hunger']/Edge").get('From'), 'init_stat_strength.OnExec')
        with self.assertRaisesRegex(ValueError, 'exact initialization edge'):
            bind_before(result, *args)

    def test_reads_source_baseline_and_refuses_invalid_values(self):
        self.assertEqual(source_stats(dict(str='2',agi='1',vit='3',spc='4')),
                         dict(strength=2,agility=1,vitality=3,speech=4))
        with self.assertRaises(ValueError):source_stats(dict(str='nan',agi='1',vit='1',spc='1'))

    def test_state_extraction_keeps_event_and_readiness_and_excludes_nested_conditions(self):
        blob = b'''<BehaviorTrees><ExternalLock SemaphoreName="assetsLoaded"><ProcessMessage inbox="QuestMailbox" variable="event"><Switch><IfCondition condition="$event.State == $enum:QuestState.Started"><Sequence><ExecuteLua code="player.soul:SetState('hunger', 40)"/><IfCondition condition="optional"><ExecuteLua code="player.soul:SetState('health', 20)"/></IfCondition></Sequence></IfCondition><IfCondition condition="$event.State == $enum:QuestState.Completed"><Sequence><ExecuteLua code="player.soul:SetState('hunger', 90)"/></Sequence></IfCondition></Switch></ProcessMessage></ExternalLock></BehaviorTrees>'''
        values, receipt = quest_start_states(blob)
        self.assertEqual(values, {'hunger':40})
        self.assertEqual(receipt[0]['readiness_locks'], ['assetsLoaded'])


if __name__ == '__main__':unittest.main()
