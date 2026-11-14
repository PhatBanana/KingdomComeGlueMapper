import contextlib
import copy
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock
import xml.etree.ElementTree as E
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from campaign_quest_graph import emit_project
from quest_lab.runner import Runner
from quest_lab.source import Source
import setup_kcd1_quests as quests

KCD1 = Path(os.environ.get('GLUEMAPPER_KCD1', 'D:/SteamLibrary/steamapps/common/KingdomComeDeliverance'))
KCD2 = Path(os.environ.get('GLUEMAPPER_KCD2', 'D:/SteamLibrary/steamapps/common/KingdomComeDeliverance2'))
QUEST = 'a_huntsman_alex'
ROW = quests.QUESTS[0]
BUTCHER = 'a_huntsman_butcher'
BUTCHER_ROW = quests.QUESTS[1]
# A built package that has the shop imports: two of the butcher's item classes exist only there.
PACKAGE = Path(os.environ.get('GLUEMAPPER_KCD1_QUEST_PACKAGE', 'D:/KCD/Builds/glue/jobs-unified-cold-20261102/'
                              '20261111-170855-7144498-unified-11-shops2/package/map'))


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
    return dict(quest=QUEST, quest_id='7', graph=dict(nodes=nodes, unresolved_edges=[],
        edges=[dict(nodeOut=t['from_objective_id'], nodeIn=t['to_objective_id'], portOut='Out', portIn='In',
                    enabled='1') for t in transitions]),
        tables={'quest': dict(rows=[dict(quest_id='7', quest_name=QUEST, is_activated='False')]),
                'quest_objective': dict(rows=objectives), 'quest_transition': dict(rows=transitions),
                'quest_tracked_asset': dict(rows=tracked), 'quest_item': dict(rows=items),
                'quest_npc': dict(rows=[dict(quest_id='7', quest_asset_id='26', soul_id='S')])})


class SelectionTests(unittest.TestCase):
    def test_selection_row_is_complete_and_pinned(self):
        self.assertEqual(ROW['quest'], QUEST)
        self.assertEqual(ROW['people'], ('rat_refugee_ales',))
        self.assertEqual(ROW['prerequisites'], {'q_huntPtacek': 'completed'})
        self.assertEqual(len(ROW['accepted_pending']), 15)
        self.assertEqual({p.rsplit(':', 1)[1] for p in ROW['accepted_pending']},
                         {'rat_hanus', 'rat_berthold', 'rat_bailiff'})
        self.assertEqual(quests.row_for(QUEST), ROW)
        with self.assertRaises(ValueError):
            quests.row_for('q_other')
        self.assertEqual(quests.selection_digest(ROW), quests.selection_digest(dict(ROW)))
        self.assertNotEqual(quests.selection_digest(ROW), quests.selection_digest(dict(ROW, namespace='other')))

    def test_the_second_quest_is_pinned_and_needs_a_package_to_plan(self):
        self.assertEqual([r['quest'] for r in quests.QUESTS], [QUEST, BUTCHER])
        row = BUTCHER_ROW
        self.assertEqual((row['people'], row['prerequisites'], row['lab_order']),
                         (('sas_butcher',), {'q_returnToSkalitz': 'completed'}, ('boar', 'offal')))
        self.assertEqual(row['branches'], (('38322', '27388'), ('38324', '27396')))
        self.assertEqual(row['accepted_pending'], tuple(sorted(
            'quest_reward_reputation:' + o + ':' + target
            for o in ('boarMoney', 'endOfFun', 'kidneyMoney', 'liverMoney', 'offalMoney')
            for target in ('faction_81', 'sas_bailiff'))))
        self.assertEqual(len(row['accepted_pending']), 10)
        self.assertTrue(row['needs_package'])
        self.assertNotIn('needs_package', ROW)
        self.assertEqual(len({r['namespace'] for r in quests.QUESTS}), 2)
        # How a quest is planned is not part of what was ported.
        self.assertEqual(quests.selection_digest(row), quests.selection_digest(dict(row, needs_package=False)))

    def test_plan_without_a_package_skips_a_quest_that_needs_one(self):
        with mock.patch.object(quests, 'plan_quest', side_effect=lambda row, *a, **k: ({}, dict(quest=row['quest']))) as planned:
            report = quests.plan('kcd1', 'kcd2')
            self.assertEqual(list(report['quests']), [QUEST])
            self.assertEqual(list(report['skipped']), [BUTCHER])
            self.assertIsNone(planned.call_args.kwargs['base'])
        chain = []
        def fake(row, source, target, package, base=None):
            chain.append(base)
            return dict(base or {}, **{row['quest']: b'x'}), dict(quest=row['quest'])
        with mock.patch.object(quests, 'plan_quest', side_effect=fake):
            report = quests.plan('kcd1', 'kcd2', 'package')
        self.assertEqual(list(report['quests']), [QUEST, BUTCHER])
        self.assertNotIn('skipped', report)
        # Each quest is planned on what the one before it left, as the stage ports them.
        self.assertEqual(chain, [None, {QUEST: b'x'}])

    def test_storm_role_is_read_by_exact_person_name(self):
        data = b'''<storm><rules><rule name="x"><selectors><hasName name="rat_refugee_ales"/></selectors>
            <operations><addRole name="GIVER"/></operations></rule><rule name="y"><selectors>
            <hasName name="rat_refugee_ales_2"/></selectors><operations><addRole name="OTHER"/></operations>
            </rule></rules></storm>'''
        self.assertEqual(quests.storm_roles(data, 'rat_refugee_ales'), ['GIVER'])

    def test_selection_must_match_source_closure_npc_and_role(self):
        closure = dict(branches=[dict(source=dict(skald_element_id=e, start_topic=t)) for e, t in ROW['branches']])
        quests.check_selection(closure, 'AB', ['ab'], ['GIVER'], {'GIVER', 'HENRY'})
        with self.assertRaisesRegex(ValueError, 'closure differs'):
            quests.check_selection(dict(branches=closure['branches'][:1]), 'AB', ['ab'], ['GIVER'], {'GIVER'})
        with self.assertRaisesRegex(ValueError, 'not the selected person'):
            quests.check_selection(closure, 'AB', ['cd'], ['GIVER'], {'GIVER'})
        with self.assertRaisesRegex(ValueError, 'Storm role'):
            quests.check_selection(closure, 'AB', ['ab'], ['OTHER'], {'GIVER'})


class PendingPolicyTests(unittest.TestCase):
    def report(self, rows=(), tracking=(), policy=(), unsupported=()):
        return dict(lowerings=dict(rewards=dict(pending=list(rows)), tracking=dict(pending=list(tracking)),
                                   policy=dict(pending=list(policy))), unsupported=list(unsupported))

    def model(self):
        return dict(tables=dict(quest_objective=dict(rows=[dict(objective_id='5', objective_name='hare')])))

    def test_every_pending_record_has_a_stable_name(self):
        row = dict(objective_id='5', soul_id='ABC', faction_id='')
        faction = dict(objective_id='5', soul_id='', faction_id='9')
        found = quests.pending_set(self.report(
            rows=[dict(table='quest_reward_reputation', row=row), dict(table='quest_reward_reputation', row=faction)],
            tracking=[dict(objective='hare')], policy=[dict(objective='hare')],
            unsupported=[dict(kind='rewards', table='quest_reward_reputation'),
                         dict(kind='tracked_completion', objective='boar')]), self.model(), {'abc': 'rat_hanus'})
        self.assertEqual(found, {'quest_reward_reputation:hare:rat_hanus', 'quest_reward_reputation:hare:faction_9',
                                 'tracking:hare', 'policy:hare', 'unsupported:tracked_completion:boar'})

    def test_only_the_accepted_pending_set_passes(self):
        quests.check_pending({'a', 'b'}, ('a', 'b'))
        with self.assertRaisesRegex(ValueError, 'unexpected: c'):
            quests.check_pending({'a', 'b', 'c'}, ('a', 'b'))
        with self.assertRaisesRegex(ValueError, 'no longer pending: b'):
            quests.check_pending({'a'}, ('a', 'b'))

    def test_tracked_predicate_is_removed_again(self):
        from campaign_dialogue_conditions import OBJECTIVE
        self.assertNotIn('IsObjectiveTrackedCompleted', OBJECTIVE)
        with quests.tracked_predicate():
            self.assertIn('IsObjectiveTrackedCompleted', OBJECTIVE)
        self.assertNotIn('IsObjectiveTrackedCompleted', OBJECTIVE)
        with self.assertRaises(RuntimeError), quests.tracked_predicate():
            raise RuntimeError('stage failed')
        self.assertNotIn('IsObjectiveTrackedCompleted', OBJECTIVE)

    def test_only_referenced_souls_and_factions_are_bound(self):
        model = dict(tables={'quest_npc': dict(rows=[dict(soul_id='AA')]),
                             'quest_reward_reputation': dict(rows=[dict(soul_id='', faction_id='7')])})
        self.assertEqual(quests.referenced_souls(model), {'aa'})
        registered = dict(souls={'aa': 'giver', 'bb': 'other'})
        with mock.patch('quest_lowering_report.build_bindings', return_value=dict(registered=dict(faction=[]))):
            bound = quests.bindings_for(model, (registered, {}), {'AA', 'BB'}, {'7': 'f7', '8': 'f8'})
        self.assertEqual(bound['soul_assets'], {'aa': 'gm_soul_giver'})
        self.assertEqual(bound['factions'], {'7': 'f7'})
        self.assertEqual(bound['registered']['faction'], ['f7'])


class LabScenarioTests(unittest.TestCase):
    def run_all(self, model, order=None):
        files, _ = emit_project([model], 'Lab')
        runs, unsupported = quests.lab_scenarios(model, order=order)
        return [Runner(s, source=Source.blobs(files)).run() for s in runs], unsupported

    def test_expectations_come_from_source_tables(self):
        facts = quests.source_expectations(contract_model())
        self.assertEqual(facts['goods'], ['rabbit', 'stag'])
        self.assertEqual(facts['refusal'], 'refused')
        self.assertEqual(facts['accepted'], {'giver_dead': 'Started', 'saved': 'Completed', 'rabbit': 'Started'})

    def test_emitted_contract_graph_passes_every_supported_scenario(self):
        results, unsupported = self.run_all(contract_model())
        self.assertEqual(len(results), 7)
        for r in results:
            with self.subTest(r['name']):
                self.assertEqual(r['status'], 'PASS', r['error'])
                self.assertFalse(r['native_runtime_verified'])
        names = ' | '.join(u['name'] for u in unsupported)
        for needed in ('below/at/above', 'one money payout', 'after payout', 'min_health', 'Early talk', 'giver'):
            self.assertIn(needed, names)

    def test_a_completion_starts_what_the_source_graph_chains_to_it(self):
        model = contract_model()
        rows = model['tables']['quest_objective']['rows']
        paid = dict(rows[0], objective_id='346', objective_name='rabbitPaid')
        both = dict(rows[0], objective_id='12', objective_name='bothDone', condition='1')
        rows.extend((paid, both))
        for name, hidden in (('rabbitPaid', '1'), ('bothDone', '1')):
            oid = '346' if name == 'rabbitPaid' else '12'
            model['graph']['nodes'][oid] = dict(attributes={'Class': 'Quest:Objective'}, payload=[dict(op='Inputs',
                attributes=dict(Name=name, IsHidden=hidden, IsExclusive='0'))])
        for a, b in (('5', '346'), ('5', '12'), ('6', '12')):
            model['tables']['quest_transition']['rows'].append(dict(quest_id='7', from_objective_id=a, to_objective_id=b,
                                                                    enabled='True'))
            model['graph']['edges'].append(dict(nodeOut=a, nodeIn=b, portOut='Out', portIn='In', enabled='1'))
        facts = quests.source_expectations(model)
        self.assertEqual(facts['joins']['rabbitPaid'], ['rabbit'])
        self.assertEqual(facts['joins']['bothDone'], ['rabbit', 'stag'])
        self.assertIn('bothDone', facts['automatic'])
        start = {n: 'Unchanged' for n in facts['objectives']}
        after = quests.after_completion(facts, start, 'rabbit')
        self.assertEqual((after['rabbit'], after['rabbitPaid'], after['bothDone']), ('Completed', 'Started', 'Unchanged'))
        both_done = quests.after_completion(facts, after, 'stag')
        self.assertEqual(both_done['bothDone'], 'Completed')
        results, _ = self.run_all(model)
        self.assertEqual([r['status'] for r in results], ['PASS'] * 7, [r['error'] for r in results])
        # Without the chained expectation the exhaustive assertion would call the payment objective untouched.
        runs, _ = quests.lab_scenarios(model)
        self.assertTrue(runs[4]['steps'][4]['values']['output.rabbitPaid_Started'])

    def test_the_unsupported_list_names_the_quests_own_prerequisite(self):
        _, unsupported = quests.lab_scenarios(contract_model(), prerequisites={'q_returnToSkalitz': 'completed'})
        self.assertEqual(unsupported[0]['name'], 'Early talk before q_returnToSkalitz is a no-op')
        self.assertEqual(quests.lab_scenarios(contract_model())[1][0]['name'], 'Early talk before q_huntPtacek is a no-op')

    def test_the_explicit_order_names_the_next_hunt(self):
        runs, _ = quests.lab_scenarios(contract_model(), order=('rabbit', 'stag'))
        self.assertEqual(runs[-1]['steps'][-2]['port'], 'start_stag')
        with self.assertRaisesRegex(ValueError, 'Lab order'):
            quests.lab_scenarios(contract_model(), order=('stag', 'rabbit'))

    def test_scenarios_detect_a_wrong_start_chain(self):
        model = contract_model()
        files, _ = emit_project([model], 'Lab')
        broken = copy.deepcopy(model)
        # Expectations from a graph where the save objective does not lead to the first hunt.
        broken['tables']['quest_transition']['rows'] = [r for r in broken['tables']['quest_transition']['rows']
                                                       if r['from_objective_id'] != '129']
        facts = quests.source_expectations(broken)
        self.assertNotIn('rabbit', facts['accepted'])
        accept = copy.deepcopy(quests.lab_scenarios(model)[0][1])
        accept['steps'][-1]['values']['output.rabbit_Started'] = False
        self.assertEqual(Runner(accept, source=Source.blobs(files)).run()['status'], 'FAIL')

    def test_write_lab_writes_graph_scenarios_and_the_unsupported_list(self):
        with tempfile.TemporaryDirectory() as temporary:
            target = Path(temporary) / 'lab'
            paths = quests.write_lab(contract_model(), target, order=('rabbit', 'stag'))
            self.assertEqual([p.name for p in paths], ['%02d-scenario.json' % i for i in range(1, 8)])
            self.assertTrue(any((target / 'graph').rglob('*.xml')))
            self.assertTrue((target / 'unsupported.json').is_file())
            with self.assertRaises(FileExistsError):
                quests.write_lab(contract_model(), target)


# ---------------------------------------------------------------- audit helpers

DEFINITIONS = b'''<Definitions><Nodes>
<Definition TypeName="If" Name="If"><Ports>
  <CompileTimePort Name="Exec" Direction="In" Type="trigger"/><CompileTimePort Name="Condition" Direction="In" Type="bool"/>
  <CompileTimePort Name="True" Direction="Out" Type="trigger"/><CompileTimePort Name="False" Direction="Out" Type="trigger"/>
</Ports></Definition>
<Definition TypeName="Function" Name="Not"><Properties><Property Name="MethodName" Value="math::boolean::Not"/>
  <Property Name="DeclaringType" Value="math::boolean"/></Properties><Ports>
  <RunTimePort Name="Value" Direction="In" Type="bool"/><RunTimePort Name="bool" Direction="Out" Type="bool"/>
</Ports></Definition>
<Definition TypeName="ObjectProperties" Name="I_SoulProperties"><Properties>
  <Property Name="DeclaringType" Value="wh::rpgmodule::I_Soul"/></Properties><Ports>
  <RunTimePort Name="I_Soul" Direction="In" Type="soul"/><RunTimePort Name="Inventory" Direction="Out" Type="inv"/>
</Ports></Definition>
<Definition TypeName="Output" Name="Output"><Ports/></Definition>
<Definition TypeName="State" Name="State"><Ports><CompileTimePort Name="State" Direction="Out" Type=""/></Ports></Definition>
</Nodes></Definitions>'''


def definition(kind, name, ports=(), nodes=()):
    root = E.Element('Database')
    host = E.SubElement(E.SubElement(root, 'Skald'), kind, Name=name)
    declared = E.SubElement(host, 'Ports')
    for port, direction in ports:
        E.SubElement(declared, 'Port', Name=port, Direction=direction, Type='bool')
    owner = E.SubElement(host, 'Nodes')
    for node in nodes:
        owner.append(node)
    return E.tostring(root)


def node(tag, name, *children, **attributes):
    element = E.Element(tag, Name=name, **attributes)
    for child in children:
        element.append(child)
    return element


def edge(source, target):
    return E.Element('Edge', {'From': source, 'To': target})


def constant(name, value):
    return E.Element('Constant', Name=name, Value=value)


class GraphAuditTests(unittest.TestCase):
    def setUp(self):
        self.definitions = quests.Definitions(DEFINITIONS)

    def audit(self, nodes, owned=('q',), ports=(('go', 'In'), ('done', 'Out'))):
        resources = {quests.ENTRY: definition('Level', 'kcd1_travel'), quests.PROJECT: definition('Project', 'p'),
                     'Quests/q.xml': definition('Module', 'q', ports, nodes)}
        return quests.graph_audit(resources, ['Quests/q.xml'], set(owned), self.definitions, {'player'})

    def test_a_wired_definition_has_no_problems(self):
        result = self.audit([
            node('If', 'gate', edge('go', 'Exec'), edge('flag.State', 'Condition')),
            node('State', 'flag'),
            node('Output', 'out', edge('gate.True', 'done')),
            node('Function', 'inverse', edge('flag.State', 'Value'), MethodName='math::boolean::Not',
                 DeclaringType='math::boolean')])
        self.assertEqual(result['problems'], [])
        self.assertEqual((result['nodes'], result['edges']), (4, 4))
        self.assertEqual(result['unchecked'], 1)

    def test_unknown_tags_methods_ports_and_aliases_are_reported(self):
        result = self.audit([
            node('Mystery', 'a'),
            node('Function', 'b', MethodName='math::boolean::Xor', DeclaringType='math::boolean'),
            node('If', 'c', edge('go', 'Exec'), edge('missing.True', 'Condition'), edge('d.True', 'Nowhere'),
                 edge('c.Exec', 'False'), edge('gone', 'Exec'), constant('Unknown', '1')),
            node('If', 'd'),
            node('ObjectProperties', 'e', E.Element('Asset', Name='I_Soul', Alias='stranger'),
                 DeclaringType='wh::rpgmodule::I_Soul'),
            node('Output', 'out', edge('c.True', 'go'))])
        text = '\n'.join(result['problems'])
        for needed in ('node Mystery', 'math::boolean::Xor', 'missing.True, which is not a node',
                       'edge to Nowhere', 'c.Exec, which', 'edge from gone', 'constant Unknown',
                       'alias stranger', 'edge to go is not a declared Out port'):
            self.assertIn(needed, text)

    def test_the_level_entry_is_audited_only_where_the_stage_wrote(self):
        entry = definition('Level', 'kcd1_travel', (), [
            node('Mystery', 'old_legacy_node'),
            node('Mystery', 'lowered_delivery_x', edge('q.done', 'Nowhere'))])
        resources = {quests.ENTRY: entry, quests.PROJECT: definition('Project', 'p'),
                     'Quests/q.xml': definition('Module', 'q', (('done', 'Out'),))}
        result = quests.graph_audit(resources, [quests.ENTRY], {'lowered_delivery_x'}, self.definitions, set())
        self.assertEqual(result['nodes'], 1)
        self.assertEqual(len(result['problems']), 2)
        self.assertTrue(all('lowered_delivery_x' in p for p in result['problems']))

    def test_dialogue_scripts_and_references_are_audited(self):
        good = b'''<Database><Skald><FaderDialog Name="d"><Ports><Port Name="active" Direction="In" Type="bool"/>
            <Port Name="go" Direction="Out" Type="trigger"/></Ports><Dialogue><Decision Name="t"><Sequences>
            <Sequence Name="s" EntryCondition="Port('active')"><Triggers><Port Name="go"/></Triggers></Sequence>
            </Sequences></Decision></Dialogue></FaderDialog></Skald></Database>'''
        self.assertEqual(quests.dialogue_audit(good, 'd'), [])
        bad = good.replace(b'<Sequence Name="s" EntryCondition="Port(\'active\')">',
                           b'<Sequence Name="s" EntryCondition="Port(\'other\')" ExitScript="QuestSystem.StartQuest(\'q\')">') \
                  .replace(b'<Port Name="go"/>', b'<Port Name="active"/>')
        text = '\n'.join(quests.dialogue_audit(bad, 'd'))
        for needed in ('QuestSystem call', 'fires active', 'reads other'):
            self.assertIn(needed, text)


def tracking_model(amount='70', health='0.5', item=None):
    item = item or '6f1d0e9e-d532-4476-af7a-e24ea01da040'
    return dict(tables=dict(
        quest_objective=dict(rows=[dict(objective_id='5', objective_name='hare')]),
        quest_item=dict(rows=[dict(quest_asset_id='14', item_id=item.upper(), min_health=health)]),
        quest_tracked_asset=dict(rows=[dict(objective_id='5', quest_asset_id='14', count=amount, map_asset_id='')])))


def tracking_quest(amount='70', health='0.5', item='6f1d0e9e-d532-4476-af7a-e24ea01da040'):
    descriptor = node('Function', 'lowered_track_5_0_descriptor', constant('ItemClass', item), constant('Amount', amount),
                      *([constant('MinimumHealth', health)] if health else []))
    return definition('Quest', 'q', nodes=[descriptor])


class TrackingAndRewardAuditTests(unittest.TestCase):
    ITEM = '6f1d0e9e-d532-4476-af7a-e24ea01da040'

    def test_descriptors_equal_the_source_rows(self):
        rows, problems = quests.tracking_audit(tracking_quest(), tracking_model(), {self.ITEM: 'Hare meat'})
        self.assertEqual(problems, [])
        self.assertEqual(rows[0]['descriptors'], [(self.ITEM, 70, 0.5)])
        self.assertEqual(rows[0]['names'], ['Hare meat'])

    def test_a_changed_count_health_or_item_is_reported(self):
        _, problems = quests.tracking_audit(tracking_quest(amount='7'), tracking_model(), {self.ITEM: 'Hare meat'})
        self.assertIn('differ from KCD1 rows', problems[0])
        _, problems = quests.tracking_audit(tracking_quest(health='0.9'), tracking_model(), {self.ITEM: 'x'})
        self.assertIn('differ from KCD1 rows', problems[0])
        _, problems = quests.tracking_audit(tracking_quest(), tracking_model(), {})
        self.assertIn('has no item row', problems[0])
        _, problems = quests.tracking_audit(tracking_quest(), tracking_model(), {self.ITEM: None})
        self.assertIn('no English name', problems[0])

    def test_a_zero_health_row_has_no_minimum_constant(self):
        _, problems = quests.tracking_audit(tracking_quest(health=''), tracking_model(health=''), {self.ITEM: 'Hare meat'})
        self.assertEqual(problems, [])

    def rewards(self, *elements):
        rewards = E.Element('Rewards')
        for tag, attributes in elements:
            E.SubElement(rewards, tag, attributes)
        return definition('Quest', 'q', nodes=[node('AddReward', 'r', rewards)])

    def test_rewards_resolve_and_kcd1_rows_carry_kcd1_numbers(self):
        tables = dict(money_change={'kcd1_2-minor': dict(change='40')},
                      reputation_change={'kcd1_quest_reward_4_normal': dict(change='0.5')},
                      factions={'gluemapper_kcd1_faction_31'})
        amounts = dict(money={'2-minor': '40'}, reputation={'quest_reward_4_normal': '0.5'})
        blob = self.rewards(('MoneyReward', dict(Amount='kcd1_2-minor')),
            ('SoulReputationReward', dict(ReputationChange='kcd1_quest_reward_4_normal', Target='gm_soul_giver')),
            ('FactionReputationReward', dict(ReputationChange='kcd1_quest_reward_4_normal',
                                             Target='gluemapper_kcd1_faction_31')))
        used, problems = quests.reward_audit(blob, tables, {'gm_soul_giver'}, amounts)
        self.assertEqual(problems, [])
        self.assertEqual(len(used), 3)
        _, problems = quests.reward_audit(blob, dict(tables, money_change={'kcd1_2-minor': dict(change='41')}),
                                          {'gm_soul_giver'}, amounts)
        self.assertIn('changes by 41, KCD1 2-minor by 40', problems[0])

    def test_unresolved_rewards_are_reported(self):
        tables = dict(money_change={}, reputation_change={}, factions=set())
        blob = self.rewards(('MoneyReward', dict(Amount='kcd1_2-minor')),
            ('SoulReputationReward', dict(ReputationChange='nope', Target='nobody')),
            ('FactionReputationReward', dict(ReputationChange='nope', Target='nobody')), ('ItemReward', {}))
        _, problems = quests.reward_audit(blob, tables, set(), dict(money={}, reputation={}))
        text = '\n'.join(problems)
        for needed in ('no money_change row', 'no reputation_change row', 'not a declared soul asset',
                       'not in any FactionTree', 'unexpected reward element ItemReward'):
            self.assertIn(needed, text)


class JournalAndMediaAuditTests(unittest.TestCase):
    def test_journal_strings_and_markers(self):
        quest = definition('Quest', 'q')
        root = E.fromstring(quest)
        host = root.find('Skald/Quest')
        E.SubElement(host, 'QuestName', StringName='gmq_a', Text='x')
        log = E.SubElement(E.SubElement(host, 'Logs'), 'EnumLog', Marker='gm_soul_giver')
        E.SubElement(log, 'Log', StringName='gmq_b')
        project = definition('Project', 'p')
        count, problems = quests.journal_audit(E.tostring(root), project, {'gmq_a': 'x'})
        self.assertEqual(count, 2)
        self.assertEqual(len(problems), 2)
        self.assertIn('gmq_b', problems[0])
        self.assertIn('gm_soul_giver', problems[1])

    def test_dialogue_lines_need_text_recording_dubbing_facial_and_voice(self):
        from zlib import crc32
        blob = b'''<Database><Skald><FaderDialog Name="Dlg"><Dialogue><SelectedSouls>
            <SelectedSoul Role="A" Voice="jdor"/><SelectedSoul Role="B" Voice="nope"/></SelectedSouls>
            <Response Role="A"><Text StringName="k1"/></Response></Dialogue></FaderDialog></Skald></Database>'''
        stem = 'jdor_k1'
        recordings = {'dlg': {stem: 'dialog/kcd1_travel/dlg/' + stem + '.ogg'}}
        facials = {'animations/humans/facials/dialog/kcd1_travel/dlg/jdor_k1.caf'}
        lines, problems = quests.dialogue_media_audit(blob, 'Dlg', {'k1': 'hi'}, recordings,
                                                      {str(crc32(stem.encode()))}, facials, {'jdor'})
        self.assertEqual(lines, 1)
        self.assertEqual(problems, ['Dlg: voice nope does not resolve'])
        _, problems = quests.dialogue_media_audit(blob, 'Dlg', {}, {}, set(), set(), {'jdor', 'nope'})
        self.assertEqual(len(problems), 2)
        _, problems = quests.dialogue_media_audit(blob, 'Dlg', {'k1': 'hi'}, recordings, set(), set(), {'jdor', 'nope'})
        self.assertEqual(sorted(p.split(': ')[1].split(' for')[0] for p in problems), ['no dubbing row', 'no facial track'])

    def test_npc_needs_entity_soul_scheduler_row_and_soul_asset(self):
        from campaign_entity_links import guid_value
        guid = '12345678-1234-1234'
        mission = E.fromstring('<L><Entity Name="giver" EntityGuid="%s"/></L>' % guid)
        wh = E.fromstring('<W><SoulList><Souls><Soul><SharedSoulGuid>S</SharedSoulGuid><EntityGuid>%s</EntityGuid>'
                          '</Soul></Souls></SoulList></W>' % guid)
        scheduler = E.fromstring('<S><Schedulers><C_SmartHub EntityGuid="%s"/></Schedulers></S>' % guid_value(guid))
        project = E.fromstring(definition('Project', 'p'))
        assets = E.SubElement(project.find('Skald/Project'), 'Assets')
        E.SubElement(assets, 'SoulAsset', Name='gm_soul_giver', SharedSoulGuids='S')
        resources = {quests.PROJECT: E.tostring(project)}
        evidence = dict(person='giver', soul='S')
        self.assertEqual(quests.npc_audit((mission, wh, scheduler), resources, evidence, 'gm_soul_giver'), [])
        self.assertIn('no scheduler row', quests.npc_audit(
            (mission, wh, E.fromstring('<S><Schedulers/></S>')), resources, evidence, 'gm_soul_giver')[0])
        self.assertIn('no SoulAsset', quests.npc_audit((mission, wh, scheduler), resources, evidence, 'other')[0])
        self.assertIn('0 entities', quests.npc_audit((mission, wh, scheduler), resources, dict(evidence, person='x'), 'a')[0])

    def test_check_results_are_written_and_summarised(self):
        rows = [dict(quest='q', status='pass', problems=[], npc=dict(problems=[]), graph=dict(nodes=3),
                     tracking=[1], delivery=dict(groups=['g']), dialogue=dict(lines=2)),
                dict(quest='r', status='fail', problems=['a | b'])]
        with tempfile.TemporaryDirectory() as temporary:
            counts = quests.write_checks(rows, Path(temporary) / 'out', 'pkg')
            self.assertEqual(counts, {'pass': 1, 'fail': 1})
            lines = (Path(temporary) / 'out/quests.jsonl').read_text().splitlines()
            self.assertEqual([json.loads(l)['quest'] for l in lines], ['q', 'r'])
            markdown = (Path(temporary) / 'out/QUESTS.md').read_text()
            self.assertIn('2 quests: fail 1, pass 1', markdown)
            self.assertIn('a / b', markdown)


# ---------------------------------------------------------------- two quests in one container

def lowering_context(model):
    items = [r['item_id'] for r in model['tables']['quest_item']['rows']]
    source = dict(souls={GIVER: 'giver'}, item_categories={i: '5' for i in items}, reputation={}, exp={}, money={})
    target = dict(item_map={i: i for i in items}, registered_items=items,
                  registered=dict(money_change=set(), reputation_change=set(), xp_change=set(), xp_target=set(),
                                  faction=set(), perk=set()))
    return source, target


GIVER = '4bd6aed3-4d8a-e72c-dae5-fcf29ec7daa1'


def giver_model(name=QUEST):
    model = contract_model()
    model['quest'] = name
    model['tables']['quest']['rows'][0]['quest_name'] = name
    model['tables']['quest_npc']['rows'][0]['soul_id'] = GIVER
    return model


def second_model():
    return giver_model('a_second')


class SharedRegistrationTests(unittest.TestCase):
    def stage(self, row, model, resources):
        return quests.stage_quest(row, model, resources, lowering_context(model), {GIVER}, {}, None)

    def rows(self, second=None):
        first = dict(quest=QUEST, prerequisites={'q_before': 'completed'}, accepted_pending=())
        return first, dict(quest='a_second', prerequisites=second or {'q_before': 'completed', 'q_other': 'unchanged'},
                           accepted_pending=())

    def test_stand_ins_host_and_type_are_registered_once(self):
        first, second = self.rows()
        one, _, report_one, _ = self.stage(first, giver_model(), quests.synthetic_container())
        both, _, report_two, _ = self.stage(second, second_model(), one)
        level = quests.host_of_blob(both[quests.ENTRY])
        self.assertEqual(sorted(n.tag for n in level.find('Nodes')),
                         sorted([QUEST, 'a_second', 'q_before', 'q_other', quests.HOST]))
        files = [d.get('File') for d in level.find('Definitions')]
        self.assertEqual(len(files), len(set(files)))
        self.assertEqual(len(files), 5)
        project = quests.host_of_blob(both[quests.PROJECT])
        self.assertEqual([t.get('TypeName') for t in project.findall('Types/Type')], ['gm_kcd1_questsObjectiveProgress'])
        self.assertEqual(report_one['registration']['types'], ['gm_kcd1_questsObjectiveProgress'])
        self.assertEqual(report_two['registration']['types'], [])
        # The shared files are byte-for-byte what the first quest wrote.
        for name in ('q_before', quests.HOST, QUEST):
            self.assertEqual(both[quests.FOLDER + name + '.xml'], one[quests.FOLDER + name + '.xml'])
        self.assertEqual(len(project.findall('Assets/SoulAsset')), 2)        # the plan's player and the one giver

    def test_a_stand_in_declared_in_another_state_is_refused(self):
        first, second = self.rows(second={'q_before': 'unchanged'})
        one, _, _, _ = self.stage(first, giver_model(), quests.synthetic_container())
        with self.assertRaisesRegex(ValueError, 'declared differently: q_before'):
            self.stage(second, second_model(), one)
        with self.assertRaisesRegex(ValueError, 'already registered'):
            self.stage(first, giver_model(), one)

    def test_value_tables_keep_the_rows_of_the_quests_already_ported(self):
        marker = dict(quests={QUEST: dict(report=dict(value_names=dict(money=['2-minor'], reputation=['micro']))),
                              'older': dict(report={})})
        report = dict(value_names=dict(money=['5-big', '2-minor'], reputation=[]))
        self.assertEqual(quests.merged_value_names(report), dict(money=['2-minor', '5-big'], reputation=[]))
        self.assertEqual(quests.merged_value_names(report, marker), dict(money=['2-minor', '5-big'], reputation=['micro']))

        class Reader:
            def __init__(self, *args): pass
            def __enter__(self): return self
            def __exit__(self, *args): return False
        rows = dict(money=[dict(name='2-minor', change='40'), dict(name='5-big', change='300'), dict(name='x', change='1')],
                    reputation=[dict(name='micro', change='1', target='soul')])
        with tempfile.TemporaryDirectory() as temporary, mock.patch('campaign_sources.RetailSourceReader', Reader), \
                mock.patch('quest_lowering_report.source_rows',
                           side_effect=lambda reader, game, path: rows['money' if 'money' in path else 'reputation']), \
                mock.patch('campaign_quest_rewards.kcd1_value_tables', side_effect=lambda *a: a) as written:
            quests.value_tables(temporary, report, marker)
        self.assertEqual(written.call_args.args[2:], (['2-minor', '5-big'], ['micro']))


# ---------------------------------------------------------------- stage on a tiny fake package

def zip_with(path, files):
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, 'x', zipfile.ZIP_STORED) as archive:
        for name, blob in files.items():
            archive.writestr(name, blob)


def table(rows):
    return '<Table>' + ''.join('<Row><Cell>%s</Cell><Cell>%s</Cell><Cell>%s</Cell></Row>' % (k, v, v)
                               for k, v in rows.items()) + '</Table>'


def fake_package(root, campaign=True, marker=None):
    root = Path(root) / 'package' / 'map'
    travel = {'Libs/Tables/rpg/soul.xml': '<soul/>'}
    if campaign:
        travel.update({quests.ENTRY: definition('Level', 'kcd1_travel'), quests.PROJECT: definition('Project', 'p')})
    if marker is not None:
        travel[quests.MARKER] = json.dumps(marker)
    zip_with(root / quests.TRAVEL, travel)
    zip_with(root / quests.LEVEL_PAK, {'objects_mission0.xml': '<L/>'})
    zip_with(root / quests.ENGLISH, {'dialog/old.ogg': 'old'})
    zip_with(root / quests.ENGLISH_XML, {'text_ui_soul.xml': table({}), 'text_ui_quest.xml': table({'old': 'x'}),
                                         'text_ui_dialog.xml': table({'old': 'y'})})
    zip_with(root / quests.FACIALS, {'index': 'old'})
    (root / 'mod.manifest').write_text('<m/>')
    return root


def fake_games(root):
    games = []
    for name in ('kcd1', 'kcd2'):
        game = Path(root) / name
        (game / 'Data').mkdir(parents=True)
        (game / 'Data/Tables.pak').write_bytes(b'')
        games.append(game)
    return games


def digest_tree(root):
    return {p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(Path(root).rglob('*')) if p.is_file()}


class UpgradeTests(unittest.TestCase):
    def test_a_package_without_the_campaign_entry_is_left_alone(self):
        with tempfile.TemporaryDirectory() as temporary:
            package = fake_package(temporary, campaign=False)
            before = digest_tree(package)
            self.assertEqual(quests.upgrade(package, None, None), ({}, {}))
            self.assertEqual(digest_tree(package), before)
            self.assertEqual(quests.upgrade(Path(temporary) / 'empty', None, None), ({}, {}))

    def test_a_ported_package_is_unchanged_by_a_second_run(self):
        marker = dict(version=quests.VERSION, quests={row['quest']: dict(selection=quests.selection_digest(row), report={})
                                                      for row in quests.QUESTS})
        with tempfile.TemporaryDirectory() as temporary:
            package = fake_package(temporary, marker=marker)
            before = digest_tree(package)
            files, report = quests.upgrade(package, None, None)
            self.assertEqual(files, {})
            self.assertEqual(report['quests'][QUEST]['report'], {})
            self.assertEqual(sorted(report['quests']), [QUEST, BUTCHER])
            self.assertEqual(digest_tree(package), before)

    def test_a_package_with_the_first_quest_gets_only_the_second(self):
        first = dict(selection=quests.selection_digest(ROW), report=dict(value_names=dict(money=['2-minor'], reputation=['a'])),
                     kept='as ported')
        with tempfile.TemporaryDirectory() as temporary:
            package = fake_package(temporary, marker=dict(version=quests.VERSION, quests={QUEST: first}))
            source, target = fake_games(temporary)
            patchers = self.patched(package)
            calls = []
            def tables(source_, report, marker=None):
                calls.append((report['quest'], quests.merged_value_names(report, marker)))
                return {'Libs/Tables/rpg/money_change__gm_kcd1_quest.xml': b'<m/>'}
            patchers[7] = mock.patch.object(quests, 'value_tables', tables)
            with contextlib.ExitStack() as stack:
                for patcher in patchers:
                    stack.enter_context(patcher)
                files, report = quests.upgrade(package, source, target)
            self.assertEqual(self.ported, [BUTCHER])
            # The value tables are one file for every quest: the first quest's rows are written again.
            self.assertEqual(calls, [(BUTCHER, dict(money=['2-minor', 'butcher-money'], reputation=['a']))])
            with zipfile.ZipFile(package / quests.TRAVEL) as archive:
                marker = json.loads(archive.read(quests.MARKER))
            self.assertEqual(marker['quests'][QUEST], first)
            self.assertEqual(marker['quests'][BUTCHER]['selection'], quests.selection_digest(BUTCHER_ROW))
            self.assertEqual(sorted(report['quests']), [QUEST, BUTCHER])
            after = digest_tree(package)
            self.assertEqual(quests.upgrade(package, None, None)[0], {})
            self.assertEqual(digest_tree(package), after)

    def test_a_changed_selection_or_version_is_refused(self):
        with tempfile.TemporaryDirectory() as temporary:
            stale = fake_package(Path(temporary) / 'a', marker=dict(version=quests.VERSION,
                quests={QUEST: dict(selection='0' * 64, report={})}))
            with self.assertRaisesRegex(ValueError, 'selection changed'):
                quests.upgrade(stale, None, None)
            future = fake_package(Path(temporary) / 'b', marker=dict(version=99, quests={}))
            with self.assertRaisesRegex(ValueError, 'Unsupported KCD1 quest migration'):
                quests.upgrade(future, None, None)

    def test_the_source_games_are_required_to_port(self):
        with tempfile.TemporaryDirectory() as temporary:
            package = fake_package(temporary)
            with self.assertRaisesRegex(ValueError, 'folders required'):
                quests.upgrade(package, None, None)
            self.assertEqual(digest_tree(package), digest_tree(package))

    def test_one_overlay_applies_everything_and_the_marker_makes_it_idempotent(self):
        with tempfile.TemporaryDirectory() as temporary:
            package = fake_package(temporary)
            source, target = fake_games(temporary)
            stages = self.patched(package)
            with contextlib.ExitStack() as stack:
                for patcher in stages:
                    stack.enter_context(patcher)
                files, report = quests.upgrade(package, source, target)
            self.assertEqual(sorted(files), sorted([quests.ENGLISH, quests.ENGLISH_XML, quests.FACIALS, quests.LEVEL_PAK,
                                                    'Data/gm_person_x.pak', quests.TRAVEL]))
            self.assertEqual(report['quests'][QUEST]['dialogues'], [ROW['namespace'] + '_27371', ROW['namespace'] + '_27375'])
            self.assertEqual(report['quests'][BUTCHER]['dialogues'],
                             [BUTCHER_ROW['namespace'] + '_27388', BUTCHER_ROW['namespace'] + '_27396'])
            self.assertEqual(self.ported, [QUEST, BUTCHER])
            with zipfile.ZipFile(package / quests.TRAVEL) as archive:
                marker = json.loads(archive.read(quests.MARKER))
                for name in (QUEST, BUTCHER):
                    self.assertIn('Quests/GlueTravel/gm_kcd1_quests/' + name + '.xml', archive.namelist())
                self.assertIn('Libs/Tables/rpg/money_change__gm_kcd1_quest.xml', archive.namelist())
                self.assertEqual(archive.read(quests.DIALOGUE_FOLDER + ROW['namespace'] + '_27371.xml'), b'<bound/>')
                self.assertEqual(archive.read(quests.DIALOGUE_FOLDER + BUTCHER_ROW['namespace'] + '_27396.xml'), b'<bound/>')
            self.assertEqual(sorted(marker['quests']), [QUEST, BUTCHER])
            for row in quests.QUESTS:
                self.assertEqual(marker['quests'][row['quest']]['selection'], quests.selection_digest(row))
                self.assertEqual(marker['quests'][row['quest']]['evidence']['person'], row['people'][0])
            # The second quest was staged on the package the first one left, with the first one's marker.
            self.assertEqual(self.markers_seen, [[], [QUEST]])
            with zipfile.ZipFile(package / quests.ENGLISH_XML) as archive:
                self.assertIn('t1', archive.read('text_ui_dialog.xml').decode())
                self.assertIn('old', archive.read('text_ui_quest.xml').decode())
                self.assertIn('journal', archive.read('text_ui_quest.xml').decode())
            with zipfile.ZipFile(package / quests.LEVEL_PAK) as archive:
                self.assertEqual(archive.read('objects_mission0.xml'), b'<L giver="1"/>')
            self.assertEqual([p.name for p in package.parent.iterdir()], ['map'])
            after = digest_tree(package)
            files, again = quests.upgrade(package, source, target)
            self.assertEqual(files, {})
            self.assertEqual(digest_tree(package), after)

    def test_a_failed_stage_leaves_the_package_untouched(self):
        with tempfile.TemporaryDirectory() as temporary:
            package = fake_package(temporary)
            source, target = fake_games(temporary)
            before = digest_tree(package)
            patchers = self.patched(package)
            patchers[-1] = mock.patch.object(quests, 'bind_scripts', side_effect=ValueError('unlowerable'))
            with contextlib.ExitStack() as stack:
                for patcher in patchers:
                    stack.enter_context(patcher)
                with self.assertRaisesRegex(ValueError, 'unlowerable'):
                    quests.upgrade(package, source, target)
            self.assertEqual(digest_tree(package), before)
            self.assertEqual([p.name for p in package.parent.iterdir()], ['map'])

    def patched(self, package):
        """The stages that need the games, replaced by fakes that write what the real ones write."""
        self.ported, self.markers_seen = [], []

        def selection(source, row, reader):
            self.ported.append(row['quest'])
            return (dict(quest=row['quest'], quest_id='1', behavior_entry='b', behavior_status='s', operations=[1, 2]),
                    dict(person=row['people'][0], soul='S', faction='31', storm_roles=['ROLE'], branches=[]))

        def people(a):
            stage = a.output / 'package'
            shutil_copy(a.mod / quests.TRAVEL, stage / quests.TRAVEL)
            zip_with(stage / quests.LEVEL_PAK, {'objects_mission0.xml': '<L giver="1"/>',
                'whdata_0': '<W><SoulList><Souls/></SoulList></W>'})
            zip_with(stage / 'Data/gm_person_x.pak', {'objects/x': 'x'})
            zip_with(stage / quests.ENGLISH_XML, {'text_ui_soul.xml': table({'ales': 'Ales'}),
                                                  'text_ui_quest.xml': table({'old': 'x'}),
                                                  'text_ui_dialog.xml': table({'old': 'y'})})
            (a.output / 'report.json').write_text(json.dumps(dict(converted=[dict(person=a.person[0])],
                                                                   existing=[], pending=[])))

        def dialogues(a):
            stage = a.output / 'package'
            with zipfile.ZipFile(a.archive) as archive:
                files = {n: archive.read(n) for n in archive.namelist()}
            self.markers_seen.append(sorted(json.loads(files[quests.MARKER])['quests']) if quests.MARKER in files else [])
            for topic in a.start_topic:
                files[quests.DIALOGUE_FOLDER + a.namespace + '_' + topic + '.xml'] = b'<dialogue/>'
            zip_with(stage / quests.TRAVEL, files)
            zip_with(stage / quests.ENGLISH, {'dialog/new.ogg': 'new'})
            zip_with(stage / quests.ENGLISH_XML, {'text_ui_dialog.xml': table({'t1': 'Hello'})})
            zip_with(stage / quests.FACIALS, {'index': 'new'})

        def stage_quest(row, model_, base, context, souls, factions, text):
            resources = dict(base)
            resources['Quests/GlueTravel/gm_kcd1_quests/' + row['quest'] + '.xml'] = b'<quest/>'
            money = ['butcher-money'] if row['quest'] == BUTCHER else []
            report = dict(quest=row['quest'], pending=sorted(row['accepted_pending']),
                          value_names=dict(money=money, reputation=[]))
            return resources, {}, report, [dict(key='journal', text='Beggars')]

        def bind(row, model_, resources, bindings, npc_assets):
            resources = dict(resources)
            for _, topic in row['branches']:
                resources[quests.DIALOGUE_FOLDER + row['namespace'] + '_' + topic + '.xml'] = b'<bound/>'
            return resources, dict(lifecycle=[], delivery=[])

        class Reader:
            def __init__(self, *args): pass
            def __enter__(self): return self
            def __exit__(self, *args): return False

        return [
            mock.patch('campaign_sources.RetailSourceReader', Reader),
            mock.patch.object(quests, 'verify_selection', selection),
            mock.patch.object(quests, 'source_model', return_value=dict(quest='q_huntPtacek')),
            mock.patch('campaign_quest_text.load', return_value=({}, dict(missing=[]))),
            mock.patch('build_quest_people_test.build', people),
            mock.patch('quest_lowering_report.load_context', return_value=({'souls': {}}, {})),
            mock.patch.object(quests, 'stage_quest', stage_quest),
            mock.patch.object(quests, 'value_tables',
                              return_value={'Libs/Tables/rpg/money_change__gm_kcd1_quest.xml': b'<m/>'}),
            mock.patch('build_actor_dialogues_test.build', dialogues),
            mock.patch.object(quests, 'prerequisite_report', return_value=[]),
            mock.patch.object(quests, 'bind_scripts', bind)]


def shutil_copy(source, destination):
    import shutil
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, destination)


# ---------------------------------------------------------------- retail

@unittest.skipUnless((KCD1 / 'Data/Tables.pak').exists() and (KCD2 / 'Data/Tables.pak').exists(),
                     'requires installed KCD1 and KCD2 data')
class RetailPlanTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.resources, cls.report = quests.plan_quest(ROW, KCD1, KCD2)

    def test_the_lowerings_leave_only_the_accepted_pending_rows(self):
        r = self.report
        self.assertEqual((r['unsupported_before'], r['unsupported_after']), (10, 1))
        self.assertEqual(r['pending'], sorted(ROW['accepted_pending']))
        self.assertEqual([x['kind'] for x in r['remaining']], ['rewards'])
        self.assertEqual(r['remaining'][0]['rows'], 15)

    def test_lifecycle_and_hand_in_scripts_are_lowered(self):
        r = self.report
        self.assertEqual([(s['function'], s['sequence']) for d in r['lifecycle'] for s in d['sites']],
                         [('ActivateQuest', 'seq_56751'), ('StartQuest', 'seq_56903')])
        sites = [s for d in r['delivery'] for s in d['sites']]
        self.assertEqual(sites, ['seq_56758', 'seq_56767', 'seq_56768'])
        groups = [g['objectives'] for d in r['delivery'] for g in d['groups']]
        self.assertEqual(groups, [['mushrooms', 'boarM'], ['hare'], ['deer'], ['doe'], ['boar']])
        self.assertEqual(r['npc_assets'], {'ALES_VUDCE_SKALICKYCH': 'gm_soul_rat_refugee_ales'})

    def test_prerequisite_stand_in_and_files(self):
        r = self.report
        self.assertEqual([p['quest'] for p in r['assumed_prerequisites']], ['q_huntPtacek'])
        self.assertEqual(r['assumed_prerequisites'][0]['sequences'][0]['sequence'], '56751')
        self.assertIn(quests.MARKER, r['files'])
        self.assertIn(quests.FOLDER + QUEST + '.xml', r['files'])
        self.assertFalse(r['controller_pending']['converted'])
        self.assertFalse(r['runtime_verified'])

    def test_no_quest_system_call_remains_and_the_shared_predicate_map_is_clean(self):
        from campaign_dialogue_conditions import OBJECTIVE
        self.assertNotIn('IsObjectiveTrackedCompleted', OBJECTIVE)
        for _, topic in ROW['branches']:
            blob = self.resources[quests.DIALOGUE_FOLDER + ROW['namespace'] + '_' + topic + '.xml']
            self.assertEqual(quests.exit_script_calls(blob), [])

    def test_plan_runs_every_quest_that_retail_alone_can_plan(self):
        report = quests.plan(KCD1, KCD2)
        self.assertEqual(list(report['quests']), [row['quest'] for row in quests.QUESTS if not row.get('needs_package')])
        self.assertEqual(list(report['skipped']), [BUTCHER])
        self.assertEqual(report['quests'][QUEST]['pending'], self.report['pending'])
        self.assertFalse(report['runtime_verified'])

    def test_the_summary_counts_what_the_plan_found(self):
        summary, = quests.summary(dict(quests={QUEST: self.report}))
        self.assertEqual((summary['lifecycle_sites'], summary['delivery_sites'], summary['delivery_groups'],
                          summary['pending']), (2, 3, 5, 15))

    def test_the_lowered_graph_passes_the_package_audit(self):
        resources = self.resources
        import zipfile as z
        with z.ZipFile(KCD2 / 'Data/IPL_GameData.pak') as archive:
            definitions = quests.Definitions(archive.read(quests.DEFINITIONS))
        dialogues = [ROW['namespace'] + '_' + t for _, t in ROW['branches']]
        owned = {QUEST, quests.HOST, 'q_huntPtacek', *dialogues}
        owned.update(n.get('Name') for n in quests.host_of_blob(resources[quests.ENTRY]).iterfind('Nodes/*')
                     if n.get('Name', '').startswith('lowered_delivery_'))
        paths = [quests.FOLDER + QUEST + '.xml', quests.FOLDER + 'q_huntPtacek.xml', quests.FOLDER + quests.HOST + '.xml',
                 *[quests.DIALOGUE_FOLDER + d + '.xml' for d in dialogues], quests.ENTRY]
        audit = quests.graph_audit(resources, paths, owned, definitions, quests.aliases_of(resources))
        self.assertEqual(audit['problems'], [])
        self.assertGreater(audit['nodes'], 100)


@unittest.skipUnless((KCD1 / 'Data/Tables.pak').exists() and (KCD2 / 'Data/Tables.pak').exists()
                     and (PACKAGE / quests.TRAVEL).is_file(),
                     'requires installed KCD1 and KCD2 data and a built package with the shop imports')
class PackagePlanTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.first, cls.first_report = quests.plan_quest(ROW, KCD1, KCD2, PACKAGE)
        cls.resources, cls.report = quests.plan_quest(BUTCHER_ROW, KCD1, KCD2, PACKAGE, base=cls.first)

    def test_the_package_resolves_every_item_and_leaves_the_accepted_pending_rows(self):
        r = self.report
        self.assertEqual((r['unsupported_before'], r['unsupported_after']), (11, 1))
        self.assertEqual(r['pending'], sorted(BUTCHER_ROW['accepted_pending']))
        self.assertEqual(len(r['pending']), 10)
        self.assertEqual(sorted(t['objective'] for t in r['tracking'] if t['mode'] == 'manual'),
                         ['boar', 'boarFeast', 'deerFeast', 'hareFeast', 'kidney', 'liver', 'offal'])
        self.assertEqual(self.first_report['pending'], sorted(ROW['accepted_pending']))

    def test_one_window_for_whichever_group_is_started(self):
        r = self.report
        self.assertEqual([(s['function'], s['sequence']) for d in r['lifecycle'] for s in d['sites']],
                         [('ActivateQuest', 'seq_56805'), ('StartQuest', 'seq_56905')])
        hand_in = r['delivery'][1]
        self.assertEqual(hand_in['sites'], ['seq_56812', 'seq_56887', 'seq_56888'])
        self.assertEqual([g['objectives'] for g in hand_in['groups']],
                         [['boar'], ['hareFeast', 'deerFeast', 'boarFeast'], ['kidney'], ['liver'], ['offal']])
        self.assertEqual([g.get('aggregate') for g in hand_in['groups']], [None, 'feast', None, None, None])
        self.assertEqual((hand_in['decision'], hand_in['accept'], hand_in['reject']),
                         ('topic_27398', 'seq_56813', 'seq_56815'))
        self.assertEqual(r['npc_assets'], {'REZNIK_SAZAVA': 'gm_soul_sas_butcher'})
        for _, topic in BUTCHER_ROW['branches']:
            blob = self.resources[quests.DIALOGUE_FOLDER + BUTCHER_ROW['namespace'] + '_' + topic + '.xml']
            self.assertEqual(quests.exit_script_calls(blob), [])

    def test_the_feast_is_completed_before_the_source_effects_read_it(self):
        dialogue = BUTCHER_ROW['namespace'] + '_27396'
        stem = 'lowered_delivery_' + dialogue + '_hareFeast_deerFeast_boarFeast_'
        nodes = {n.get('Name'): n for n in quests.host_of_blob(self.resources[quests.ENTRY]).iterfind('Nodes/*')}
        sources = lambda node, port: [e.get('From') for e in node.findall('Edge') if e.get('To') == port]
        quest = nodes[BUTCHER]
        for member in ('hareFeast', 'deerFeast', 'boarFeast'):
            self.assertEqual(sources(quest, 'complete_' + member), [stem + 'accepted.A'])
        self.assertEqual(sources(nodes[stem + 'aggregate'], 'Exec'), [stem + 'accepted.B'])
        self.assertEqual(sources(nodes[stem + 'aggregate'], 'Condition'), [BUTCHER + '.feast_Started'])
        self.assertEqual(sources(quest, 'complete_feast'), [stem + 'aggregate.True'])
        program = sources(nodes[dialogue + '_effects_56813_0'], 'Exec')
        self.assertEqual(program, ['lowered_delivery_' + dialogue + '_' + g + '_accepted.' + port for g, port in (
            ('boar', 'B'), ('hareFeast_deerFeast_boarFeast', 'C'), ('kidney', 'B'), ('liver', 'B'), ('offal', 'B'))])
        items = [quests.node_constants(nodes[stem + 'item_%d' % i]) for i in range(3)]
        self.assertEqual([(c['Amount'], c['MinimumHealth']) for c in items], [('100', '0.5'), ('70', '0.5'), ('40', '0.5')])

    def test_shared_registrations_and_the_first_quest_are_untouched(self):
        level = quests.host_of_blob(self.resources[quests.ENTRY])
        tags = [n.tag for n in level.find('Nodes')]
        for name in (QUEST, BUTCHER, quests.HOST, 'q_huntPtacek', 'q_returnToSkalitz'):
            self.assertEqual(tags.count(name), 1, name)
        project = quests.host_of_blob(self.resources[quests.PROJECT])
        self.assertEqual([t.get('TypeName') for t in project.findall('Types/Type')].count('gm_kcd1_questsObjectiveProgress'), 1)
        for path in (quests.FOLDER + QUEST + '.xml', quests.FOLDER + quests.HOST + '.xml',
                     *(quests.DIALOGUE_FOLDER + ROW['namespace'] + '_' + t + '.xml' for _, t in ROW['branches'])):
            self.assertEqual(self.resources[path], self.first[path], path)
        self.assertNotIn(quests.FOLDER + quests.HOST + '.xml', self.report['files'])
        self.assertIn(quests.FOLDER + 'q_returnToSkalitz.xml', self.report['files'])

    def test_the_lowered_graph_passes_the_package_audit(self):
        with zipfile.ZipFile(KCD2 / 'Data/IPL_GameData.pak') as archive:
            definitions = quests.Definitions(archive.read(quests.DEFINITIONS))
        dialogues = [BUTCHER_ROW['namespace'] + '_' + t for _, t in BUTCHER_ROW['branches']]
        owned = {BUTCHER, quests.HOST, 'q_returnToSkalitz', *dialogues}
        owned.update(n.get('Name') for n in quests.host_of_blob(self.resources[quests.ENTRY]).iterfind('Nodes/*')
                     if any(n.get('Name', '').startswith('lowered_delivery_' + d + '_') for d in dialogues))
        paths = [quests.FOLDER + BUTCHER + '.xml', quests.FOLDER + 'q_returnToSkalitz.xml',
                 *[quests.DIALOGUE_FOLDER + d + '.xml' for d in dialogues], quests.ENTRY]
        audit = quests.graph_audit(self.resources, paths, owned, definitions, quests.aliases_of(self.resources))
        self.assertEqual(audit['problems'], [])
        for path, d in zip(paths[2:4], dialogues):
            self.assertEqual(quests.dialogue_audit(self.resources[path], d), [])
        model_items = {t['objective']: t['requirements'] for t in self.report['tracking']}
        self.assertEqual(model_items['offal'][0]['target_item'][:8], '3a2d670c')


if __name__ == '__main__':
    unittest.main()
