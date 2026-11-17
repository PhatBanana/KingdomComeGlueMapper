"""Converter C2: the controller's half of the scene seam."""
from pathlib import Path
import sys
import unittest
import xml.etree.ElementTree as E
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
import campaign_controller_contracts as contracts
import campaign_controller_scenes as scenes

DOCUMENT = 'libs/ai/quests/q_example.xml'


def node(op, children=(), **attributes):
    return dict(op=op, attributes=attributes, children=list(children), text='')


def send(values, target='this.id', op='InstantSendMessageToNPC'):
    return node(op, target=target, type='cutscene', values=values)


def model(sends, trees=('cutscene_a', 'cutscene_b'), automaton=1, worker=()):
    include = node('IncludeTree', File='"final/questUtils.xml"', Name='"cutsceneAutomaton"', nodeLabel='1')
    entry = node('Root', [node('Parallel', [node('Sequence', list(sends))] + [dict(include) for _ in range(automaton)])])
    documents = dict(entry=entry, worker=node('Root', list(worker)), **{name: node('Root', [node('Success')]) for name in trees})
    points = [dict(file='quests/q_example.xml', tree='entry', kind='on_update_tree'),
              dict(file='quests/q_example.xml', tree='worker', kind='behavior_callback', name='worker')]
    return dict(quest='q_example', controller_registration=dict(entry_points=points),
                behavior_documents={DOCUMENT: dict(trees={name: dict(variables=[], root=root) for name, root in documents.items()})})


def shape(tree):
    return (tree['op'], [shape(child) for child in tree['children']]) if tree['children'] else tree['op']


class SceneSeamTests(unittest.TestCase):
    def test_an_owned_request_fires_the_module_and_the_automaton_becomes_the_dispatcher(self):
        source = model([send("alias('a'), state($enum:cutsceneState.doStart)"),
                        send("alias('b'), saveGameQuest('q_other'), saveGameObjective('saved'), dialogFadeIn(true)"),
                        send("alias('c')")])
        report = scenes.apply(source, {'a', 'b'})
        trees = source['behavior_documents'][DOCUMENT]['trees']
        sequence, include = trees['entry']['root']['children'][0]['children']
        self.assertEqual([(n['op'], n['attributes']) for n in sequence['children'][:2]],
                         [('SceneSignal', dict(module='gm_q_example_scenes', port='play_a')),
                          ('SceneSignal', dict(module='gm_q_example_scenes', port='play_b'))])
        self.assertEqual(sequence['children'][2]['op'], 'InstantSendMessageToNPC')
        self.assertEqual(include['attributes'], dict(File='"quests/q_example.xml"', Name='"q_example_scene_dispatch"', nodeLabel='1'))
        self.assertEqual((report['requests'], report['converted_requests'], report['not_owned'], report['dispatcher']),
                         (3, 2, dict(c=1), 'q_example_scene_dispatch'))
        self.assertEqual(report['aliases']['b'], dict(requests=1, converted=True, reason=None,
                                                      save=dict(quest='q_other', objective='saved'), playback_fields=['dialogFadeIn']))
        self.assertEqual([(w['module_port'], w['type'], w['exists_in_c5']) for w in report['wiring'] if w['alias'] == 'a'],
                         [('play_a', 'trigger', True), ('pending_a', 'bool', False), ('done_a', 'trigger', False)])
        body = trees['q_example_scene_dispatch']['root']['children'][0]['children'][0]
        plain, saving = body['children']
        self.assertEqual(shape(plain), ('Loop', [('ScenePending', [('Sequence', [
            ('SuppressFailure', ['IncludeTree']), 'SceneSignal', ('ScenePending', ['Success'])])])]))
        steps = saving['children'][0]['children'][0]['children']
        self.assertEqual([s['op'] for s in steps], ['SuppressFailure', 'QuestObjectiveCondition', 'QuestObjectiveCondition',
                                                    'SceneSignal', 'ScenePending'])
        self.assertEqual(steps[0]['children'][0]['attributes'], dict(File='"quests/q_example.xml"', Name='"cutscene_b"'))
        self.assertEqual([(s['attributes']['function'], s['attributes']['quest'], s['attributes']['objective'],
                           s['children'][0]['op'], s['children'][0]['children'][0]['attributes']['function']) for s in steps[1:3]],
                         [('"IsObjectiveUnchanged"', '"q_other"', '"saved"', 'Then', '"StartObjective"'),
                          ('"IsObjectiveStarted"', '"q_other"', '"saved"', 'Then', '"CompleteObjective"')])
        self.assertEqual((steps[3]['attributes']['port'], steps[4]['attributes']['port'], steps[4]['attributes']['Negation'],
                          saving['children'][0]['attributes']['Negation']), ('done_b', 'pending_b', '"true"', '"false"'))

    def test_a_request_the_controller_cannot_serve_leaves_the_alias_alone(self):
        cases = [(["alias('a'), onBeginEvent(true)"], {}, 'fields the controller cannot serve: onBeginEvent'),
                 (["alias('a'), state($enum:cutsceneState.onEnd)"], {}, 'request does not start a scene'),
                 (["alias('a')", "alias('a'), saveGameObjective('s')"], {}, 'requests disagree on the save objective'),
                 (["alias('a'), saveGameObjective($objective)"], {}, 'save objective is not a literal name'),
                 (["alias('a')"], dict(trees=('cutscene_b',)), 'no cutscene_a tree'),
                 (["alias('a')"], dict(automaton=0), 'the entry tree does not include the scene automaton exactly once'),
                 (["alias('a')"], dict(automaton=2), 'the entry tree does not include the scene automaton exactly once'),
                 (["alias('a') extra"], {}, None)]
        for values, options, reason in cases:
            source = model([send(v) for v in values], **options)
            before = [shape(t['root']) for t in source['behavior_documents'][DOCUMENT]['trees'].values()]
            report = scenes.apply(source, {'a'})
            self.assertEqual((report['converted_requests'], report['dispatcher']), (0, None))
            self.assertEqual([shape(t['root']) for t in source['behavior_documents'][DOCUMENT]['trees'].values()], before)
            if reason:
                self.assertEqual(report['aliases']['a']['reason'], reason)
        for target, op, reason in (('t_actors[x]', 'InstantSendMessageToNPC', 'request is not an instant send to the controller'),
                                   ('this.id', 'SendMessageToNPC', 'request is not an instant send to the controller')):
            self.assertEqual(scenes.apply(model([send("alias('a')", target, op)]), {'a'})['aliases']['a']['reason'], reason)
        npc = model([], worker=[send("alias('a')")])
        self.assertEqual(scenes.apply(npc, {'a'})['aliases']['a']['reason'],
                         'request to this.id from a tree the controller may not run itself')
        self.assertEqual(scenes.apply(model([], worker=[send("alias('a')", '__object.id')]), {'a'})['converted_requests'], 1)
        self.assertEqual(scenes.apply(model([send("alias('a')")]), set())['not_owned'], dict(a=1))

    def test_the_generated_operations_lower_to_bridge_signals_and_context_barriers(self):
        import campaign_behavior
        contracts.register()
        catalog = dict(nodes={op: dict(attributes=list(fields), children=[]) for op, fields in campaign_behavior.CONTRACTS.items()},
                       variable_types=[], enum_types=[])
        compiler = campaign_behavior.BehaviorCompiler([], 'C2', catalog)
        record = dict(unresolved=[], buff_dependencies=[], item_dependencies=[], includes=[])
        pending = node('ScenePending', [node('SceneSignal', module='gm_q_example_scenes', port='done_a')],
                       module='gm_q_example_scenes', port='pending_a', Negation='"false"', RunLogic='"KeepRunning"')
        emitted = compiler.lower_node(pending, 'q_example', DOCUMENT, 'dispatch', 'Root', record)
        self.assertEqual(record['unresolved'], [])
        (context, condition), = compiler.bridge.conditions.items()
        (signal, action), = compiler.bridge.actions.items()
        self.assertEqual(E.tostring(emitted, encoding='unicode'),
                         '<GameContextBarrier context="%s" Negation="false" RunLogic="KeepRunning"><SendAIConceptSignal_%s /></GameContextBarrier>'
                         % (context, signal))
        self.assertEqual(((condition['quest'], condition['port'], condition['kind']), (action['quest'], action['port'], action['kind'])),
                         (('gm_q_example_scenes', 'pending_a', 'condition'), ('gm_q_example_scenes', 'done_a', 'action')))
        files, wiring = compiler.bridge.emit()
        self.assertEqual(sorted((w['direction'], w['quest'], w['quest_port']) for w in wiring),
                         [('action', 'gm_q_example_scenes', 'done_a'), ('condition', 'gm_q_example_scenes', 'pending_a')])


if __name__ == '__main__': unittest.main()
