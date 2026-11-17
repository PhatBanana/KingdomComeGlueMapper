import copy
from pathlib import Path
import sys
import unittest
import xml.etree.ElementTree as E

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from campaign_controller_patterns import PATTERN, Unmatched, lower, match
from campaign_dialogue_lifecycle import expose_cancel
from campaign_quest_graph import emit_project
from quest_lab.graph import Graph
from quest_lab.source import Source
from test_campaign_quest_graph import model as quest_model

QUEST = 'arbitrary_quest'
DOCUMENT = 'libs/ai/quests/' + QUEST + '.xml'


def node(op, *children, **attributes):
    return dict(op=op, attributes={k: v if k == 'saveVersion' else '"' + v + '"' for k, v in attributes.items()},
                children=list(children), text='')


def rule(objective='second', state='Completed', function='CancelQuest', quest=QUEST, variable='questObjectiveUpdate'):
    return node('IfCondition',
                node('QuestCondition',
                     node('Then', node('SetQuest', questName=quest, objectiveName='', paramInt='0', function=function)),
                     node('Else', node('Success')),
                     quest=quest, function='IsQuestStarted', failSubtMissing='false'),
                failOnCondition='false',
                condition="$%s.State == $enum:ObjectiveState.%s & $%s.ObjectiveName == '%s'" % (variable, state, variable, objective))


def controller(*rules, init=()):
    loop = node('Loop', node('ProcessMessage', node('Switch', *(rules or (rule(),)), node('DefaultBranch', node('Success'))),
                             Atomic='true', timeout='-1', timeType='GameTime', variable='questObjectiveUpdate',
                             senderInfo='', inbox='QuestMailbox', condition='', answerVar=''), count='-1')
    children = ([node('OnInit', *init)] if init else []) + [node('Behavior', loop)]
    return node('Root', *children, OneTimeOnly='false', FailState='Error')


def with_controller(root=None):
    m = quest_model()
    m['behavior_documents'] = {DOCUMENT: dict(trees={'onUpdate': dict(root=root or controller())})}
    return m


def emitted(m):
    files, _ = emit_project([m], 'Example')
    return files['Example/' + QUEST + '.xml'], files


def find(root, *path):
    for index in path: root = root['children'][index]
    return root


class MatchTests(unittest.TestCase):
    def test_the_shape_is_matched_and_reported_by_tree(self):
        found = match(with_controller())
        self.assertEqual(found['pattern'], PATTERN)
        self.assertEqual(found['rules'], [dict(objective='second', state='Completed', guard='IsQuestStarted', function='CancelQuest')])
        self.assertEqual([(c['document'], c['tree'], c['skipped']) for c in found['consumed']], [(DOCUMENT, 'onUpdate', [])])
        two = match(with_controller(controller(rule('first'), rule('second'))))
        self.assertEqual([r['objective'] for r in two['rules']], ['first', 'second'])

    def test_a_save_migration_branch_is_skipped_and_listed(self):
        migration = node('IfCondition', node('SetQuestObjective', quest='q_other', objective='x', function='CancelObjective'),
                         failOnCondition='false', condition='$__version.loaded < $enum:gameVersion.Ver_01_09')
        found = match(with_controller(controller(init=[migration])))
        self.assertEqual(found['consumed'][0]['skipped'], [dict(condition='$__version.loaded < $enum:gameVersion.Ver_01_09',
            reason='migrates an old save; does not run in a new game')])
        with self.assertRaisesRegex(Unmatched, 'OnInit does more'):
            match(with_controller(controller(init=[node('SetQuest', questName=QUEST, function='StartQuest')])))

    def test_a_quest_without_a_controller_has_nothing_to_lower(self):
        m = quest_model()
        self.assertEqual(match(m), dict(pattern=None, consumed=[], rules=[]))
        blob, _ = emitted(m)
        self.assertEqual(lower(blob, m)[0], blob)

    def test_the_match_does_not_depend_on_the_quests_name(self):
        m = with_controller(controller(rule(quest='renamed')))
        m['quest'] = 'renamed'
        m['behavior_documents'] = {'libs/ai/quests/renamed.xml': m['behavior_documents'][DOCUMENT]}
        self.assertEqual(match(m)['rules'][0]['objective'], 'second')

    def test_anything_else_is_refused(self):
        def changed(edit):
            root = controller()
            edit(root)
            return with_controller(root)
        rule_path = (0, 0, 0, 0, 0)          # Behavior > Loop > ProcessMessage > Switch > IfCondition
        cases = {
            'another state': controller(rule(state='Started')),
            'unknown objective': controller(rule(objective='nowhere')),
            'another action': controller(rule(function='StartQuest')),
            'another quest': controller(rule(quest='q_other')),
            'another variable': controller(rule(variable='other')),
            'two rules on one state': controller(rule(), rule()),
            'no rule': node('Root', node('Behavior', node('Loop', node('ProcessMessage', node('Switch', node('DefaultBranch', node('Success'))),
                            variable='v', inbox='QuestMailbox', condition='', senderInfo='', answerVar=''), count='-1'))),
            'finite loop': changed(lambda r: find(r, 0, 0)['attributes'].update(count='"3"'))['behavior_documents'][DOCUMENT]['trees']['onUpdate']['root'],
            'another inbox': changed(lambda r: find(r, 0, 0, 0)['attributes'].update(inbox='"Other"'))['behavior_documents'][DOCUMENT]['trees']['onUpdate']['root'],
            'message filter': changed(lambda r: find(r, 0, 0, 0)['attributes'].update(condition='"$x"'))['behavior_documents'][DOCUMENT]['trees']['onUpdate']['root'],
            'extra operation': changed(lambda r: r['children'].append(node('ExecuteLua')))['behavior_documents'][DOCUMENT]['trees']['onUpdate']['root'],
            'else does something': changed(lambda r: find(r, *rule_path, 0, 1)['children'].__setitem__(0, node('SetQuest', questName=QUEST, function='StartQuest')))['behavior_documents'][DOCUMENT]['trees']['onUpdate']['root'],
            'two actions': changed(lambda r: find(r, *rule_path, 0, 0)['children'].append(node('Success')))['behavior_documents'][DOCUMENT]['trees']['onUpdate']['root'],
            'objective action': changed(lambda r: find(r, *rule_path, 0, 0, 0)['attributes'].update(objectiveName='"first"'))['behavior_documents'][DOCUMENT]['trees']['onUpdate']['root'],
            'default does something': changed(lambda r: find(r, 0, 0, 0, 0, 1)['children'].__setitem__(0, node('ExecuteLua')))['behavior_documents'][DOCUMENT]['trees']['onUpdate']['root'],
            'guard is another test': changed(lambda r: find(r, *rule_path, 0)['attributes'].update(function='"IsQuestCompleted"'))['behavior_documents'][DOCUMENT]['trees']['onUpdate']['root'],
        }
        for label, root in cases.items():
            with self.subTest(label):
                m = with_controller(root)
                blob, _ = emitted(m)
                with self.assertRaises(Unmatched): match(m)
                with self.assertRaises(Unmatched): lower(blob, m)


class LowerTests(unittest.TestCase):
    def lowered(self):
        m = with_controller()
        before = copy.deepcopy(m)
        blob, files = emitted(m)
        out, report = lower(blob, m)
        self.assertEqual(m, before)
        return E.fromstring(out).find('./Skald/Quest'), report, out, files, m

    def test_the_rule_is_an_if_on_the_objective_event_behind_the_quest_guard(self):
        quest, report, _, _, _ = self.lowered()
        nodes = {n.get('Name'): n for n in quest.find('Nodes')}
        edges = lambda name: [(e.get('From'), e.get('To')) for e in nodes[name].findall('Edge')]
        self.assertEqual(edges('lowered_controller_5_completed'),
                         [('quest_progress.Active', 'Condition'), ('objective_5.OnCompleted', 'Exec')])
        self.assertEqual(edges('lowered_cancel_if_active'), [('quest_progress.Active', 'Condition'), ('cancel', 'Exec'),
                                                             ('lowered_controller_5_completed.True', 'Exec')])
        self.assertIn(('lowered_cancel_if_active.True', 'SetFailed'), edges('quest_progress'))
        self.assertIn(('lowered_cancel_canceled.State', 'canceled'), edges('Output'))
        ports = {p.get('Name'): (p.get('Direction'), p.get('Type')) for p in quest.find('Ports')}
        self.assertEqual((ports['cancel'], ports['canceled']), (('In', 'trigger'), ('Out', 'bool')))
        self.assertEqual(report['rules'][0]['native'], 'lowered_controller_5_completed')
        self.assertEqual((report['pattern'], report['runtime_verified']), (PATTERN, False))

    def test_a_second_lowering_is_refused(self):
        _, _, out, _, m = self.lowered()
        with self.assertRaisesRegex(ValueError, 'already lowered'): lower(out, m)

    def run_quest(self, steps):
        _, _, out, files, _ = self.lowered()
        files = dict(files, **{'Example/' + QUEST + '.xml': out})
        graph = Graph(Source.blobs(files), QUEST)
        self.assertEqual(graph.unsupported, [])
        for port in steps:
            graph.fire(port); graph.drain(); graph.advance_to(graph.now)
        return {p: bool(graph.value('output.' + p)) for p in ('started', 'completed', 'failed', 'canceled', 'second_Completed')}

    def test_in_the_lab_the_objective_cancels_a_started_quest_only(self):
        self.assertEqual(self.run_quest(['activate', 'start', 'complete_second']),
                         dict(started=False, completed=False, failed=True, canceled=True, second_Completed=True))
        # Not started: the source guard keeps the rule from firing, as in KCD1.
        self.assertEqual(self.run_quest(['complete_second']),
                         dict(started=False, completed=False, failed=False, canceled=False, second_Completed=True))
        self.assertEqual(self.run_quest(['activate', 'start', 'complete_first']),
                         dict(started=True, completed=False, failed=False, canceled=False, second_Completed=False))


class CancelTests(unittest.TestCase):
    def test_cancel_fails_an_active_quest_and_always_records_the_word(self):
        blob, files = emitted(quest_model())
        out = expose_cancel(blob)
        self.assertEqual(expose_cancel(out), out)
        def run(steps):
            graph = Graph(Source.blobs(dict(files, **{'Example/' + QUEST + '.xml': out})), QUEST)
            for port in steps:
                graph.fire(port); graph.drain()
            return tuple(bool(graph.value('output.' + p)) for p in ('started', 'failed', 'canceled', 'unchanged'))
        self.assertEqual(run(['start', 'cancel']), (False, True, True, False))
        self.assertEqual(run(['cancel']), (False, False, True, True))        # never started: not a failed journal entry
        self.assertEqual(run(['start']), (True, False, False, False))

    def test_sources_must_be_nodes_of_the_quest_and_a_foreign_cancel_is_refused(self):
        blob, _ = emitted(quest_model())
        with self.assertRaisesRegex(ValueError, 'not a node of the quest'): expose_cancel(blob, ['nowhere.True'])
        with self.assertRaisesRegex(ValueError, 'not a node of the quest'): expose_cancel(blob, ['cancel'])
        taken = blob.replace(b'<Port Name="fail" ', b'<Port Name="cancel" Direction="In" Type="trigger" /><Port Name="fail" ', 1)
        self.assertNotEqual(taken, blob)
        with self.assertRaisesRegex(ValueError, 'different cancel'): expose_cancel(taken)
        with self.assertRaises(ValueError): expose_cancel(b'<Database><Skald><Module Name="m"/></Skald></Database>')
        twice = expose_cancel(expose_cancel(blob, ['objective_4.OnCompleted']), ['objective_4.OnCompleted', 'objective_5.OnCompleted'])
        gate = E.fromstring(twice).find(".//If[@Name='lowered_cancel_if_active']")
        self.assertEqual([e.get('From') for e in gate.findall('Edge') if e.get('To') == 'Exec'],
                         ['cancel', 'objective_4.OnCompleted', 'objective_5.OnCompleted'])


if __name__ == '__main__':
    unittest.main()
