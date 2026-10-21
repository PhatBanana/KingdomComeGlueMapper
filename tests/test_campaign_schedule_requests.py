import copy
import unittest
import xml.etree.ElementTree as E

from campaign_behavior import convert_behaviors
from campaign_dependencies import DependencyImporter
from campaign_schedule_requests import dependencies, request
from campaign_quest_bridge import UnsupportedOperation
from quest_import import ast
from test_campaign_behavior import source, catalog


VALUES = "add(true),handle('work_handle'),name('public_job'),immediate(true),once(true),priority(55),sourceId($this.id)"


def message(values=VALUES):
    return ast(E.Element('InstantSendMessageToNPC', target='actors[worker]',
                        type='daycycle:change', values=values))


def fixture():
    m = source('<Root><Behavior><Sequence/></Behavior></Root>')
    doc = 'libs/ai/quests/q_test.xml'
    trees = m['behavior_documents'][doc]['trees']
    trees['onUpdate']['variables'].append(dict(name='actors', type='common:wuid', form='associative', values=''))
    trees['onUpdate']['root']['children'][0]['children'][0]['children'].append(message())
    trees['implementation'] = dict(variables=[], root=ast(E.fromstring('<Root><Success/></Root>')))
    m['controller_registration'] = dict(entry_points=[dict(kind='behavior_callback',
        name='public_job', file='quests/q_test.xml', tree='implementation')])
    return m, doc, trees


class ScheduleRequestsTests(unittest.TestCase):
    def test_source_policy_and_registration_are_retained(self):
        m, doc, trees = fixture(); original = copy.deepcopy(m)
        records = dependencies(m, trees['onUpdate']['root'])
        self.assertEqual(records[0]['callback'], dict(document=doc, tree='implementation'))
        self.assertEqual(records[0]['actor'], 'actors[worker]')
        self.assertEqual(records[0]['handle'], 'work_handle')
        self.assertEqual(records[0]['priority'], 55)
        self.assertTrue(records[0]['once'])
        self.assertEqual([a['op'] for a in records[0]['ancestors']], ['Root', 'Behavior', 'Sequence'])
        self.assertEqual(m, original)

    def test_guarded_requests_are_not_flattened(self):
        m, _, trees = fixture()
        root = ast(E.fromstring('<Root><IfCondition condition="$ready"><Then><Sequence/></Then></IfCondition></Root>'))
        root['children'][0]['children'][0]['children'][0]['children'] = [message()]
        record = dependencies(m, root)[0]
        self.assertEqual(record['ancestors'][1]['attributes']['condition'], '$ready')
        self.assertEqual(record['ancestors'][2]['op'], 'Then')

    def test_remove_keeps_actor_and_handle_without_inventing_a_callback(self):
        self.assertEqual(request(message("add(false),handle('work_handle')")),
                         dict(actor='actors[worker]', handle='work_handle', add=False))

    def test_multiline_source_and_false_policies(self):
        result = request(message(VALUES.replace(',', ',\n').replace('once(true)', 'once(false)')
                                 .replace('immediate(true)', 'immediate(false)')))
        self.assertFalse(result['once']); self.assertFalse(result['immediate'])

    def test_omitted_once_keeps_source_boolean_default(self):
        result = request(message(VALUES.replace('once(true),', '')))
        self.assertFalse(result['once'])

    def test_incomplete_dynamic_and_ambiguous_policies_fail(self):
        for value in (VALUES.replace('priority(55),', ''), VALUES + ',priority(44)',
                      VALUES.replace('55', '256'), VALUES.replace("'public_job'", '$job'),
                      VALUES.replace("'work_handle'", '$handle'), VALUES + ',unknown(true)',
                      "add(false),handle('work_handle'),once(true)"):
            with self.subTest(value=value), self.assertRaises(UnsupportedOperation):
                request(message(value))

    def test_unregistered_callback_is_reported_without_guessing(self):
        m, _, trees = fixture(); m['controller_registration']['entry_points'] = []
        record = dependencies(m, trees['onUpdate']['root'])[0]
        self.assertIn('registration', record['error']); self.assertNotIn('callback', record)

    def test_cloned_message_type_cannot_make_controller_executable(self):
        m, _, _ = fixture()
        importer = DependencyImporter({}, {'ai_types': {'daycycle:change': 'cloned_message'}})
        files, _, report = convert_behaviors([m], 'Imported', catalog(), importer=importer)
        caller = next(r for r in report['trees'] if r['tree'] == 'onUpdate')
        self.assertFalse(caller['native_emitted'])
        self.assertTrue(any('consumer' in r['reason'] for r in caller['unresolved']))
        self.assertEqual(caller['schedule_requests'][0]['callback']['tree'], 'implementation')
        self.assertNotIn('onUpdate', [t.get('name') for b in files.values() for t in E.fromstring(b)])

    def test_controller_local_call_withholds_caller_when_registered_worker_fails(self):
        m, doc, trees = fixture()
        trees['onUpdate']['root'] = ast(E.fromstring('<Root><Success/></Root>'))
        trees['implementation']['root'] = ast(E.fromstring(
            '<Root><CallBehavior Target="__object.id" BehaviorName="second_tag"/></Root>'))
        trees['broken'] = dict(variables=[], root=ast(E.fromstring('<Root><UnsupportedExercise/></Root>')))
        m['controller_registration']['entry_points'].append(dict(kind='behavior_callback',
            name='second_tag', file='quests/q_test.xml', tree='broken'))
        _, _, report = convert_behaviors([m], 'Imported', catalog())
        caller = next(r for r in report['trees'] if r['tree'] == 'implementation')
        self.assertFalse(caller['native_emitted'])
        self.assertIn(('q_test', doc, 'broken'), caller['blocked_includes'])

    def test_controller_local_call_retains_public_tag_and_scope(self):
        m, _, trees = fixture()
        trees['onUpdate']['root'] = ast(E.fromstring('<Root><Success/></Root>'))
        trees['implementation']['root'] = ast(E.fromstring(
            '<Root><CallBehavior Target="__object.id" BehaviorName="public_job"/></Root>'))
        files, _, report = convert_behaviors([m], 'Imported', catalog())
        self.assertEqual(report['blocked_trees'], 0)
        call = E.fromstring(next(iter(files.values()))).find('.//CallBehavior')
        self.assertEqual(call.get('BehaviorName'), "'public_job'")
        self.assertEqual(call.get('Target'), '$__object.id')

    def test_perception_operations_retain_target_guard_and_order(self):
        m = source('<Root><IfCondition condition="$phase &lt; 10"><Sequence>'
                   '<DisablePerception ToWhom="actor" Perceptor="true" Perceptible="true"/>'
                   '<EnablePerception ToWhom="actor" Perceptor="true" Perceptible="true"/>'
                   '</Sequence></IfCondition></Root>')
        files, _, _ = convert_behaviors([m], 'Imported', catalog())
        root = E.fromstring(next(iter(files.values())))
        sequence = root.find('.//IfCondition/Sequence')
        self.assertEqual([n.tag for n in sequence], ['DisablePerception', 'EnablePerception'])
        self.assertTrue(all(n.get('ToWhom') == '$actor' for n in sequence))
        native = catalog(); del native['nodes']['EnablePerception']
        self.assertFalse(convert_behaviors([m], 'Imported', native)[0])


if __name__ == '__main__': unittest.main()
