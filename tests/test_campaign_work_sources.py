import unittest
import xml.etree.ElementTree as E
from test_campaign_behavior import source
from campaign_work_sources import discover


class WorkSourcesTests(unittest.TestCase):
    def trees(self, expression, only='true'):
        m = source('''<Root><SmartAreaBehaviorTag preferredBehaviors="&quot;''' + expression +
            '''&quot;" preferredBehaviorsOnly="&quot;''' + only + '''&quot;"/></Root>''')
        return m['behavior_documents']['libs/ai/quests/q_test.xml']['trees']

    def test_table_dispatch_finds_all_programs_without_matching_actor_names(self):
        rows = [dict(sa_behaviour_tag_name='AuthoredJob', tree_file='work/tools.xml', tree_name='cycle'),
                dict(sa_behaviour_tag_name='AuthoredJob', tree_file='work/other.xml', tree_name='variant'),
                dict(sa_behaviour_tag_name='Unrelated', tree_file='elsewhere.xml', tree_name='unused')]
        report = discover(self.trees('AuthoredJob'), lambda name: rows)
        self.assertEqual({(c['file'], c['tree']) for c in report[0]['candidates']},
                         {('Libs/AI/work/tools.xml', 'cycle'), ('Libs/AI/work/other.xml', 'variant')})
        self.assertFalse(report[0]['unresolved'])

    def test_dynamic_and_fallback_requests_remain_explicit(self):
        dynamic = discover(self.trees('$nextJob'), lambda name: self.fail('Do not guess a dynamic job'))
        self.assertFalse(dynamic[0]['candidates'])
        self.assertTrue(dynamic[0]['unresolved'])
        fallback = discover(self.trees('Unknown', 'false'), lambda name: [])
        self.assertEqual(len(fallback[0]['unresolved']), 2)

    def test_direct_callback_follows_area_and_object_registrations(self):
        model = source('''<Root><CallBehavior Target="&quot;station&quot;" BehaviorName="&quot;use&quot;"/>
          <SmartObjectBehaviorTag preferredBehaviors="&quot;pickup&quot;" preferredBehaviorsOnly="&quot;true&quot;"/>
          </Root>''')
        tables = {
            'sa_behaviour_tag': [dict(sa_behaviour_tag_name='use', tree_file='work/area.xml', tree_name='areaUse')],
            'so_behaviour_tag': [dict(so_behaviour_tag_name='use', tree_file='work/prop.xml', tree_name='propUse'),
                                 dict(so_behaviour_tag_name='pickup', tree_file='work/prop.xml', tree_name='pickup')],
        }
        calls = discover(model['behavior_documents']['libs/ai/quests/q_test.xml']['trees'], tables.__getitem__)
        self.assertEqual({c['tree'] for c in calls[0]['candidates']}, {'areaUse', 'propUse'})
        self.assertEqual([c['tree'] for c in calls[1]['candidates']], ['pickup'])
        self.assertFalse(any(c['unresolved'] for c in calls))


if __name__ == '__main__':
    unittest.main()
