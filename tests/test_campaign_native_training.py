import io
from pathlib import Path
import sys
import unittest
import xml.etree.ElementTree as ET
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from campaign_native_training import inspect_contract, emit, OUTPUTS
from campaign_quest_dependencies import predicate_references, objective_dependencies
from campaign_quest_graph import emit_project
from campaign_objective_conditions import counted_asset
from test_campaign_quest_graph import model as quest_fixture


def fixture():
    root = ET.Element('Database')
    nodes = ET.SubElement(root, 'Nodes')
    node = ET.SubElement(nodes, 'CombatTutorialNode', Name='native')
    ET.SubElement(node, 'Asset', Name='Tutor', Alias='any_actor')
    ET.SubElement(node, 'Constant', Name='Domain', Value='Basic')
    ET.SubElement(node, 'Constant', Name='InitialPhase', Value='0')
    ET.SubElement(node, 'Edge', From='active.State', To='IsActive')
    ET.SubElement(node, 'Edge', From='dialogue.finished', To='CustomStepEvent')
    sink = ET.SubElement(nodes, 'Output', Name='Output')
    for native, _ in OUTPUTS.values():
        ET.SubElement(sink, 'Edge', **{'From': 'native.' + native, 'To': native})
    return ET.tostring(root)


class NativeTrainingTests(unittest.TestCase):
    def contract(self, prefix='Quests/Final/'):
        stream = io.BytesIO()
        with zipfile.ZipFile(stream, 'w') as z:
            z.writestr(prefix + 'arbitrary/lesson.xml', fixture())
        with zipfile.ZipFile(stream) as z:
            return inspect_contract(z)

    def test_native_controller_has_no_quest_or_actor_special_cases(self):
        blob, report = emit('AnyTraining', 'Basic', self.contract())
        root = ET.fromstring(blob)
        node = root.find('.//CombatTutorialNode')
        self.assertEqual({e.get('To'):e.get('From') for e in node.findall('Edge')},
                         {'Tutor':'tutor', 'IsActive':'isactive', 'CustomStepEvent':'continue'})
        self.assertFalse(root.findall('.//Asset'))
        self.assertFalse(root.findall('.//State'))
        self.assertFalse(report['runtime_validated'])

    def test_hits_skips_and_failures_are_not_completion(self):
        blob, _ = emit('AnyTraining', 'Basic', self.contract())
        edges = ET.fromstring(blob).findall('.//Output/Edge')
        self.assertEqual([e.get('From') for e in edges if e.get('To') == 'finished'],
                         ['training.OnTutorialEnd'])

    def test_unknown_domain_and_incomplete_contract_fail(self):
        with self.assertRaises(ValueError): emit('Training', 'Unknown', self.contract())
        contract = self.contract()
        contract['Basic']['outputs'].remove('OnTutorialEnd')
        with self.assertRaises(ValueError): emit('Training', 'Basic', contract)
        self.assertEqual(self.contract('Quests/Testing/'), {})


class QuestPredicateDependenciesTests(unittest.TestCase):
    def test_linked_completion_uses_actual_dependency_state_and_own_started_guard(self):
        owner, lesson = quest_fixture(), quest_fixture()
        lesson['quest'] = 'another_lesson'
        lesson['tables']['quest']['rows'][0]['quest_name'] = 'another_lesson'
        owner['tables']['quest_objective']['rows'][1]['condition'] = "IsQuestCompleted('another_lesson')"
        owner['tables']['quest_tracked_asset'] = dict(rows=[dict(quest_id='42', objective_id='4',
            count='1', map_asset_id='marker', quest_asset_id='')])
        files, reports = emit_project([owner, lesson], 'Linked')
        host = ET.fromstring(files['Linked.xml'])
        timers = host.findall('.//Timer')
        self.assertEqual(len(timers), 1)
        self.assertEqual({e.get('From') for e in timers[0].findall('Edge')},
                         {'arbitrary_quest.source_state_changed', 'another_lesson.source_state_changed'})
        self.assertIn(b'another_lesson.completed', files['Linked.xml'])
        self.assertIn(b'arbitrary_quest.first_Started', files['Linked.xml'])
        self.assertIn(b'To="complete_first"', files['Linked.xml'])
        self.assertEqual(reports['quests'][0]['converted_linked_conditions'][0]['objective'], 'first')

    def test_missing_quest_or_counted_inventory_is_not_completed(self):
        owner = quest_fixture()
        owner['tables']['quest_objective']['rows'][1]['condition'] = "IsQuestCompleted('missing')"
        files, report = emit_project([owner], 'Linked')
        self.assertEqual(report['quests'][0]['converted_linked_conditions'], [])

        self.assertFalse(ET.fromstring(files['Linked.xml']).findall('.//Timer'))
        lesson = quest_fixture()
        lesson['quest'] = 'missing'
        lesson['tables']['quest']['rows'][0]['quest_name'] = 'missing'
        owner['tables']['quest_tracked_asset'] = dict(rows=[dict(quest_id='42', objective_id='4', count='1')])
        _, report = emit_project([owner, lesson], 'Linked')
        self.assertEqual(report['quests'][0]['converted_linked_conditions'], [])

    def test_only_explicit_map_only_tracking_is_exempt_from_counting(self):
        self.assertFalse(counted_asset(dict(count='1', map_asset_id='marker', quest_asset_id='')))
        self.assertTrue(counted_asset(dict(count='1', map_asset_id='marker', quest_asset_id='item')))
        self.assertTrue(counted_asset(dict(count='1', map_asset_id='marker')))

    def test_nested_function_references_survive_unsupported_sibling_checks(self):
        refs = list(predicate_references("done AND SomeUnconvertedCheck()",
                    {'done': "inner", 'inner': "IsQuestCompleted('other_lesson')"}))
        self.assertEqual(refs, [dict(quest='other_lesson', dynamic=False, operation='IsQuestCompleted')])

    def test_quoted_text_does_not_create_dependencies(self):
        self.assertEqual(list(predicate_references("Unknown('IsQuestCompleted(\\'fake\\')')")), [])

    def test_dynamic_names_are_reported_not_guessed(self):
        self.assertTrue(list(predicate_references('IsQuestCompleted(selectedQuest)'))[0]['dynamic'])

    def test_recursive_functions_fail_explicitly(self):
        with self.assertRaises(ValueError):
            list(predicate_references('a', {'a':'b', 'b':'a'}))

    def test_objective_dependencies_record_provenance_and_skip_self(self):
        model = dict(quest='owner', tables={'quest_objective':dict(rows=[dict(
            objective_id='42', objective_name='training',
            condition="IsQuestStarted('owner') AND IsQuestCompleted('other_lesson')")])})
        refs = list(objective_dependencies(model))
        self.assertEqual(len(refs), 1)
        self.assertEqual(refs[0]['quest'], 'other_lesson')
        self.assertEqual(refs[0]['site']['objective_id'], '42')


if __name__ == '__main__':
    unittest.main()
