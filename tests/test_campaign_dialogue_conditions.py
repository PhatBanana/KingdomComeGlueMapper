import sys
from pathlib import Path
import unittest
import xml.etree.ElementTree as E

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from campaign_dialogue_conditions import QuestConditions
from campaign_dialogue import emit, resolve
from campaign_dialogue_runtime import attach_dialogue
from campaign_quest_graph import emit_project
from test_campaign_quest_graph import model as quest
from test_campaign_dialogue_presentation import model as dialogue


class ConditionsTests(unittest.TestCase):
    def test_database_function_item_dependencies_and_local_variables(self):
        item = '11111111-2222-3333-4444-555555555555'
        functions = {'owns_tools': "GetAmountOfActorItems('" + item + "') > 0"}
        compiler = QuestConditions([quest()], functions, [item])
        converted = compiler.compile("var('visited') == 0 AND owns_tools")
        self.assertIn("var('visited') == 0", converted)
        self.assertIn("CountOfActorItems('" + item + "') > 0", converted)
        with self.assertRaisesRegex(ValueError, 'Unregistered dialogue item'):
            QuestConditions([quest()], functions).compile('owns_tools')
        for bad in ["var('visited')", "var('visited') + 1", "var('visited') > ExecuteLua('x')"]:
            with self.subTest(bad=bad), self.assertRaises(ValueError): compiler.compile(bad)

    def test_source_function_dependencies_expand_without_quest_specific_rules(self):
        compiler = QuestConditions([quest()], {'nested': "IsObjectiveCompleted('arbitrary_quest','second')",
                                               'ready': "IsQuestStarted('arbitrary_quest') AND !nested"})
        output = compiler.compile('ready OR nested')
        self.assertIn(' OR ', output)
        self.assertEqual({b['output'] for b in compiler.bindings.values()}, {'started', 'second_Completed'})
        cyclic = QuestConditions([quest()], {'a': 'b', 'b': 'a'})
        with self.assertRaisesRegex(ValueError, 'Cyclic dialogue function'):
            cyclic.compile('a')
        self.assertEqual(cyclic.bindings, {})
        malformed = QuestConditions([quest()], {'ready': "IsQuestStarted('arbitrary_quest') AND unknown"})
        with self.assertRaises(ValueError): malformed.compile('ready')
        self.assertEqual(malformed.bindings, {})

    def test_conditions_are_wired_to_original_objectives(self):
        q, d = quest(), dialogue()
        d['topics']['1']['sequences'][0]['entry']['entry_condition'] = (
            "IsObjectiveStarted('arbitrary_quest','first') OR "
            "!IsObjectiveCompleted('arbitrary_quest','second')")
        blob, report = emit(d, 'conversation', [q])
        files, _ = emit_project([q], 'world')
        files = attach_dialogue(files, 'world', blob, report, 'arbitrary_quest.started')
        root = E.fromstring(files['world.xml'])
        edges = root.findall('.//conversation/Edge')
        self.assertEqual({e.get('From') for e in edges},
                         {'arbitrary_quest.started', 'arbitrary_quest.first_Started',
                          'arbitrary_quest.second_Completed'})
        condition = E.fromstring(blob).find('.//Sequence').get('EntryCondition')
        self.assertTrue(condition.startswith("Port('active') AND ("))
        self.assertIn(' OR !(', condition)
        broken = dict(report, conditions={})
        with self.assertRaisesRegex(ValueError, 'input ports'):
            attach_dialogue(*[emit_project([q], 'world')[0], 'world', blob, broken, 'arbitrary_quest.started'])

    def test_unsupported_or_malformed_expressions_cannot_change_bindings(self):
        compiler = QuestConditions([quest()])
        for value in ["IsQuestStarted('missing')", "IsObjectiveStarted('arbitrary_quest','absent')",
                      "IsQuestStarted('arbitrary_quest') OR ExecuteLua('x')",
                      "IsQuestStarted('arbitrary_quest'); true", '(1 OR 0', '1 0', 'skillCheckSuccess']:
            with self.subTest(value=value), self.assertRaises(ValueError): compiler.compile(value)
            self.assertEqual(compiler.bindings, {})
        self.assertEqual(compiler.compile('!(0 OR 1) AND 1'), '!((false OR true)) AND true')
        self.assertEqual(compiler.compile('FALSE | TRUE & !FALSE'), 'false OR true AND !(false)')

    def test_unnamed_branch_keeps_original_identity(self):
        tables = dict(topic=[dict(topic_id='7', label='')], sequence=[dict(sequence_id='8', priority='0', next='0')],
                      topic2sequence=[dict(topic_id='7', sequence_id='8')], sequence_line=[], response=[],
                      v_dialogue_commands=[], v_response_wave_file_recorded=[], sequence2quest_objective=[],
                      sequence_flowchart=[], topictorole=[], v_branch=[dict(start_topic='7')],
                      v_topic2subchapter_id=[], dialogue_mood=[])
        imported = resolve(tables, start_topic='7')
        self.assertEqual(imported['alias'], '')
        self.assertEqual(imported['start_topic'], '7')
        for kwargs in [dict(alias=''), dict(start_topic='8'), dict(alias='x', start_topic='7')]:
            with self.assertRaises(ValueError): resolve(tables, **kwargs)


if __name__ == '__main__': unittest.main()
