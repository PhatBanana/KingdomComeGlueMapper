import copy
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from campaign_training_runtime import emit
import test_campaign_native_training as native_tests
from test_campaign_combat_runtime import Graph


class TrainingGraph(Graph):
    """Exercise emitted graph ordering; native combat events are external inputs."""
    def __init__(self):
        super().__init__(emit('ArbitraryTraining', 'Basic', native_tests.NativeTrainingTests().contract())[0])
        self.values.update(tutor_ready=False, dialogue_busy=False, ack_phase=0, lesson_authorized=True)
        self.values['training.Phase'] = 0

    def fire(self, event):
        super().fire(event)
        for name, node in self.nodes.items():
            for e in node.findall('Edge'):
                if e.get('From') != event: continue
                if node.tag == 'IfFunction' and e.get('To') == 'Exec':
                    a = self.value(node.find("Edge[@To='ValueA']").get('From'))
                    b = self.value(node.find("Edge[@To='ValueB']").get('From'))
                    self.fire(name + ('.True' if a == b else '.False'))
                elif node.tag == 'CombatTutorialNode' and e.get('To') == 'CustomStepEvent':
                    self.events.append('native.continue')

    def run(self):
        self.fire('request'); self.fire('arrived')
        self.values['tutor_ready'] = True
        self.fire('prepared')


class TrainingRuntimeTests(unittest.TestCase):
    def test_arrival_waits_for_separate_lesson_authorization(self):
        for authorize_first in (False, True):
            g = TrainingGraph(); g.values['lesson_authorized'] = False
            g.fire('request')
            if authorize_first:
                g.values['lesson_authorized'] = True; g.fire('authorization_changed')
                self.assertNotIn('output.prepare', g.events)
            g.fire('arrived')
            if not authorize_first:
                self.assertTrue(g.states['at_destination'])
                self.assertNotIn('output.prepare', g.events)
                g.values['lesson_authorized'] = True; g.fire('authorization_changed')
            g.fire('authorization_changed')
            self.assertEqual(g.events.count('output.prepare'), 1)

    def test_training_waits_for_all_acknowledgements_and_dialogue_release(self):
        g = TrainingGraph()
        g.fire('prepared'); g.fire('arrived')
        self.assertFalse(g.states['running'])
        g.fire('request'); g.fire('request')
        self.assertEqual(g.events.count('output.arrive'), 1)
        g.fire('arrived'); g.fire('prepared')
        self.assertTrue(g.states['waiting']); self.assertFalse(g.states['running'])
        g.values.update(tutor_ready=True, dialogue_busy=True)
        g.fire('readiness_changed')
        self.assertFalse(g.states['running'])
        g.values['dialogue_busy'] = False; g.fire('dialogue_finished')
        self.assertTrue(g.states['running'])
        self.assertEqual(g.events.count('output.started'), 1)

    def test_success_requires_workers_stopped_and_successful_cleanup(self):
        g = TrainingGraph(); g.run()
        g.fire('training.OnSuccessEvent'); g.fire('training.OnPhaseSkipped')
        self.assertNotIn('output.finished', g.events)
        g.fire('training.OnTutorialEnd')
        self.assertFalse(g.states['running']); self.assertTrue(g.states['stopping'])
        g.fire('cleanup_done')
        self.assertNotIn('output.finished', g.events)
        g.fire('workers_stopped'); g.fire('cleanup_failed')
        self.assertTrue(g.states['cleaning'])
        self.assertNotIn('output.finished', g.events)
        g.fire('retry_cleanup'); g.fire('cleanup_done'); g.fire('cleanup_done')
        self.assertEqual(g.events.count('output.finished'), 1)
        self.assertFalse(any(g.states[n] for n in ('arriving','at_destination','preparing','waiting','running','stopping','cleaning')))

    def test_cancel_during_preparation_rejects_late_callbacks(self):
        g = TrainingGraph(); g.fire('request'); g.fire('arrived'); g.fire('cancel')
        g.values['tutor_ready'] = True
        g.fire('prepared'); g.fire('readiness_changed'); g.fire('training.OnTutorialEnd')
        self.assertFalse(g.states['running'])
        self.assertNotIn('output.cleanup', g.events)
        g.fire('workers_stopped'); g.fire('cleanup_done')
        self.assertEqual(g.events.count('output.canceled'), 1)
        self.assertNotIn('output.finished', g.events)

    def test_cancellation_during_success_cleanup_revokes_completion(self):
        g = TrainingGraph(); g.run(); g.fire('training.OnTutorialEnd')
        g.fire('workers_stopped'); g.fire('cancel'); g.fire('cleanup_done')
        self.assertIn('output.canceled', g.events)
        self.assertNotIn('output.finished', g.events)

    def test_instruction_is_phase_scoped_once_and_never_auto_acknowledged(self):
        g = TrainingGraph(); g.run(); g.fire('training.OnPhaseStart')
        self.assertNotIn('native.continue', g.events)
        g.values['ack_phase'] = 2; g.fire('instruction_ack')
        self.assertNotIn('native.continue', g.events)
        g.values['ack_phase'] = 0; g.fire('instruction_ack'); g.fire('instruction_ack')
        self.assertEqual(g.events.count('native.continue'), 1)
        g.values['training.Phase'] = 1; g.fire('training.OnPhaseStart'); g.fire('instruction_ack')
        self.assertEqual(g.events.count('native.continue'), 1)
        g.values['ack_phase'] = 1; g.fire('instruction_ack')
        self.assertEqual(g.events.count('native.continue'), 2)

    def test_saved_lifecycle_retains_cleanup_obligation(self):
        g = TrainingGraph(); g.run(); g.fire('training.OnTutorialEnd'); g.fire('workers_stopped')
        restored = TrainingGraph()
        restored.states = copy.deepcopy(g.states)
        restored.values = copy.deepcopy(g.values)
        restored.fire('request')
        self.assertNotIn('output.arrive', restored.events)
        restored.fire('cleanup_done')
        self.assertEqual(restored.events.count('output.finished'), 1)

    def test_preparation_failure_and_readiness_loss_require_cleanup(self):
        for failure in ('preparation_failed', 'readiness_changed'):
            g = TrainingGraph()
            if failure == 'preparation_failed':
                g.fire('request'); g.fire('arrived')
            else:
                g.run(); g.values['tutor_ready'] = False
            g.fire(failure)
            self.assertFalse(g.states['running'])
            self.assertIn('output.fault', g.events)
            self.assertIn('output.stop_workers', g.events)
            self.assertNotIn('output.finished', g.events)
            g.fire('workers_stopped'); g.fire('cleanup_done')
            self.assertIn('output.canceled', g.events)


if __name__ == '__main__': unittest.main()
