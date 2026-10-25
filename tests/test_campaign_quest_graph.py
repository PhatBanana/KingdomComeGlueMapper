import copy
from pathlib import Path
import sys
import unittest
import xml.etree.ElementTree as E

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from campaign_quest_graph import emit_project


def model():
    objectives = [dict(quest_id='42', objective_id=str(i), objective_name=n,
                       is_hidden=str(i == 3), is_exclusive='False', condition='',
                       autocomplete_timeout_str='', expiration_timeout_str='')
                  for i, n in ((3, 'intro'), (4, 'first'), (5, 'second'), (6, 'returnHome'), (7, 'disabled'))]
    nodes = {'1': dict(attributes={'Class': 'Quest:Begin'}), '2': dict(attributes={'Class': 'Quest:End'})}
    for o in objectives:
        nodes[o['objective_id']] = dict(attributes={'Class': 'Quest:Objective'}, payload=[dict(op='Inputs', attributes=dict(
            Name=o['objective_name'], IsHidden='1' if o['is_hidden'] == 'True' else '0', IsExclusive='0'))])
    transitions = [dict(quest_id='42', from_objective_id=a, to_objective_id=b, enabled=str(enabled))
                   for a, b, enabled in [('1', '3', True), ('3', '4', True), ('3', '5', True),
                                         ('4', '6', True), ('5', '6', True), ('3', '7', False), ('6', '2', True)]]
    edges = [dict(nodeOut=t['from_objective_id'], nodeIn=t['to_objective_id'], portOut='Out', portIn='In',
                  enabled='1' if t['enabled'] == 'True' else '0') for t in transitions]
    return dict(quest='arbitrary_quest', quest_id='42', graph=dict(nodes=nodes, edges=edges, unresolved_edges=[]),
                tables={'quest': dict(rows=[dict(quest_id='42', quest_name='arbitrary_quest', is_activated='False')]),
                        'quest_objective': dict(rows=objectives), 'quest_transition': dict(rows=transitions)})


class QuestGraphTests(unittest.TestCase):
    def test_stale_editor_names_and_flags_use_runtime_identity_with_evidence(self):
        m = model()
        rows = m['tables']['quest_objective']['rows']
        rows[0].update(objective_name='patchedIntro', is_hidden='False')
        rows[1]['is_exclusive'] = rows[2]['is_exclusive'] = 'True'
        m['tables']['quest_objective']['provenance'] = [{'sha256': 'runtime-patch'}]
        before = copy.deepcopy(m)
        files, report = emit_project([m], 'Example')
        root = E.fromstring(files['Example/arbitrary_quest.xml'])
        self.assertIsNotNone(root.find(".//Objective[@Name='patchedIntro']"))
        self.assertIsNotNone(root.find(".//Port[@Name='start_patchedIntro']"))
        self.assertIsNone(root.find(".//Port[@Name='start_intro']"))
        details = report['quests'][0]
        self.assertEqual(details['objective_table_differences']['name_mismatches'],
                         [dict(id='3', graph='intro', table='patchedIntro')])
        self.assertEqual(len(details['objective_table_differences']['flag_mismatches']), 3)
        self.assertEqual(len(details['exclusive_cancellations']), 2)
        self.assertEqual(details['objective_provenance'], [{'sha256': 'runtime-patch'}])
        self.assertEqual(m, before)

    def test_reconciliation_does_not_accept_invalid_flags_or_duplicate_identity(self):
        for update in (dict(is_hidden='Maybe'), dict(is_exclusive='2'), dict(objective_id='4')):
            with self.subTest(update=update):
                m = model()
                m['tables']['quest_objective']['rows'][0].update(update)
                with self.assertRaises(ValueError): emit_project([m], 'Example')

    def test_objective_callbacks_are_not_condition_aliases_or_silent_success(self):
        from campaign_quest_dependencies import objective_dependencies
        m = model()
        callback = dict(quest_id='42', objective_id='4', objective_function_id='1',
                        objective_function_type_id='2', function='SomeCallback()',
                        call_script='True', context_soul_id='')
        m['tables']['quest_function'] = dict(rows=[callback])
        m['tables']['quest_objective']['rows'][1]['condition'] = "IsObjectiveCompleted('arbitrary_quest','second')"
        m['tables']['quest_objective']['rows'][2]['condition'] = "IsQuestStarted('external') AND SomeCallback()"
        self.assertEqual([r['quest'] for r in objective_dependencies(m)], ['external'])
        files, report = emit_project([m], 'Example')
        details = report['quests'][0]
        self.assertIn('first', details['converted_conditions'])
        self.assertNotIn('second', details['converted_conditions'])
        unsupported = [r for r in details['unsupported'] if r['kind'] == 'objective_callbacks']
        self.assertEqual(unsupported[0]['rows'], [callback])
        self.assertIsNone(E.fromstring(files['Example/arbitrary_quest.xml']).find(".//Timer[@Name='source_condition_5']"))

    def test_source_end_completes_only_active_quest_after_its_predecessor(self):
        files, report = emit_project([model()], 'Example')
        root = E.fromstring(files['Example/arbitrary_quest.xml'])
        nodes = root.find('./Skald/Quest/Nodes')
        gate = nodes.find("If[@Name='advance_2']")
        self.assertIsNotNone(gate)
        self.assertEqual([e.get('From') for e in gate.findall("Edge[@To='Exec']")],
                         ['quest_end_2_queued.OnFinished'])
        timer = nodes.find("Timer[@Name='quest_end_2_queued']")
        self.assertEqual([e.get('From') for e in timer.findall("Edge[@To='SetRunning']")],
                         ['objective_6.OnCompleted'])
        condition = gate.find("Edge[@To='Condition']").get('From')
        conjunction = next(n for n in nodes if n.get('Name') == condition.split('.')[0])
        self.assertEqual({e.get('From') for e in conjunction.findall('Edge')},
                         {'objective_6.Completed', 'quest_progress.Active'})
        self.assertIsNotNone(nodes.find("State[@Name='quest_progress']/Edge[@From='advance_2.True'][@To='SetDone']"))
        self.assertEqual(report['quests'][0]['converted_quest_end']['join'], 'all')

    def test_begin_to_end_has_no_synchronous_state_feedback(self):
        m = model()
        m['tables']['quest_transition']['rows'] = [dict(
            quest_id='42', from_objective_id='1', to_objective_id='2', enabled='True')]
        files, _ = emit_project([m], 'Example')
        nodes = E.fromstring(files['Example/arbitrary_quest.xml']).find('./Skald/Quest/Nodes')
        # Follow execution edges until an asynchronous Timer boundary. No path
        # from OnActive may synchronously write back into quest_progress.
        pending, visited = ['quest_progress.OnActive'], set()
        while pending:
            event = pending.pop()
            if event in visited: continue
            visited.add(event)
            for node in nodes:
                for e in node.findall('Edge'):
                    if e.get('From') != event: continue
                    if node.tag == 'Timer': continue
                    self.assertNotEqual(node.get('Name'), 'quest_progress')
                    if node.tag == 'If' and e.get('To') == 'Exec':
                        pending.extend(node.get('Name') + '.' + v for v in ('True', 'False'))
        timer = nodes.find("Timer[@Name='quest_end_2_queued']")
        self.assertIsNotNone(timer.find("Edge[@From='quest_progress.OnActive'][@To='SetRunning']"))
        self.assertEqual({e.get('From') for e in timer.findall("Edge[@To='SetStopped']")},
                         {'quest_progress.OnDone', 'quest_progress.OnFailed', 'quest_progress.OnNone'})
        self.assertEqual(timer.find("Constant[@Name='Duration']").get('Value'), '0s')

    def test_disabled_source_end_does_not_complete_quest(self):
        m = model()
        for row in m['tables']['quest_transition']['rows']:
            if row['to_objective_id'] == '2': row['enabled'] = 'False'
        for edge in m['graph']['edges']:
            if edge['nodeIn'] == '2': edge['enabled'] = '0'
        files, report = emit_project([m], 'Example')
        self.assertIsNone(E.fromstring(files['Example/arbitrary_quest.xml']).find(".//If[@Name='advance_2']"))
        self.assertNotIn('converted_quest_end', report['quests'][0])

    def test_source_objective_predicate_rechecks_at_start_and_dependency_change(self):
        m = model()
        m['tables']['quest_objective']['rows'][1]['condition'] = "IsObjectiveCompleted('arbitrary_quest','second')"
        m['tables']['quest_tracked_asset'] = dict(rows=[dict(quest_id='42', objective_id='4', count='0')])
        files, report = emit_project([m], 'Example')
        root = E.fromstring(files['Example/arbitrary_quest.xml'])
        timer = root.find(".//Timer[@Name='source_condition_4']")
        self.assertEqual({e.get('From') for e in timer.findall('Edge')},
                         {'objective_4.OnStarted', 'objective_5.OnExec'})
        self.assertIn('first', report['quests'][0]['converted_conditions'])
        self.assertIsNotNone(root.find(".//State[@Name='objective_4']/Edge[@From='source_condition_4_apply_0_gate.True']"))
        m['tables']['quest_tracked_asset']['rows'][0]['count'] = '1'
        files, report = emit_project([m], 'Example')
        self.assertNotIn('first', report['quests'][0]['converted_conditions'])

    def test_exclusive_predecessors_advance_on_either_completion_and_cancel_sibling(self):
        m = model()
        for row in m['tables']['quest_objective']['rows']:
            if row['objective_id'] in ('4', '5'):
                row['is_exclusive'] = 'True'
                m['graph']['nodes'][row['objective_id']]['payload'][0]['attributes']['IsExclusive'] = '1'
        files, report = emit_project([m], 'Example')
        root = E.fromstring(files['Example/arbitrary_quest.xml'])
        nodes = {n.get('Name'): n for n in root.find('./Skald/Quest/Nodes')}
        def evaluate(port, state):
            if port in state: return state[port]
            node = nodes[port.split('.')[0]]
            inputs={e.get('To'): evaluate(e.get('From'),state) for e in node.findall('Edge')}
            if node.get('MethodName') == 'math::boolean::And': return inputs['A'] and inputs['B']
            if node.get('MethodName') == 'math::boolean::Or': return inputs['A'] or inputs['B']
            self.fail('Unexpected boolean expression')
        condition=nodes['advance_6'].find("Edge[@To='Condition']").get('From')
        for first,second,unchanged,canceled,expected in (
            (False,False,True,False,False), (True,False,True,False,True),
            (False,True,True,False,True), (True,False,False,True,True),
            (True,False,False,False,False)):
            self.assertEqual(evaluate(condition,{'objective_4.Completed':first,
                'objective_5.Completed':second,'objective_6.Unchanged':unchanged,
                'objective_6.Canceled':canceled}),expected)
        # Exclusive objectives themselves still start from their incoming edge.
        self.assertIn('advance_4',nodes)
        self.assertIn('advance_5',nodes)
        for winner,other in [('4','5'),('5','4')]:
            name='exclusive_cancel_'+winner+'_'+other
            self.assertEqual(nodes[name].find("Edge[@To='Exec']").get('From'),
                'objective_'+winner+'.OnCompleted')
            self.assertEqual(nodes['objective_'+other].find("Edge[@From='"+name+".True']").get('To'),'SetCanceled')
        self.assertEqual(len(report['quests'][0]['exclusive_cancellations']),2)

    def test_mixed_predecessor_policy_is_explicitly_unresolved(self):
        m=model()
        m['tables']['quest_objective']['rows'][1]['is_exclusive']='True'
        m['graph']['nodes']['4']['payload'][0]['attributes']['IsExclusive']='1'
        files,report=emit_project([m],'Example')
        self.assertIsNone(E.fromstring(files['Example/arbitrary_quest.xml']).find(".//If[@Name='advance_6']"))
        self.assertTrue(any(r['kind']=='mixed_exclusive_transition' for r in report['quests'][0]['unsupported']))

    def test_source_game_time_autocomplete_preserves_duration_and_cancel_gate(self):
        m = model()
        row = m['tables']['quest_objective']['rows'][0]
        row.update(condition='1', autocomplete_timeout_str='4m #GT')
        files, report = emit_project([m], 'Example')
        root = E.fromstring(files['Example/arbitrary_quest.xml'])
        timer = root.find(".//Timer[@Name='complete_3_queued']")
        self.assertEqual(timer.find("Constant[@Name='Duration']").get('Value'), '4m')
        self.assertEqual(timer.find("Constant[@Name='TimeType']").get('Value'), 'GameTime')
        self.assertEqual({e.get('From') for e in timer.findall("Edge[@To='SetStopped']")},
                         {'objective_3.OnCompleted', 'objective_3.OnFailed', 'objective_3.OnCanceled', 'objective_3.OnUnchanged'})
        self.assertFalse(any(r.get('objective') == 'intro' for r in report['quests'][0]['unsupported']))
        for duration, condition in [('4m #UNKNOWN', '1'), ('4m #GT', 'sourceDynamicCheck')]:
            row.update(autocomplete_timeout_str=duration, condition=condition)
            files, report = emit_project([m], 'Example')
            root = E.fromstring(files['Example/arbitrary_quest.xml'])
            self.assertIsNone(root.find(".//Timer[@Name='complete_3_queued']"))
            self.assertTrue(any(r.get('objective') == 'intro' for r in report['quests'][0]['unsupported']))

    def test_true_condition_does_not_bypass_tracked_item_requirements(self):
        m = model()
        m['tables']['quest_objective']['rows'][1]['condition'] = '1'
        tracking = dict(quest_id='42', objective_id='4', quest_asset_id='90', count='10')
        m['tables']['quest_tracked_asset'] = dict(rows=[tracking])
        files, report = emit_project([m], 'Example')
        q = E.fromstring(files['Example/arbitrary_quest.xml'])
        self.assertIsNone(q.find(".//Timer[@Name='complete_4_queued']"))
        pending = [r for r in report['quests'][0]['unsupported'] if r['kind'] == 'tracked_completion']
        self.assertEqual(pending, [dict(kind='tracked_completion', objective='first', assets=[tracking])])
        tracking['objective_id'] = '999'
        with self.assertRaisesRegex(ValueError, 'unknown quest objective'):
            emit_project([m], 'Example')

    def test_constant_true_objective_completes_on_start_but_timed_condition_does_not(self):
        m = model()
        m['tables']['quest_objective']['rows'][0]['condition'] = '1'
        files, report = emit_project([m], 'Example')
        root = E.fromstring(files['Example/arbitrary_quest.xml'])
        state = root.find(".//State[@Name='objective_3']")
        self.assertIsNone(state.find("Edge[@From='objective_3.OnStarted']"))
        timer = root.find(".//Timer[@Name='complete_3_queued']")
        self.assertEqual(timer.find("Constant[@Name='Duration']").get('Value'), '0s')
        self.assertEqual(timer.find('Edge').get('From'), 'objective_3.OnStarted')
        gate = root.find(".//If[@Name='complete_3_if_started']")
        self.assertEqual(gate.find("Edge[@To='Condition']").get('From'), 'objective_3.Started')
        self.assertEqual(state.find("Edge[@From='complete_3_if_started.True']").get('To'), 'SetCompleted')
        self.assertFalse(any(r.get('objective') == 'intro' for r in report['quests'][0]['unsupported']))
        m['tables']['quest_objective']['rows'][0]['time'] = '5'
        files, report = emit_project([m], 'Example')
        root = E.fromstring(files['Example/arbitrary_quest.xml'])
        self.assertIsNone(root.find(".//State[@Name='objective_3']/Edge[@From='objective_3.OnStarted']"))
        self.assertIsNone(root.find(".//Timer[@Name='complete_3_queued']"))
        self.assertTrue(any(r.get('objective') == 'intro' for r in report['quests'][0]['unsupported']))

    def test_hidden_objectives_remain_states_and_production_has_no_test_inputs(self):
        m = model(); before = copy.deepcopy(m)
        files, report = emit_project([m], 'Example')
        q = E.fromstring(files['Example/arbitrary_quest.xml'])
        self.assertIsNotNone(q.find(".//State[@Name='objective_3']"))
        self.assertIsNone(q.find(".//Objective[@Name='intro']"))
        self.assertEqual(len(q.findall('.//Objective')), 4)
        self.assertFalse(q.findall('.//HasteTrigger'))
        self.assertFalse(report['campaign_ready'])
        self.assertFalse(report['source_behavior_executed'])
        self.assertEqual(m, before)

    def test_transition_requires_every_predecessor_and_cannot_reopen_completed_destination(self):
        files, _ = emit_project([model()], 'Example')
        q = E.fromstring(files['Example/arbitrary_quest.xml'])
        gates = q.findall(".//If[@Name='advance_6']/Edge")
        self.assertEqual({e.get('From') for e in gates if e.get('To') == 'Exec'},
                         {'objective_4.OnCompleted', 'objective_5.OnCompleted'})
        terms = {e.get('From') for n in q.findall('.//Function') if n.get('Name').startswith('ready_6_') for e in n}
        self.assertTrue({'objective_4.Completed', 'objective_5.Completed', 'objective_6.Unchanged'} <= terms)
        self.assertIsNone(q.find(".//If[@Name='advance_7']"))

    def test_runtime_table_difference_is_reported_and_not_silently_dropped(self):
        m = model(); m['graph']['edges'].pop(1)
        _, report = emit_project([m], 'Example')
        self.assertEqual(report['quests'][0]['graph_transition_differences']['table_only'], [('3', '4', True)])
        m['graph']['unresolved_edges'] = [{'unknown': 'source edge'}]
        with self.assertRaisesRegex(ValueError, 'Unresolved'): emit_project([m], 'Example')

    def test_native_boolean_and_failed_log_contracts_and_explicit_diagnostic_start(self):
        files, _ = emit_project([model()], 'Example', 'arbitrary_quest', diagnostics=True)
        root = E.fromstring(files['Example.xml'])
        self.assertEqual(root.find(".//If[@Name='first_start']/Edge[@To='Condition']").get('From'), 'not_started.bool')
        q = E.fromstring(files['Example/arbitrary_quest.xml'])
        self.assertTrue(all(n.get('Type') == 'Canceled' for n in q.findall(".//EnumLog[@Name='Failed']")))
        self.assertTrue(any(n.get('Name') == 'fail_first' for n in q.findall('.//Port')))
        self.assertTrue(root.findall('.//GameStart'))
        with self.assertRaises(ValueError): emit_project([model()], 'Example', 'not_in_package')


if __name__ == '__main__': unittest.main()
