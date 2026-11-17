from pathlib import Path
import sys
import unittest
import xml.etree.ElementTree as E
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from campaign_quest_graph import emit_project
from campaign_quest_policy import bind, plan
from test_campaign_quest_graph import model


def policy(**objective):
    m = model()
    m['tables']['quest_objective']['rows'][1].update(objective)
    return m


def lowered(m):
    files, report = emit_project([m], 'Example')
    blob, result = bind(files['Example/arbitrary_quest.xml'], m)
    return E.fromstring(blob), result, blob, files['Example/arbitrary_quest.xml'], report


class PolicyTests(unittest.TestCase):
    def test_zero_condition_never_completes_by_itself(self):
        # The emitter's own condition binder already covers '0' on identifier-named
        # objectives; numeric source names (q_lionsDen '7') are what it leaves behind.
        root, result, blob, emitted, report = lowered(policy(condition='0', objective_name='7'))
        self.assertEqual([r['kind'] for r in report['quests'][0]['unsupported']], ['completion_policy'])
        self.assertEqual(result['converted'], [dict(objective_id='4', objective='7', policy='never_automatic')])
        self.assertEqual(blob, emitted)

    def test_timed_completion_keeps_the_source_clock(self):
        for text, duration, clock in (('2h #WT', '2h', 'WorldTime'), ('30s#GT', '30s', 'GameTime'),
                                      ('1d #WT', '1d', 'WorldTime'), ('500ms #GT', '500ms', 'GameTime')):
            with self.subTest(text=text):
                root, result, _, _, _ = lowered(policy(condition='1', autocomplete_timeout_str=text))
                self.assertEqual(result['converted'][0]['policy'], 'timed')
                timer = root.find(".//Timer[@Name='lowered_policy_4_timer']")
                self.assertEqual({c.get('Name'): c.get('Value') for c in timer.findall('Constant')},
                                 dict(Duration=duration, TimeType=clock))
                edges = {(e.get('From'), e.get('To')) for e in timer.findall('Edge')}
                self.assertIn(('objective_4.OnStarted', 'SetRunning'), edges)
                self.assertEqual({f for f, t in edges if t == 'SetStopped'}, {'objective_4.OnCompleted',
                    'objective_4.OnFailed', 'objective_4.OnCanceled', 'objective_4.OnUnchanged'})
                gate = root.find(".//If[@Name='lowered_policy_4_if_started']")
                self.assertEqual({(e.get('From'), e.get('To')) for e in gate},
                                 {('objective_4.Started', 'Condition'), ('lowered_policy_4_timer.OnFinished', 'Exec')})
                state = root.find(".//State[@Name='objective_4']")
                self.assertIn('lowered_policy_4_if_started.True',
                              [e.get('From') for e in state.findall("Edge[@To='SetCompleted']")])

    def test_emitter_timers_are_not_duplicated(self):
        root, result, blob, emitted, _ = lowered(policy(condition='1', autocomplete_timeout_str='5m #GT'))
        self.assertEqual(result['converted'][0]['policy'], 'timed_by_emitter')
        self.assertEqual(blob, emitted)
        self.assertIsNotNone(root.find(".//Timer[@Name='complete_4_queued']"))

    def test_unclear_policies_stay_pending(self):
        cases = {'timeout without a named clock: 10s': dict(condition='1', autocomplete_timeout_str='10s'),
                 'timeout without a named clock: 1.5h #WT': dict(condition='1', autocomplete_timeout_str='1.5h #WT'),
                 'timeout without a constant-true condition': dict(condition='', autocomplete_timeout_str='2h #WT'),
                 'expiration timeout': dict(condition='', expiration_timeout_str='30s #WT')}
        for reason, objective in cases.items():
            with self.subTest(reason=reason):
                result = plan(policy(**objective))
                self.assertFalse(result['converted'])
                self.assertEqual([p['reason'] for p in result['pending']], [reason])

    def test_expressions_and_counted_tracking_belong_to_other_adapters(self):
        m = policy(condition="IsQuestCompleted('other')")
        self.assertEqual(plan(m), dict(converted=[], pending=[], runtime_verified=False))
        m = policy(condition='0')
        m['tables']['quest_tracked_asset'] = dict(rows=[dict(quest_id='42', objective_id='4', quest_asset_id='8',
                                                             count='1', map_asset_id='')])
        self.assertFalse(plan(m)['converted'])
        m['tables']['quest_tracked_asset']['rows'][0].update(quest_asset_id='', map_asset_id='26')
        self.assertEqual(plan(m)['converted'][0]['policy'], 'never_automatic')

    def test_binding_is_single_use(self):
        m = policy(condition='1', autocomplete_timeout_str='2h #WT')
        _, _, blob, _, _ = lowered(m)
        with self.assertRaisesRegex(ValueError, 'already lowered'):
            bind(blob, m)


if __name__ == '__main__': unittest.main()
