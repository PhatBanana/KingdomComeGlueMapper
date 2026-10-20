import sys
from pathlib import Path
import unittest
import xml.etree.ElementTree as E
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from campaign_quest_graph import emit_quest
from campaign_transition_refresh import refresh
from test_campaign_quest_graph import model

class TransitionRefreshTests(unittest.TestCase):
    def test_upgrades_old_quest_without_end_timer_and_preserves_direct_completion(self):
        source = model()
        blob, _ = emit_quest(source, 'Progress')
        root = E.fromstring(blob)
        nodes = root.find('./Skald/Quest/Nodes')
        ending = {n.get('Name') for n in nodes if n.get('Name', '').startswith('quest_end_')}
        ending.update(n.get('Name') for n in nodes if n.get('Name') == 'advance_2'
                      or n.get('Name', '').startswith('ready_2'))
        for node in list(nodes):
            if node.get('Name') in ending:
                nodes.remove(node)
            else:
                for edge in list(node.findall('Edge')):
                    if edge.get('From', '').split('.')[0] in ending:
                        node.remove(edge)
        updated, _ = refresh(E.tostring(root), source)
        parsed = E.fromstring(updated)
        self.assertIsNotNone(parsed.find(".//Timer[@Name='quest_end_2_queued']"))
        self.assertIsNotNone(parsed.find(".//If[@Name='advance_2']/Edge[@From='quest_end_2_queued.OnFinished']"))
        state = parsed.find(".//State[@Name='quest_progress']")
        self.assertIsNotNone(state.find("Edge[@From='complete'][@To='SetDone']"))
        self.assertIsNotNone(state.find("Edge[@From='advance_2.True'][@To='SetDone']"))
        self.assertEqual(updated, refresh(updated, source)[0])

    def test_replaces_old_join_preserves_other_logic_and_is_idempotent(self):
        source = model()
        blob, _ = emit_quest(source, 'Progress')
        root = E.fromstring(blob)
        nodes = root.find('./Skald/Quest/Nodes')
        E.SubElement(nodes, 'Trace', Name='existing_custom_trace')
        state = nodes.find("State[@Name='objective_4']")
        E.SubElement(state, 'Edge', From='custom_action.Exec', To='SetCompleted')
        for row in source['tables']['quest_objective']['rows']:
            if row['objective_id'] in ('4', '5'):
                row['is_exclusive'] = 'True'
                source['graph']['nodes'][row['objective_id']]['payload'][0]['attributes']['IsExclusive'] = '1'
        changed, result = refresh(E.tostring(root), source)
        parsed=E.fromstring(changed)
        self.assertIsNotNone(parsed.find(".//Trace[@Name='existing_custom_trace']"))
        self.assertIsNotNone(parsed.find(".//State[@Name='objective_4']/Edge[@From='custom_action.Exec']"))
        self.assertEqual(len(result['exclusive_cancellations']),2)
        join=parsed.find(".//Function[@Name='ready_6_predecessors_0']")
        self.assertEqual(join.get('MethodName'),'math::boolean::Or')
        again, _ = refresh(changed, source)
        self.assertEqual(again,changed)

if __name__ == '__main__': unittest.main()
