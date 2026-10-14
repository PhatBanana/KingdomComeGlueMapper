import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from campaign_quest_dialogues import discover, reachable_behaviors, import_participants, scope_to_quest


class QuestDialogueDiscoveryTests(unittest.TestCase):
    def test_source_ownership_excludes_later_references_but_keeps_called_dependencies(self):
        tables = dict(v_topic2subchapter_id=[dict(start_topic='1',skald_subchapter_id='a'),
            dict(start_topic='2',skald_subchapter_id='b'),dict(start_topic='3',skald_subchapter_id='b')],
            sequence=[dict(sequence_id='10',next='4'),dict(sequence_id='30',next='0')],
            topic2sequence=[dict(topic_id='1',sequence_id='10'),dict(topic_id='3',sequence_id='30')])
        closure = dict(quest_id='q', branches=[dict(source=dict(start_topic=str(i))) for i in range(1,4)],
            references=[dict(topic_id='3',sites=[dict(kind='behavior_dialogue_alias')])])
        result = scope_to_quest(closure,tables,[dict(quest_id='q',skald_subchapter_id='a')])
        self.assertEqual([b['source']['start_topic'] for b in result['branches']],['1','3'])
        self.assertEqual(result['reachable_topics'],['1','3','4'])
        self.assertEqual(len(closure['branches']),3)
    def test_registered_callback_scope_does_not_import_unrelated_trees(self):
        model = dict(controller_registration=dict(entry_points=[dict(file='quests/a.xml', tree='start')]),
            includes=[dict(document='libs/ai/quests/a.xml', tree='start', target='libs/ai/final/helper.xml', name='work')],
            work_program_calls=[dict(document='libs/ai/final/helper.xml', tree='work', candidates=[
                dict(file='Libs/AI/final/job.xml', tree='run')])])
        self.assertEqual(reachable_behaviors(model), {('libs/ai/quests/a.xml','start'),
            ('libs/ai/final/helper.xml','work'), ('libs/ai/final/job.xml','run')})

    def test_dialogue_only_actor_is_requested_without_quest_asset_binding(self):
        class Tables:
            def get(self, name):
                return dict(rows={'rpg/role': [dict(role_id='1', metarole_id='npc'), dict(role_id='2', metarole_id='player')],
                    'rpg/metarole': [dict(metarole_id='npc', metarole_name='NPC'), dict(metarole_id='player', metarole_name='Player')],
                    'rpg/soul2role': [dict(role_id='1', soul_id='source_actor')]}[name])
        class Importer:
            def __init__(self): self.requests = []
            def ensure(self, group, identity, site):
                self.requests.append((group, identity, site))
                return 'converted_actor'
        importer = Importer()
        closure = dict(quest='quest', reachable_topics=['1'], unresolved=[])
        result = import_participants(closure, dict(topictorole=[dict(topic_id='1',role_id='1'),
            dict(topic_id='1',role_id='2'), dict(topic_id='2',role_id='3')]), Tables(), importer)
        self.assertEqual(result, {'source_actor':'converted_actor'})
        self.assertEqual(len(importer.requests), 1)
        self.assertEqual(importer.requests[0][2]['kind'], 'dialogue_participant')

    def test_silent_command_target_and_undeclared_speaker_are_imported(self):
        class Tables:
            def get(self, name):
                return dict(rows={'rpg/role': [dict(role_id=r, metarole_id='npc') for r in ('1','2','3')],
                    'rpg/metarole': [dict(metarole_id='npc', metarole_name='NPC')],
                    'rpg/soul2role': [dict(role_id=r, soul_id='actor_'+r) for r in ('1','2','3')]}[name])
        class Importer:
            def __init__(self): self.requests = []
            def ensure(self, group, identity, site):
                self.requests.append((identity, site)); return identity
        importer = Importer()
        tables = dict(topictorole=[], topic2sequence=[dict(topic_id='10', sequence_id='20')],
            sequence_line=[dict(sequence_id='20', sequence_line_id='30'),dict(sequence_id='99',sequence_line_id='90')],
            response=[dict(sequence_line_id='30',role_id='1'),dict(sequence_line_id='90',role_id='3')],
            v_dialogue_commands=[dict(sequence_line_id='30',who='1',target='2')])
        result = import_participants(dict(quest='quest',reachable_topics=['10'],unresolved=[]), tables, Tables(), importer)
        self.assertEqual(set(result), {'actor_1','actor_2'})
        self.assertEqual({s['dependency_kind'] for _,s in importer.requests},
                         {'response_speaker','command_who','command_target'})
        importer.requests.clear()
        closure = dict(quest='quest',reachable_topics=['10'],unresolved=[])
        result = import_participants(closure, tables, Tables(), importer, eligible_souls={'actor_2'})
        self.assertEqual(set(result), {'actor_2'})
        self.assertTrue(closure['unresolved'])
        self.assertTrue(all(identity == 'actor_2' for identity, _ in importer.requests))

    def test_named_predicates_sequence_dependencies_and_behavior_requests(self):
        tables = dict(topic=[dict(topic_id=str(i), label='bark' if i == 4 else '') for i in range(1, 6)],
                      sequence=[dict(sequence_id=str(i*10), next='0') for i in range(1, 6)],
                      topic2sequence=[dict(topic_id=str(i), sequence_id=str(i*10), entry_condition='') for i in range(1, 6)],
                      sequence2quest_objective=[], v_branch=[dict(start_topic=str(i)) for i in range(1, 6)],
                      topictorole=[], dialogue_functions=[dict(function_name='outer', expression='inner'),
                          dict(function_name='inner', expression="IsQuestStarted('quest') AND IsSeqAvailable(20)")])
        tables['topic2sequence'][0]['entry_condition'] = 'outer'
        tables['topic2sequence'][1]['entry_condition'] = 'IsSeqAvailable(10)'
        tables['topic2sequence'][2]['entry_condition'] = "var('outer') == 1"
        model = dict(behavior_documents={'a.xml': dict(trees={'job': dict(root=dict(op='SendMessageToNPC',
            attributes={'values': 'alias(bark)'}, children=[]))})})
        result = discover(tables, '42', 'quest', model)
        self.assertEqual([b['topic']['topic_id'] for b in result['branches']], ['1', '2', '4'])
        self.assertEqual(result['unresolved'], [])
        tables['topic2sequence'][1]['entry_condition'] = 'IsSeqAvailable(999)'
        self.assertEqual(discover(tables, '42', 'quest')['unresolved'][0]['referenced_sequence'], '999')

    def test_unnamed_root_is_found_through_nested_callback_and_cycles_terminate(self):
        tables = dict(topic=[dict(topic_id=i, label='') for i in ['1','2','3']],
                      sequence=[dict(sequence_id='10', next='2'), dict(sequence_id='20', next='1'),
                                dict(sequence_id='30', next='0')],
                      topic2sequence=[dict(topic_id=i, sequence_id=i+'0', entry_condition='') for i in ['1','2','3']],
                      sequence2quest_objective=[dict(quest_id='42', sequence_id='20', objective_id='9')],
                      v_branch=[dict(start_topic='1'),dict(start_topic='3')], topictorole=[])
        report = discover(tables, '42', 'arbitrary')
        self.assertEqual([b['topic']['topic_id'] for b in report['branches']], ['1'])
        self.assertEqual(report['references'][0]['topic_id'], '2')
        tables['sequence2quest_objective'] = []
        tables['topic2sequence'][2]['entry_condition'] = "IsQuestStarted('arbitrary')"
        self.assertEqual([b['topic']['topic_id'] for b in discover(tables,'42','arbitrary')['branches']], ['3'])
        self.assertEqual(discover(tables,'42','arbitrary_extra')['branches'], [])


if __name__ == '__main__': unittest.main()
