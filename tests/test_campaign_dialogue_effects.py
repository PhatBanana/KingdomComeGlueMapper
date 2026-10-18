import copy
from pathlib import Path
import sys
import unittest
import xml.etree.ElementTree as E

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from campaign_dialogue import emit
from campaign_dialogue_effects import predicate
from campaign_dialogue_runtime import attach_dialogue
from campaign_quest_graph import emit_project
from test_campaign_dialogue_presentation import model as dialogue
from test_campaign_quest_graph import model as quest


class DialogueEffectsTests(unittest.TestCase):
    def stage(self):
        d, q = dialogue(), quest()
        d['topics']['1']['sequences'][0]['effects'] = [
            dict(quest_id='42', objective_id='4', action='1', order_by='1',
                 condition="IsObjectiveUnchanged('arbitrary_quest','first')"),
            dict(quest_id='42', objective_id='4', action='2', order_by='2',
                 condition="IsObjectiveStarted('arbitrary_quest','first')")]
        return d, q

    def test_effects_recheck_state_after_previous_effect_and_false_does_not_block_next(self):
        d, q = self.stage()
        blob, report = emit(d, 'conversation', [q])
        files = attach_dialogue(emit_project([q], 'world')[0], 'world', blob, report,
                                'arbitrary_quest.started')
        nodes = E.fromstring(files['world.xml']).find('./Skald/Project/Nodes')
        callbacks = E.fromstring(blob).findall('.//Sequence/Triggers/Port')
        self.assertEqual([c.get('Name') for c in callbacks], ['gm_sequence_active', 'effects_10'])
        self.assertEqual(report['actions'], {})
        # Exercise the emitted event topology against live objective state.
        # In particular, the second predicate must see the first mutation.
        for initial in ('Unchanged', 'Started', 'Completed'):
            state, mutations = [initial], []
            def dispatch(event):
                for node in nodes:
                    incoming = [e for e in node.findall('Edge') if e.get('From') == event]
                    for edge in incoming:
                        if node.tag == 'TriggerSequence':
                            dispatch(node.get('Name') + '.A')
                            dispatch(node.get('Name') + '.B')
                        elif node.tag == 'If':
                            value = node.find("Edge[@To='Condition']").get('From').split('_')[-1]
                            if value == state[0]: dispatch(node.get('Name') + '.True')
                        elif node.get('Name') == 'arbitrary_quest':
                            state[0] = {'start_first':'Started', 'complete_first':'Completed'}[edge.get('To')]
                            mutations.append(state[0])
                        else:
                            self.fail('Unexpected event target: ' + node.tag)
            dispatch('conversation.effects_10')
            self.assertEqual(state[0], 'Completed')
            self.assertEqual(mutations, {'Unchanged':['Started','Completed'],
                                         'Started':['Completed'], 'Completed':[]}[initial])

    def test_graph_predicate_preserves_precedence_and_rejects_dialogue_local_values(self):
        tree = predicate("Port('one') OR !Port('two') AND false")
        self.assertEqual(tree['op'], 'or')
        self.assertEqual(tree['children'][1]['op'], 'and')
        self.assertEqual(tree['children'][1]['children'][0]['op'], 'not')
        for unsupported in ("var('visited') == 1", 'unknown()', "Port('one') + 1", 'true false'):
            with self.subTest(unsupported=unsupported), self.assertRaises(ValueError): predicate(unsupported)

    def test_global_effect_snapshots_and_native_context_binding(self):
        from campaign_dialogue_effects import wire_program, global_snapshots
        tree=predicate("gvar('debt') > 1 AND Port('one')")
        action=dict(predicate=tree,quest='q',input='complete')
        script=global_snapshots([action])
        self.assertIn("Variables.GetGlobal('debt')",script)
        nodes=E.Element('Nodes');dest=E.SubElement(nodes,'Quest',Name='q')
        wire_program(nodes,'effect','talk.trigger',[action],{'one':'q.one'},lambda *a:dest,'talk.VariableContext')
        self.assertIsNotNone(nodes.find("Function[@MethodName='wh::dialogmodule::GetVariableContextValue']/Edge[@From='talk.VariableContext']"))
        self.assertIsNotNone(nodes.find("Function[@MethodName='Control::Compare']/Constant[@Value='Greater']"))

    def test_unsupported_conditional_effect_blocks_whole_dialogue(self):
        d, q = self.stage()
        d['topics']['1']['sequences'][0]['effects'][1]['condition'] = "var('local_only') == 1"
        with self.assertRaisesRegex(ValueError, 'graph-readable'):
            emit(d, 'conversation', [q])

    def test_attach_rejects_changed_objective_destination_without_mutating_files(self):
        d, q = self.stage()
        blob, report = emit(d, 'conversation', [q])
        report['action_programs']['effects_10'][1]['input'] = 'complete_missing'
        files = emit_project([q], 'world')[0]
        before = copy.deepcopy(files)
        with self.assertRaisesRegex(ValueError, 'Incompatible project port'):
            attach_dialogue(files, 'world', blob, report, 'arbitrary_quest.started')
        self.assertEqual(files, before)


if __name__ == '__main__': unittest.main()
