from pathlib import Path
import sys
import unittest
import xml.etree.ElementTree as E

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from campaign_training_readiness import emit


class TrainingReadinessTests(unittest.TestCase):
    def test_readiness_is_scoped_to_an_active_wait_after_action_completion(self):
        data = emit('ImportedLesson')['AI/ImportedLesson_ready.xml']
        root = E.fromstring(data)
        sequence = root.find('./BehaviorTree/Root/Behavior/Sequence')
        self.assertEqual([n.tag for n in sequence], ['WaitAction', 'EntityContext'])
        context = sequence[1]
        self.assertEqual(context.get('target'), '')  # executing actor, not a named tutor
        self.assertEqual(context.get('context'), 'tutorial_npcReadyForCombat')
        self.assertEqual(context.find('Wait').get('duration'), "'-1'")
        self.assertEqual(context.find('Wait').get('skipInLOD'), 'false')
        self.assertIsNone(root.find('.//InstantAddEntityContext'))

    def test_rejects_unsafe_generated_paths(self):
        for stem in ('../lesson', 'a/b', '', 'a b'):
            with self.assertRaises(ValueError): emit(stem)


if __name__ == '__main__': unittest.main()
