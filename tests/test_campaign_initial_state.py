import sys
from pathlib import Path
import unittest
import xml.etree.ElementTree as ET
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from campaign_initial_state import bind_before, source_stats, quest_start_states


class InitialStateTests(unittest.TestCase):
    def test_requires_exact_lifecycle_edge_and_sequences_native_calls(self):
        blob = b'<Database><Skald><Project><Assets><SoulAsset Name="actor"/></Assets><Nodes><Dialog Name="scene"><Edge From="once.C" To="EnqueueDialogue"/></Dialog></Nodes></Project></Skald></Database>'
        defs = b'''<Definitions><Type TypeName="wh::rpgmodule::SoulStat"><Enumeration Name="strength"/></Type><Type TypeName="wh::rpgmodule::SoulState"><Enumeration Name="hunger"/></Type><Definition TypeName="Function"><Properties><Property Name="MethodName" Value="wh::rpgmodule::SetStatLevelDebug"/></Properties></Definition><Definition TypeName="MemberFunction"><Properties><Property Name="MethodName" Value="SetState"/></Properties></Definition></Definitions>'''
        args = ('scene','EnqueueDialogue','once.C','actor','init',{'strength':1},{},{'hunger':40},defs)
        result, _ = bind_before(blob, *args)
        root = ET.fromstring(result)
        self.assertEqual(root.find('.//Dialog/Edge').get('From'), 'init_state_hunger.OnExec')
        self.assertEqual(root.find('.//Function/Edge').get('From'), 'once.C')
        self.assertEqual(root.find('.//MemberFunction/Edge').get('From'), 'init_stat_strength.OnExec')
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
