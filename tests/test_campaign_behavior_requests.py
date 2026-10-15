import sys
from pathlib import Path
import unittest
import xml.etree.ElementTree as ET

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from campaign_behavior_requests import dependencies
from campaign_rpg_script import upgrade
from campaign_quest_bridge import UnsupportedOperation
from quest_import import ast


class BehaviorRequestTests(unittest.TestCase):
    def test_message_invocation_preserves_source_identity(self):
        root = ast(ET.fromstring('''<Root><InstantSendMessageToNPC target="t_actors[other]"
          type="combat:stimulus:customBehaviorRequest"
          values="behaviorSource($this.id),behaviorName(arbitrary_fight),entity($__player)"/></Root>'''))
        self.assertEqual(dependencies(root), [dict(path='Root/0', tree='arbitrary_fight',
                                                  source='$this.id', entity='$__player')])
        root['children'][0]['attributes']['values'] = 'behaviorName($dynamic)'
        self.assertIn('error', dependencies(root)[0])

    def test_missing_message_target_withholds_request_caller(self):
        from test_campaign_behavior import source, catalog
        from campaign_behavior import convert_behaviors
        from campaign_dependencies import DependencyImporter
        m = source('''<Root><InstantSendMessageToNPC target="this.id"
          type="combat:stimulus:customBehaviorRequest"
          values="behaviorSource($this.id),behaviorName(absent),entity($__player)"/></Root>''')
        importer = DependencyImporter({}, {'ai_types': {'combat:stimulus:customBehaviorRequest': 'cloned_type'}})
        files, _, report = convert_behaviors([m], 'Imported', catalog(), importer=importer)
        self.assertFalse(files)
        record = report['trees'][0]
        self.assertIn(('q_test', 'libs/ai/quests/q_test.xml', 'absent'), record['blocked_includes'])
        self.assertTrue(any('consumer' in e['reason'] for e in record['unresolved']))

    def test_duel_health_upgrade_is_actor_independent_and_bounded(self):
        source = """local differentActor = XGenAIModule.GetEntityByWUID(data.this.id)
          differentActor.soul:SetState('health', 80)
          local currentHP = player.soul:GetState('health')
          data.customThreshold = currentHP/4"""
        result = upgrade(source)
        self.assertIn("SetState('health', 80)", result)
        self.assertIn("data.customThreshold = player.soul:GetState('health') / 4", result)
        self.assertNotIn('differentActor', result)
        for invalid in (source.replace('/4', '/0'), source.replace('80)', '200)'), source + '\nUnknown()'):
            with self.assertRaises(UnsupportedOperation):
                upgrade(invalid)


if __name__ == '__main__':
    unittest.main()
