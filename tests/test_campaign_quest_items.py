import copy
from pathlib import Path
import sys
import unittest
import xml.etree.ElementTree as E
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from campaign_quest_items import bind, plan
from campaign_quest_graph import emit_project
from test_campaign_quest_graph import model

A = '00000000-0000-0000-0000-000000000001'
B = '00000000-0000-0000-0000-000000000002'


def tracked():
    m = model()
    m['tables']['quest_objective']['rows'][1]['condition'] = '1'
    m['tables']['quest_tracked_asset'] = dict(rows=[dict(quest_id='42', objective_id='4', quest_asset_id='8', count='10')])
    m['tables']['quest_item'] = dict(rows=[dict(quest_id='42', quest_asset_id='8', item_id=A,
        item_category_id='0', min_health='0')])
    return m


class ItemTrackingTests(unittest.TestCase):
    def test_missing_mapping_never_becomes_completion(self):
        r = plan(tracked(), {}, [])
        self.assertFalse(r['converted'])
        self.assertIn('unmapped item', r['pending'][0]['reasons'][0])

    def test_target_registration_required(self):
        with self.assertRaisesRegex(ValueError, 'Unregistered'):
            plan(tracked(), {A: B}, [])

    def test_unsupported_health_count_and_predicate_stay_pending(self):
        for change in ('health', 'count', 'condition'):
            m = tracked()
            if change == 'health': m['tables']['quest_item']['rows'][0]['min_health'] = '0.5'
            if change == 'count': m['tables']['quest_tracked_asset']['rows'][0]['count'] = '0'
            if change == 'condition': m['tables']['quest_objective']['rows'][1]['condition'] = 'HasTalked()'
            self.assertFalse(plan(m, {A: B}, [B])['converted'])

    def test_mixed_item_and_npc_does_not_partially_complete(self):
        m = tracked()
        m['tables']['quest_tracked_asset']['rows'].append(dict(quest_id='42', objective_id='4', quest_asset_id='99', count='1'))
        self.assertFalse(plan(m, {A: B}, [B])['converted'])

    def test_native_completion_rechecks_quantity_and_active_state_after_events(self):
        m = tracked()
        files, _ = emit_project([m], 'Example')
        b, r = bind(files['Example/arbitrary_quest.xml'], m, {A: B}, [B], 'player')
        root = E.fromstring(b)
        self.assertEqual(root.find(".//Function[@Name='tracked_items_4_0_descriptor']/Constant[@Name='Amount']").get('Value'), '10')
        self.assertEqual(root.find(".//Function[@Name='tracked_items_4_0_descriptor']/Constant[@Name='ItemClass']").get('Value'), B)
        timer = root.find(".//Timer[@Name='tracked_items_4_queued']")
        self.assertIn('objective_4.OnStarted', [e.get('From') for e in timer.findall('Edge')])
        state = root.find(".//State[@Name='objective_4']")
        self.assertIn('tracked_items_4_complete.True', [e.get('From') for e in state.findall("Edge[@To='SetCompleted']")])
        gate = root.find(".//Function[@Name='tracked_items_4_all_0']")
        self.assertEqual({e.get('From') for e in gate}, {'objective_4.Started', 'tracked_items_4_0_matches.bool'})
        self.assertFalse(r['runtime_verified'])
        with self.assertRaisesRegex(ValueError, 'already bound'):
            bind(b, m, {A: B}, [B], 'player')

    def test_multiple_requirements_preserved(self):
        m = tracked()
        m['tables']['quest_tracked_asset']['rows'].append(dict(quest_id='42', objective_id='4', quest_asset_id='9', count='2'))
        m['tables']['quest_item']['rows'].append(dict(quest_id='42', quest_asset_id='9', item_id=B))
        r = plan(m, {A: A, B: B}, [A, B])
        self.assertEqual([x['count'] for x in r['converted'][0]['requirements']], [10, 2])


if __name__ == '__main__': unittest.main()
