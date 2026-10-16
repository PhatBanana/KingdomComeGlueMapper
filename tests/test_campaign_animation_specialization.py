import copy
import unittest
import xml.etree.ElementTree as E
from test_campaign_behavior import source
import test_campaign_work_animations as animation_tests
from quest_import import ast
from campaign_behavior import convert_behaviors
from campaign_animation_specialization import specialize


def library(root):
    return dict(trees={'work':dict(variables=[],root=ast(E.fromstring(root)))})


class AnimationSpecializationTests(unittest.TestCase):
    def fixture(self, extra=''):
        return source('''<Root><HasGenderCheck Gender="&quot;Male&quot;" SoulWUID="&quot;this.id&quot;">
          <Then><IncludeTree File="&quot;final/jobs.xml&quot;" Name="&quot;work&quot;"/></Then>
          </HasGenderCheck>'''+extra+'''</Root>''', extra={
            'libs/ai/final/jobs.xml': library('<Root><PlayAnimation animation="&quot;MaleWork&quot;"/></Root>')})

    def test_branch_helper_is_specialized_without_relaxing_generic_helper(self):
        model = self.fixture()
        original = copy.deepcopy(model)
        native = animation_tests.WorkAnimationTests().gender_catalog()
        files, _, report = convert_behaviors([model], 'Converted', native)
        self.assertEqual(model, original)
        specialization = report['animation_specializations'][0]
        self.assertEqual(specialization['controllers'], ['male'])
        root = E.fromstring(files['AI/converted/q_test/quests/q_test.xml'])
        include = root.find('.//IncludeTree')
        self.assertIn('/__controller_variants/male/final/jobs.xml', include.get('File'))
        self.assertIn('AI/converted/q_test/__controller_variants/male/final/jobs.xml', files)
        self.assertNotIn('AI/converted/q_test/final/jobs.xml', files)

    def test_unconstrained_call_still_blocks_its_caller(self):
        model = self.fixture('<IncludeTree File="&quot;final/jobs.xml&quot;" Name="&quot;work&quot;"/>')
        files, _, _ = convert_behaviors([model], 'Converted', animation_tests.WorkAnimationTests().gender_catalog())
        self.assertNotIn('AI/converted/q_test/quests/q_test.xml', files)

    def test_recursive_helpers_specialize_once_and_keep_recursive_link(self):
        model = self.fixture()
        model['behavior_documents']['libs/ai/final/jobs.xml'] = library('''<Root><Sequence>
          <PlayAnimation animation="&quot;MaleWork&quot;"/>
          <IncludeTree File="&quot;final/jobs.xml&quot;" Name="&quot;work&quot;"/></Sequence></Root>''')
        files, _, report = convert_behaviors([model], 'Converted', animation_tests.WorkAnimationTests().gender_catalog())
        self.assertEqual(len(report['animation_specializations']), 1)
        path = 'AI/converted/q_test/__controller_variants/male/final/jobs.xml'
        self.assertEqual(E.fromstring(files[path]).find('.//IncludeTree').get('File'), "'"+path.removeprefix('AI/')+"'")

    def test_named_quest_calls_keep_their_ownership(self):
        model = self.fixture()
        model['behavior_documents']['libs/ai/quests/another.xml'] = library('<Root><Success/></Root>')
        model['behavior_documents']['libs/ai/final/jobs.xml'] = library('''<Root>
          <IncludeTree File="&quot;quests/another.xml&quot;" Name="&quot;work&quot;"/></Root>''')
        models, report = specialize([model])
        self.assertEqual(len(report), 1)
        tree = models[0]['behavior_documents'][report[0]['document']]['trees']['work']
        self.assertEqual(tree['root']['children'][0]['attributes']['File'], '"quests/another.xml"')


if __name__ == '__main__': unittest.main()
