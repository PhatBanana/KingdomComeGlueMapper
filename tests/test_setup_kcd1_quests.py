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
        marker = dict(version=quests.VERSION, quests={QUEST: dict(selection=quests.selection_digest(ROW), report={})})
        with tempfile.TemporaryDirectory() as temporary:
            package = fake_package(temporary, marker=marker)
            before = digest_tree(package)
            files, report = quests.upgrade(package, None, None)
            self.assertEqual(files, {})
            self.assertEqual(report['quests'][QUEST]['report'], {})
            self.assertEqual(digest_tree(package), before)

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
            with zipfile.ZipFile(package / quests.TRAVEL) as archive:
                marker = json.loads(archive.read(quests.MARKER))
                self.assertIn('Quests/GlueTravel/gm_kcd1_quests/' + QUEST + '.xml', archive.namelist())
                self.assertIn('Libs/Tables/rpg/money_change__gm_kcd1_quest.xml', archive.namelist())
                self.assertEqual(archive.read(quests.DIALOGUE_FOLDER + ROW['namespace'] + '_27371.xml'), b'<bound/>')
            self.assertEqual(marker['quests'][QUEST]['selection'], quests.selection_digest(ROW))
            self.assertEqual(marker['quests'][QUEST]['evidence']['person'], 'rat_refugee_ales')
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
        model = dict(quest=QUEST, quest_id='1', behavior_entry='b', behavior_status='s', operations=[1, 2])
        evidence = dict(person='rat_refugee_ales', soul='S', faction='31', storm_roles=['ROLE'], branches=[])

        def people(a):
            stage = a.output / 'package'
            shutil_copy(a.mod / quests.TRAVEL, stage / quests.TRAVEL)
            zip_with(stage / quests.LEVEL_PAK, {'objects_mission0.xml': '<L giver="1"/>',
                'whdata_0': '<W><SoulList><Souls/></SoulList></W>'})
            zip_with(stage / 'Data/gm_person_x.pak', {'objects/x': 'x'})
            zip_with(stage / quests.ENGLISH_XML, {'text_ui_soul.xml': table({'ales': 'Ales'}),
                                                  'text_ui_quest.xml': table({'old': 'x'}),
                                                  'text_ui_dialog.xml': table({'old': 'y'})})
            (a.output / 'report.json').write_text(json.dumps(dict(converted=[dict(person='rat_refugee_ales')],
                                                                   existing=[], pending=[])))

        def dialogues(a):
            stage = a.output / 'package'
            with zipfile.ZipFile(a.archive) as archive:
                files = {n: archive.read(n) for n in archive.namelist()}
            for topic in ('27371', '27375'):
                files[quests.DIALOGUE_FOLDER + ROW['namespace'] + '_' + topic + '.xml'] = b'<dialogue/>'
            zip_with(stage / quests.TRAVEL, files)
            zip_with(stage / quests.ENGLISH, {'dialog/new.ogg': 'new'})
            zip_with(stage / quests.ENGLISH_XML, {'text_ui_dialog.xml': table({'t1': 'Hello'})})
            zip_with(stage / quests.FACIALS, {'index': 'new'})

        def stage_quest(row, model_, base, context, souls, factions, text):
            resources = dict(base)
            resources['Quests/GlueTravel/gm_kcd1_quests/' + QUEST + '.xml'] = b'<quest/>'
            report = dict(quest=QUEST, pending=sorted(row['accepted_pending']), value_names=dict(money=[], reputation=[]))
            return resources, {}, report, [dict(key='journal', text='Beggars')]

        def bind(row, model_, resources, bindings, npc_assets):
            resources = dict(resources)
            for topic in ('27371', '27375'):
                resources[quests.DIALOGUE_FOLDER + ROW['namespace'] + '_' + topic + '.xml'] = b'<bound/>'
            return resources, dict(lifecycle=[], delivery=[])

        class Reader:
            def __init__(self, *args): pass
            def __enter__(self): return self
            def __exit__(self, *args): return False

        return [
            mock.patch('campaign_sources.RetailSourceReader', Reader),
            mock.patch.object(quests, 'verify_selection', return_value=(model, evidence)),
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

    def test_plan_runs_every_selected_quest(self):
        report = quests.plan(KCD1, KCD2)
        self.assertEqual(list(report['quests']), [row['quest'] for row in quests.QUESTS])
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


if __name__ == '__main__':
    unittest.main()
