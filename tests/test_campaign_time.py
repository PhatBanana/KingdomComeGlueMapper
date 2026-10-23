import sys
from pathlib import Path
import unittest
import xml.etree.ElementTree as E
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from campaign_time import parse, TimeBridge
from campaign_quest_bridge import UnsupportedOperation
from campaign_behavior import convert_behaviors
from campaign_compile import wire_bridge
from campaign_quest_graph import emit_project
from test_campaign_quest_graph import model as quest
from test_campaign_behavior import source, catalog


class CampaignTimeTests(unittest.TestCase):
    def test_named_locks_are_independent_persistent_states(self):
        bridge = TimeBridge('imported')
        bridge.lower("forwardTime(10.00)\nUtils.SetWorldTimePaused(true, 'one')", {})
        bridge.lower("Utils.SetWorldTimePaused(false, 'one'); forwardTime(16.00)", {})
        bridge.lower("Utils.SetWorldTimePaused(true, 'two')", {})
        root = E.fromstring(bridge.emit()['Quests/imported_time_bridge.xml'])
        states = root.findall('.//State')
        self.assertEqual(len(states), 2)
        self.assertEqual(len(root.findall('.//PauseWorldTime')), 2)
        shared = next(s for s in states if len(s.findall('Edge')) == 2)
        self.assertEqual({e.get('To') for e in shared.findall('Edge')}, {'SetTrue', 'SetFalse'})
        commands = root.findall('.//Function/Constant')
        self.assertEqual({c.get('Value') for c in commands}, {'10h00m', '16h00m'})

    def test_unsupported_tail_or_dynamic_hour_does_not_register_partial_action(self):
        bridge = TimeBridge('imported')
        for script in ['forwardTime(10); unknown()', 'forwardTime(data.hour)', 'forwardTime(24)',
                       "Utils.SetWorldTimePaused(true, reason)"]:
            with self.subTest(script=script), self.assertRaises(UnsupportedOperation):
                bridge.lower(script, {})
        self.assertFalse(bridge.actions)

    def test_clock_signal_remains_inside_source_gate(self):
        c = catalog(); c['nodes']['ExecuteLua'] = dict(attributes=['code'], children=[])
        m = source('''<Root><IfCondition condition="&quot;$hasStarted&quot;">
          <ExecuteLua code="&quot;forwardTime(10); Utils.SetWorldTimePaused(true, 'quest_lock')&quot;"/>
          </IfCondition></Root>''')
        files, bridges, report = convert_behaviors([m], 'imported', c)
        gate = E.fromstring(next(iter(files.values()))).find('.//IfCondition')
        self.assertTrue(gate[0].tag.startswith('SendAIConceptSignal_'))
        self.assertEqual(gate.get('condition'), '$hasStarted')
        self.assertIn(report['auxiliary_modules'][0]['file'], bridges)
        self.assertEqual(report['whole_trees_emitted'], 1)

    def test_campaign_host_declares_and_instantiates_clock_module(self):
        c = catalog(); c['nodes']['ExecuteLua'] = dict(attributes=['code'], children=[])
        m = source('''<Root><ExecuteLua code="&quot;forwardTime(10)&quot;"/></Root>''')
        _, bridges, report = convert_behaviors([m], 'imported', c)
        files, _ = emit_project([quest()], 'world')
        wire_bridge(files, 'world', bridges, report)
        host = E.fromstring(files['world.xml']).find('./Skald/Project')
        self.assertIsNotNone(host.find("Definitions/Definition[@File='imported_time_bridge.xml']"))
        self.assertIsNotNone(host.find("Nodes/imported_time_bridge[@Name='source_time_bridge']"))


if __name__ == '__main__': unittest.main()
