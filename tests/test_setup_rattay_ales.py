import copy
import os
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from campaign_quest_graph import emit_project
from quest_lab.runner import Runner
from quest_lab.source import Source
import setup_rattay_ales as ales

KCD1 = Path(os.environ.get('GLUEMAPPER_KCD1', 'D:/SteamLibrary/steamapps/common/KingdomComeDeliverance'))
KCD2 = Path(os.environ.get('GLUEMAPPER_KCD2', 'D:/SteamLibrary/steamapps/common/KingdomComeDeliverance2'))


def contract_model():
    """Synthetic quest with the same table shape as an NPC hand-in activity."""
    def objective(oid, name, hidden, condition=''):
        return dict(quest_id='7', objective_id=oid, objective_name=name, is_hidden=hidden,
                    is_exclusive='False', condition=condition, autocomplete_timeout_str='-1',
                    expiration_timeout_str='-1', time='0')
    objectives = [objective('4', 'refused', 'True'), objective('5', 'rabbit', 'False'),
                  objective('6', 'stag', 'False'), objective('9', 'finished', 'True', '1'),
                  objective('79', 'giver_dead', 'True', '1'), objective('129', 'saved', 'True', '1')]
    nodes = {'2': dict(attributes={'Class': 'Quest:Begin'}), '3': dict(attributes={'Class': 'Quest:End'})}
    for o in objectives:
        nodes[o['objective_id']] = dict(attributes={'Class': 'Quest:Objective'}, payload=[dict(op='Inputs',
            attributes=dict(Name=o['objective_name'], IsHidden='1' if o['is_hidden'] == 'True' else '0',
                            IsExclusive='0'))])
    transitions = [dict(quest_id='7', from_objective_id=a, to_objective_id=b, enabled='True')
                   for a, b in (('2', '79'), ('2', '129'), ('9', '3'), ('129', '5'))]
    tracked = [dict(quest_id='7', objective_id=o, quest_asset_id=a, count=c, map_asset_id='', on_map='False')
               for o, a, c in (('5', '14', '70'), ('6', '17', '40'), ('79', '26', '1'))]
    items = [dict(quest_id='7', quest_asset_id=a, item_id=i, item_category_id='5', min_health='0.5',
                  item_category_subtype_id='', item_category_type_id='')
             for a, i in (('14', '00000000-0000-0000-0000-000000000014'), ('17', '00000000-0000-0000-0000-000000000017'))]
    return dict(quest=ales.QUEST, quest_id='7', graph=dict(nodes=nodes, unresolved_edges=[],
        edges=[dict(nodeOut=t['from_objective_id'], nodeIn=t['to_objective_id'], portOut='Out', portIn='In',
                    enabled='1') for t in transitions]),
        tables={'quest': dict(rows=[dict(quest_id='7', quest_name=ales.QUEST, is_activated='False')]),
                'quest_objective': dict(rows=objectives), 'quest_transition': dict(rows=transitions),
                'quest_tracked_asset': dict(rows=tracked), 'quest_item': dict(rows=items),
                'quest_npc': dict(rows=[dict(quest_id='7', quest_asset_id='26', soul_id='S')])})


def dialogue(*sequences):
    return dict(start_topic='1', functions={}, topics={'1': dict(sequences=[
        dict(source=dict(sequence_id=sid, script=script), entry=dict(entry_condition=condition))
        for sid, script, condition in sequences])})


class SelectionTests(unittest.TestCase):
    def test_storm_role_is_read_by_exact_person_name(self):
        data = b'''<storm><rules><rule name="x"><selectors><hasName name="rat_refugee_ales"/></selectors>
            <operations><addRole name="GIVER"/></operations></rule><rule name="y"><selectors>
            <hasName name="rat_refugee_ales_2"/></selectors><operations><addRole name="OTHER"/></operations>
            </rule></rules></storm>'''
        self.assertEqual(ales.storm_roles(data, ales.PERSON), ['GIVER'])

    def test_lifecycle_sites_keep_gate_and_ignore_other_quests(self):
        found = ales.lifecycle_sites([dialogue(
            ('10', "QuestSystem.ActivateQuest('a_huntsman_alex')", "IsQuestCompleted('q_other')"),
            ('11', "QuestSystem.StartQuest('q_other')", ''),
            ('12', "QuestSystem.StartQuest('a_huntsman_alex')", ''))])
        self.assertEqual([(s['sequence'], s['function'], s['entry_condition']) for s in found],
                         [('10', 'ActivateQuest', "IsQuestCompleted('q_other')"), ('12', 'StartQuest', '')])
        self.assertEqual(ales.external_quests([dialogue(('10', '', "IsQuestCompleted('q_other')"))]),
                         {'q_other': ['10']})

    def test_selection_must_match_source_closure_npc_and_role(self):
        closure = dict(branches=[dict(source=dict(skald_element_id=e, start_topic=t)) for e, t in ales.BRANCHES])
        ales.check_selection(closure, 'AB', ['ab'], ['GIVER'], {'GIVER', 'HENRY'})
        with self.assertRaisesRegex(ValueError, 'closure differs'):
            ales.check_selection(dict(branches=closure['branches'][:1]), 'AB', ['ab'], ['GIVER'], {'GIVER'})
        with self.assertRaisesRegex(ValueError, 'not the selected person'):
            ales.check_selection(closure, 'AB', ['cd'], ['GIVER'], {'GIVER'})
        with self.assertRaisesRegex(ValueError, 'Storm role'):
            ales.check_selection(closure, 'AB', ['ab'], ['OTHER'], {'GIVER'})

    def test_blockers_are_listed_once_and_prevent_installation(self):
        report = dict(dialogues=[dict(topic='1', emitted=False, failure='no')],
            lifecycle=[dict(sequence='5', function='OpenInventory')] * 2 + [dict(sequence='5', function='IsObjectiveStarted')],
            quest_graph_unsupported=[dict(kind='rewards', table='quest_reward_money')],
            tracked_items=dict(pending=[dict(objective='rabbit', reasons=['a', 'b'])]))
        found = ales.blockers(report)
        self.assertEqual([b['kind'] for b in found], ['dialogue', 'exit_script', 'quest_graph', 'tracked_items'])
        with self.assertRaisesRegex(ValueError, 'not installable'):
            ales.require_ready(dict(report, blockers=found))
        self.assertEqual(ales.require_ready(dict(blockers=[]))['blockers'], [])


class LabScenarioTests(unittest.TestCase):
    def run_all(self, model):
        files, _ = emit_project([model], 'Lab')
        runs, unsupported = ales.lab_scenarios(model)
        return [Runner(s, source=Source.blobs(files)).run() for s in runs], unsupported

    def test_expectations_come_from_source_tables(self):
        facts = ales.source_expectations(contract_model())
        self.assertEqual(facts['goods'], ['rabbit', 'stag'])
        self.assertEqual(facts['refusal'], 'refused')
        self.assertEqual(facts['accepted'], {'giver_dead': 'Started', 'saved': 'Completed', 'rabbit': 'Started'})

    def test_emitted_contract_graph_passes_every_supported_scenario(self):
        results, unsupported = self.run_all(contract_model())
        self.assertEqual(len(results), 5)
        for r in results:
            with self.subTest(r['name']):
                self.assertEqual(r['status'], 'PASS', r['error'])
                self.assertFalse(r['native_runtime_verified'])
        names = ' | '.join(u['name'] for u in unsupported)
        for needed in ('below/at/above', 'one money payout', 'after payout', 'min_health', 'Early talk'):
            self.assertIn(needed, names)

    def test_scenarios_detect_a_wrong_start_chain(self):
        model = contract_model()
        files, _ = emit_project([model], 'Lab')
        broken = copy.deepcopy(model)
        # Expectations from a graph where the save objective does not lead to the first hunt.
        broken['tables']['quest_transition']['rows'] = [r for r in broken['tables']['quest_transition']['rows']
                                                       if r['from_objective_id'] != '129']
        facts = ales.source_expectations(broken)
        self.assertNotIn('rabbit', facts['accepted'])
        accept = ales.lab_scenarios(model)[0][1]
        accept = copy.deepcopy(accept)
        accept['steps'][-1]['values']['output.rabbit_Started'] = False
        self.assertEqual(Runner(accept, source=Source.blobs(files)).run()['status'], 'FAIL')


@unittest.skipUnless((KCD1 / 'Data/Tables.pak').exists(), 'requires installed KCD1 source data')
class SourcePreflightTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.report = ales.preflight(KCD1, KCD2 if (KCD2 / 'Data/Scripts.pak').exists() else None)

    def test_source_selection_is_confirmed_and_not_installable(self):
        r = self.report
        self.assertEqual(r['storm_roles'], ['ALES_VUDCE_SKALICKYCH'])
        sites = {(s['function'], s['sequence']) for s in r['lifecycle']}
        self.assertLessEqual({('ActivateQuest', '56751'), ('StartQuest', '56903')}, sites)
        self.assertEqual(r['external_quests'], {'q_huntPtacek': ['56751']})
        self.assertEqual([d['emitted'] for d in r['dialogues']], [False, False])
        kinds = {b['kind'] for b in r['blockers']}
        self.assertEqual(kinds, {'dialogue', 'exit_script', 'quest_graph', 'tracked_items'})
        with self.assertRaises(ValueError):
            ales.require_ready(r)


if __name__ == '__main__':
    unittest.main()
