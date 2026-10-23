import unittest
import xml.etree.ElementTree as E

from campaign_training_runtime import emit
from training_handoff_repair import preparation_release
import test_campaign_native_training as native_tests
from test_campaign_combat_runtime import Graph


class SceneReleaseMigration(unittest.TestCase):
    def legacy(self):
        root = E.fromstring(emit('arbitrary_lesson', 'Basic', native_tests.NativeTrainingTests().contract())[0])
        nodes = root.find('Skald/Module/Nodes')
        nodes.remove(nodes.find("Function[@Name='may_prepare_1']"))
        guard = nodes.find("If[@Name='authorized_preparation']")
        guard.find("Edge[@To='Condition']").set('From', 'may_prepare_0.bool')
        guard.remove(guard.find("Edge[@From='dialogue_finished']"))
        return root

    def test_upgraded_lifecycle_waits_for_scene_then_prepares_once(self):
        old = E.tostring(self.legacy())
        fixed, changed = preparation_release(old)
        self.assertTrue(changed)
        graph = Graph(fixed)
        graph.values.update(dialogue_busy=True, lesson_authorized=True, tutor_ready=False)
        graph.fire('request'); graph.fire('arrived')
        graph.fire('authorization_changed')
        self.assertNotIn('output.prepare', graph.events)
        graph.values['dialogue_busy'] = False; graph.fire('dialogue_finished')
        graph.fire('dialogue_finished')
        self.assertEqual(graph.events.count('output.prepare'), 1)
        self.assertEqual(preparation_release(fixed), (fixed, False))

    def test_unrecognized_preparation_binding_is_rejected(self):
        root = self.legacy()
        root.find(".//If[@Name='authorized_preparation']/Edge[@To='Condition']").set('From','other.bool')
        with self.assertRaisesRegex(ValueError, 'Unrecognized'):
            preparation_release(E.tostring(root))


if __name__ == '__main__': unittest.main()
