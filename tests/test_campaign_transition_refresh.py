import sys
from pathlib import Path
import unittest
import xml.etree.ElementTree as E
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from campaign_quest_graph import emit_quest
from campaign_transition_refresh import refresh
from test_campaign_quest_graph import model

class TransitionRefreshTests(unittest.TestCase):
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
