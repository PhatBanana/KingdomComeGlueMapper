"""Modeled quest effects (rewards, deaths, areas, deliveries) and the exhaustive walk, on synthetic graphs."""
import copy
import os
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from quest_lab import Unsupported
from quest_lab.graph import Graph
from quest_lab.kcd1 import Reference, parse_script
from quest_lab.objects import INVENTORY, SOUL
from quest_lab.pure import descriptor, matches
from quest_lab.runner import Runner
from quest_lab.source import Source
from quest_lab.walk import ASSUMED, Walk, slice_container, table

KCD1 = Path(os.environ.get('GLUEMAPPER_KCD1', 'D:/SteamLibrary/steamapps/common/KingdomComeDeliverance'))
KCD2 = Path(os.environ.get('GLUEMAPPER_KCD2', 'D:/SteamLibrary/steamapps/common/KingdomComeDeliverance2'))
MEAT = '11111111-1111-4111-8111-111111111111'
GIVER = '22222222-2222-4222-8222-222222222222'


def wrap(text):
    return ('<Database><Skald>' + text + '</Skald></Database>').encode()


def bag(items):
    return {INVENTORY: {'queries': [dict(method='Items', arguments={}, result=items)]}}


def world(items=None):
    return dict(assets={'hero': 'player', 'giver': GIVER},
                assumptions=dict(ASSUMED, **{'delivery.player_inventory': 'player-bag', 'area.inactive_trigger': 'missed'}),
                objects={'player': {SOUL: {'properties': {'Inventory': 'player-bag'}}}, 'player-bag': bag(items or {}),
                         GIVER: {SOUL: {'properties': {'Inventory': 'giver-bag'}}}, 'giver-bag': bag({})})


TYPE = '''<Types><Type TypeName="Progress"><StateTypeEnumeration Name="Unchanged"/><StateTypeEnumeration Name="Started"/>
  <StateTypeEnumeration Name="Completed"/><StateTypeEnumeration Name="Failed"/><StateTypeEnumeration Name="Canceled"/></Type></Types>'''
QUEST = '''<Quest Name="hunt_quest">''' + TYPE + '''<Ports>
  <Port Name="activate" Direction="In" Type="trigger"/><Port Name="start" Direction="In" Type="trigger"/>
  <Port Name="start_hunt" Direction="In" Type="trigger"/><Port Name="complete_hunt" Direction="In" Type="trigger"/>
  <Port Name="cancel_hunt" Direction="In" Type="trigger"/><Port Name="enter" Direction="In" Type="trigger"/>
  <Port Name="available" Direction="Out" Type="bool"/><Port Name="started" Direction="Out" Type="bool"/>
  <Port Name="completed" Direction="Out" Type="bool"/>
  <Port Name="hunt_Unchanged" Direction="Out" Type="bool"/><Port Name="hunt_Started" Direction="Out" Type="bool"/>
  <Port Name="hunt_Completed" Direction="Out" Type="bool"/><Port Name="hunt_Failed" Direction="Out" Type="bool"/>
  <Port Name="hunt_Canceled" Direction="Out" Type="bool"/><Port Name="hunt_TrackedCompleted" Direction="Out" Type="bool"/>
  <Port Name="dead" Direction="Out" Type="bool"/><Port Name="inside" Direction="Out" Type="bool"/></Ports><Nodes>
  <State Name="quest_progress" TypeT="wh::questmodule::QuestProgress"><Constant Name="DefaultValue" Value="None"/>
    <Edge From="start" To="SetActive"/></State>
  <State Name="quest_available" TypeT="bool"><Constant Name="DefaultValue" Value="false"/><Edge From="activate" To="SetTrue"/></State>
  <State Name="objective_1" TypeT="Progress"><Constant Name="DefaultValue" Value="Unchanged"/>
    <Edge From="start_hunt" To="SetStarted"/><Edge From="quest_progress.OnActive" To="SetStarted"/>
    <Edge From="complete_hunt" To="SetCompleted"/><Edge From="cancel_hunt" To="SetCanceled"/></State>
  <ObjectProperties Name="soul" DeclaringType="wh::rpgmodule::I_Soul"><Asset Name="I_Soul" Alias="hero"/></ObjectProperties>
  <MemberFunction Name="inventory" MethodName="Items" DeclaringType="wh::entitymodule::Inventory">
    <Edge From="soul.Inventory" To="Inventory"/></MemberFunction>
  <Function Name="wanted" MethodName="wh::entitymodule::CreateItemClassDescriptor" DeclaringType="wh::entitymodule">
    <Constant Name="ItemClass" Value="''' + MEAT + '''"/><Constant Name="Amount" Value="2"/>
    <Constant Name="MinimumHealth" Value="0.5"/></Function>
  <MemberFunction Name="tracked" MethodName="FullyMatchesItems" DeclaringType="wh::entitymodule::ItemDescriptor">
    <Edge From="wanted.ItemDescriptor" To="ItemDescriptor"/><Edge From="inventory.Items" To="InputItems"/></MemberFunction>
  <AddReward Name="lowered_reward_1"><Edge From="objective_1.OnCompleted" To="AddReward"/>
    <Rewards><MoneyReward Amount="kcd1_small"/><SoulReputationReward ReputationChange="kcd1_up" Target="giver"/></Rewards></AddReward>
  <SoulDeathTrigger Name="watch"><Asset Name="Souls" Alias="giver"/><Edge From="objective_1.Started" To="IsActive"/></SoulDeathTrigger>
  <State Name="dead_latch" TypeT="bool"><Constant Name="DefaultValue" Value="false"/><Edge From="watch.OnAllDeath" To="SetTrue"/></State>
  <AreaTrigger Name="area"><Asset Name="Souls" Alias="hero"/><Asset Name="Areas" Alias="camp"/>
    <Edge From="quest_progress.Active" To="IsActive"/></AreaTrigger>
  <State Name="inside_latch" TypeT="bool"><Constant Name="DefaultValue" Value="false"/>
    <Edge From="area.OnEnter" To="SetTrue"/><Edge From="area.OnLeave" To="SetFalse"/></State>
  <Output Name="Output"><Edge From="quest_available.State" To="available"/><Edge From="quest_progress.Active" To="started"/>
    <Edge From="quest_progress.Done" To="completed"/><Edge From="objective_1.Unchanged" To="hunt_Unchanged"/>
    <Edge From="objective_1.Started" To="hunt_Started"/><Edge From="objective_1.Completed" To="hunt_Completed"/>
    <Edge From="objective_1.Failed" To="hunt_Failed"/><Edge From="objective_1.Canceled" To="hunt_Canceled"/>
    <Edge From="tracked.bool" To="hunt_TrackedCompleted"/><Edge From="dead_latch.State" To="dead"/>
    <Edge From="inside_latch.State" To="inside"/></Output></Nodes></Quest>'''
OFFER = '''<FaderDialog Name="offer"><Ports><Port Name="go" Direction="Out" Type="trigger"/></Ports>
  <Dialogue TechnicalStatus="Enabled"><Decision Name="topic_1"><Sequences>
    <Sequence Name="seq_1" EndType="EndDialogue" EntryCondition="!SequenceUsed('seq_1')" Visibility="Internal">
      <UiPrompt StringName="p" Text="Yes"/><Triggers><Port Name="go"/></Triggers><Elements/></Sequence>
  </Sequences></Decision></Dialogue></FaderDialog>'''
SUCCESS = "Port('result') == Enum('DeliveryResult','Success') AND Port('started')"
HAND_IN = '''<FaderDialog Name="hand_in"><Ports><Port Name="started" Direction="In" Type="bool"/>
  <Port Name="tracked" Direction="In" Type="bool"/><Port Name="result" Direction="In" Type="DeliveryResult"/>
  <Port Name="delivery_begin" Direction="Out" Type="trigger"/><Port Name="delivery_accept" Direction="Out" Type="trigger"/>
  <Port Name="delivery_reject" Direction="Out" Type="trigger"/></Ports>
  <Dialogue TechnicalStatus="Enabled"><Decision Name="topic_2"><Sequences>
    <Sequence Name="seq_10" EndType="Decision" EntryCondition="Port('started') AND Port('tracked')"><UiPrompt StringName="p" Text="Here"/>
      <Elements/><Decision Name="topic_3"><Sequences>
      <Sequence Name="seq_11" EndType="Decision"><Triggers><Port Name="delivery_begin"/></Triggers><Elements/>
        <Decision Name="topic_4"><Sequences>
        <Sequence Name="seq_12" EntryCondition="''' + SUCCESS + '''"><Triggers><Port Name="delivery_accept"/></Triggers><Elements/></Sequence>
        <Sequence Name="seq_13" EndType="EndDialogue" EntryCondition="!(''' + SUCCESS + ''')"><Triggers><Port Name="delivery_reject"/></Triggers>
          <Elements/></Sequence></Sequences></Decision></Sequence></Sequences></Decision></Sequence>
  </Sequences></Decision></Dialogue></FaderDialog>'''
LEVEL = '''<Level Name="level"><Definitions><Definition File="quest.xml"/><Definition File="offer.xml"/>
  <Definition File="hand_in.xml"/></Definitions><Nodes>
  <hunt_quest Name="hunt_quest"><Edge From="offer.go" To="start"/><Edge From="accepted.A" To="complete_hunt"/>
    <Edge From="cancel_gate.True" To="cancel_hunt"/></hunt_quest>
  <offer Name="offer"/>
  <hand_in Name="hand_in"><Edge From="hunt_quest.hunt_Started" To="started"/>
    <Edge From="hunt_quest.hunt_TrackedCompleted" To="tracked"/><Edge From="handler.DeliveryResult" To="result"/></hand_in>
  <ObjectProperties Name="npc" DeclaringType="wh::rpgmodule::I_Soul"><Asset Name="I_Soul" Alias="giver"/></ObjectProperties>
  <Function Name="item" MethodName="wh::entitymodule::CreateItemClassDescriptor" DeclaringType="wh::entitymodule">
    <Constant Name="ItemClass" Value="''' + MEAT + '''"/><Constant Name="Amount" Value="2"/><Constant Name="MinimumHealth" Value="0.5"/></Function>
  <Function Name="filter" MethodName="wh::entitymodule::CreateItemClassDescriptor" DeclaringType="wh::entitymodule">
    <Constant Name="ItemClass" Value="''' + MEAT + '''"/></Function>
  <MakeArray Name="items" TypeT="wh::entitymodule::HomogenousItemDescriptors"><Edge From="item.ItemDescriptor" To="A"/></MakeArray>
  <MakeArray Name="filters" TypeT="wh::entitymodule::HomogenousItemDescriptors"><Edge From="filter.ItemDescriptor" To="A"/></MakeArray>
  <MakeArray Name="labels" TypeT="wh::framework::LocalizedStrings"><Constant Name="A" Value="label_meat"/></MakeArray>
  <Function Name="delivery" MethodName="wh::entitymodule::CreateItemDelivery" DeclaringType="wh::entitymodule">
    <Edge From="items.Array" To="DeliveryDescriptors"/><Edge From="filters.Array" To="PlayerInventoryFilters"/>
    <Edge From="labels.Array" To="Labels"/><Edge From="npc.Inventory" To="DeliveryInventory"/></Function>
  <ItemDeliveryHandler Name="handler"><Edge From="delivery.ItemDelivery" To="ItemDelivery"/>
    <Edge From="begin.True" To="BeginDelivery"/><Edge From="accept.True" To="AcceptDelivery"/>
    <Edge From="reject.True" To="RejectDelivery"/></ItemDeliveryHandler>
  <If Name="begin"><Edge From="hand_in.delivery_begin" To="Exec"/><Edge From="hunt_quest.hunt_Started" To="Condition"/></If>
  <If Name="accept"><Edge From="hand_in.delivery_accept" To="Exec"/><Edge From="hunt_quest.hunt_Started" To="Condition"/></If>
  <If Name="reject"><Edge From="hand_in.delivery_reject" To="Exec"/><Edge From="hunt_quest.hunt_Started" To="Condition"/></If>
  <TriggerSequence Name="accepted"><Edge From="handler.OnAccept" To="Exec"/></TriggerSequence>
  <If Name="cancel_gate"><Edge From="accepted.B" To="Exec"/><Edge From="hunt_quest.hunt_Completed" To="Condition"/></If>
  <Trace Name="unrelated"><Edge From="other.Bool" To="Value"/></Trace><Engine Name="other"/>
  </Nodes></Level>'''
FILES = {'quest.xml': wrap(QUEST), 'offer.xml': wrap(OFFER), 'hand_in.xml': wrap(HAND_IN), 'level.xml': wrap(LEVEL)}
UNRELATED = '<Trace Name="unrelated"><Edge From="other.Bool" To="Value"/></Trace><Engine Name="other"/>'
CLEAN = dict(FILES, **{'level.xml': wrap(LEVEL.replace(UNRELATED, ''))})      # the container without its other content
assert CLEAN != FILES


def source_model():
    """The same quest as KCD1 tables: Begin -> hunt (manual, 2 meat at health 0.5, pays money and reputation)."""
    row = lambda **values: dict(dict(quest_id='7'), **values)
    tables = dict(
        quest_objective=[row(objective_id='1', objective_name='hunt', condition='', is_exclusive='False', is_hidden='False',
                             autocomplete_timeout_str='-1', expiration_timeout_str='-1', time='0')],
        quest_transition=[row(enabled='True', from_objective_id='2', to_objective_id='1')],
        quest_item=[row(quest_asset_id='5', item_id=MEAT, min_health='0.5')],
        quest_npc=[], quest_tracked_asset=[row(objective_id='1', quest_asset_id='5', count='2')],
        quest_reward_money=[row(objective_id='1', money_change_id='3', is_immediate='True', is_exclusive='False')],
        quest_reward_reputation=[row(objective_id='1', reputation_change_id='4', soul_id=GIVER, is_immediate='True')])
    model = dict(quest='hunt_quest', quest_id='7', tables={k: dict(rows=v) for k, v in tables.items()},
                 graph=dict(nodes={'2': dict(attributes={'Class': 'Quest:Begin'})}), behavior_documents={})
    sequence = lambda sid, topic, **source: dict(
        source=dict(dict(sequence_id=sid, next='0', flags='0', timeout='0', ui_prompt='', script=''),
                    **{k: v for k, v in source.items() if k not in ('condition', 'effects')}),
        entry=dict(entry_condition=source.get('condition', ''), npc_entry_condition='', sequence_id=sid, topic_id=topic),
        effects=source.get('effects', []))
    done = "IsObjectiveCompleted('hunt_quest','hunt')"
    offer = dict(start_topic='1', functions={}, topics={'1': dict(sequences=[
        sequence('1', '1', ui_prompt='p', flags='1', timeout='-1', script="QuestSystem.StartQuest('hunt_quest')")])})
    hand_in = dict(start_topic='2', functions={'ready': "IsObjectiveTrackedCompleted('hunt_quest','hunt')"}, topics={
        '2': dict(sequences=[sequence('10', '2', ui_prompt='p', next='3',
                                      condition="IsObjectiveStarted('hunt_quest','hunt') & ready")]),
        '3': dict(sequences=[sequence('11', '3', next='4',
                                      script="QuestSystem.OpenInventory('hunt_quest', dc['GIVER'].this.id,'hunt')")]),
        '4': dict(sequences=[
            sequence('12', '4', condition=done, effects=[dict(action='3', condition=done, objective_id='1', order_by='1',
                                                              quest_id='7', sequence_id='12')]),
            sequence('13', '4', flags='1', condition='!(' + done + ')')])})
    return model, [offer, hand_in]


def walk(files=FILES, **options):
    model, dialogues = source_model()
    blobs, kept, externals = slice_container(files, 'level.xml', ['hunt_quest', 'offer', 'hand_in'])
    blobs['quest.xml'] = files['quest.xml']
    return Walk(Source.blobs(blobs), 'level', 'hunt_quest', ['offer', 'hand_in'], model, dialogues, GIVER,
                {'hero': 'player', 'giver': GIVER, 'camp': 'camp-area'}, money={'3': 'kcd1_small'}, **options).run(), kept, externals


def scenario(steps, items=None, entry='level', **extra):
    return Runner(dict(schema=1, name='t', entry=entry, steps=steps, **dict(world(items), **extra)), source=Source.blobs(CLEAN)).run()


class ItemTests(unittest.TestCase):
    def test_minimum_health_counts_only_fresh_stacks_and_needs_stacks(self):
        target = descriptor({'ItemClass': MEAT, 'Amount': 3, 'MinimumHealth': 0.5})
        self.assertEqual(target, dict(item_class=MEAT, amount=3, minimum_health=0.5))
        stock = lambda *stacks: {MEAT: [dict(amount=a, health=h) for a, h in stacks]}
        for items, expected in [(stock((3, 0.5)), True), (stock((2, 1.0), (1, 0.49)), False), (stock((2, 1), (1, 0.9)), True), ({}, False)]:
            self.assertEqual(matches({'ItemDescriptor': target, 'InputItems': items}), expected)
        with self.assertRaisesRegex(Unsupported, 'stacks with health'):
            matches({'ItemDescriptor': target, 'InputItems': {MEAT: 5}})
        with self.assertRaises(Unsupported):
            descriptor({'ItemClass': MEAT, 'Amount': 1, 'MinimumHealth': 1.5})
        self.assertEqual(descriptor({'ItemClass': MEAT}), dict(item_class=MEAT))
        with self.assertRaisesRegex(Unsupported, 'Amount'):
            matches({'ItemDescriptor': dict(item_class=MEAT), 'InputItems': {}})


class EffectTests(unittest.TestCase):
    def test_lowered_quest_loads_without_unsupported_nodes(self):
        self.assertEqual(Graph(Source.blobs(FILES), 'hunt_quest', objects={}).unsupported, [])

    def test_reward_is_paid_exactly_once_across_snapshot_and_replay(self):
        paid = [dict(node='lowered_reward_1', rewards=[dict(kind='MoneyReward', Amount='kcd1_small'),
                dict(kind='SoulReputationReward', ReputationChange='kcd1_up', Target='giver')])]
        result = scenario([
            dict(action='fire', port='start'), dict(action='save', name='before'),
            dict(action='fire', port='complete_hunt'), dict(action='assert_ledger', count=1, payouts=paid),
            dict(action='fire', port='complete_hunt'), dict(action='assert_ledger', count=1),
            dict(action='save', name='after'), dict(action='advance', duration='2h'), dict(action='load', name='after'),
            dict(action='advance', duration='2h'), dict(action='assert_ledger', count=1),
            dict(action='load', name='before'), dict(action='assert_ledger', count=0),
            dict(action='fire', port='complete_hunt'), dict(action='assert_ledger', count=1, payouts=paid)], entry='hunt_quest')
        self.assertEqual(result['status'], 'PASS', result['error'])
        self.assertTrue(result['graph']['world']['assumptions']['rewards.load_does_not_replay']['used'])

    def test_loading_after_a_payout_needs_the_replay_assumption(self):
        steps = [dict(action='fire', port='start'), dict(action='fire', port='complete_hunt'), dict(action='save', name='s'),
                 dict(action='load', name='s'), dict(action='assert_ledger', count=1)]
        result = scenario(steps, entry='hunt_quest', assumptions={})
        self.assertEqual(result['status'], 'UNSUPPORTED')
        self.assertIn('rewards.load_does_not_replay', result['error'])

    def test_death_reaches_only_an_active_trigger(self):
        result = scenario([dict(action='fire', port='start'), dict(action='soul_death', soul=GIVER),
                           dict(action='assert', values={'output.dead': True})], entry='hunt_quest')
        self.assertEqual(result['status'], 'PASS', result['error'])
        early = [dict(action='soul_death', soul=GIVER), dict(action='fire', port='start'),
                 dict(action='assert', values={'output.dead': False})]
        self.assertEqual(scenario(early, entry='hunt_quest')['status'], 'PASS')
        undeclared = scenario(early, entry='hunt_quest', assumptions={})
        self.assertEqual(undeclared['status'], 'UNSUPPORTED')
        self.assertIn('soul_death.inactive_trigger', undeclared['error'])

    def test_area_presence_is_a_scenario_event_into_a_latch(self):
        world_ = world(); world_['assets']['camp'] = 'camp-area'
        steps = [dict(action='fire', port='start'), dict(action='area', soul='player', area='camp-area', event='enter'),
                 dict(action='assert', values={'output.inside': True}),
                 dict(action='area', soul='player', area='other-area', event='enter'),
                 dict(action='area', soul='player', area='camp-area', event='leave'),
                 dict(action='assert', values={'output.inside': False})]
        result = Runner(dict(schema=1, name='t', entry='hunt_quest', steps=steps, **world_), source=Source.blobs(FILES)).run()
        self.assertEqual(result['status'], 'PASS', result['error'])
        before = [dict(action='area', soul='player', area='camp-area', event='enter'), dict(action='fire', port='start'),
                  dict(action='assert', values={'output.inside': False})]
        result = Runner(dict(schema=1, name='t', entry='hunt_quest', steps=before, **world_), source=Source.blobs(FILES)).run()
        self.assertEqual(result['status'], 'PASS', result['error'])
        self.assertTrue(result['graph']['world']['assumptions']['area.inactive_trigger']['used'])


class DeliveryTests(unittest.TestCase):
    OPEN = [dict(action='dialogue_start', dialogue='offer'), dict(action='dialogue_choose', dialogue='offer', sequence='seq_1'),
            dict(action='dialogue_end', dialogue='offer'), dict(action='dialogue_start', dialogue='hand_in'),
            dict(action='dialogue_choose', dialogue='hand_in', sequence='seq_10'),
            dict(action='dialogue_choose', dialogue='hand_in', sequence='seq_11'),
            dict(action='assert_delivery', open='handler', handler='handler', phase='open')]
    FRESH = {MEAT: [dict(amount=1, health=0.2), dict(amount=3, health=0.9)]}

    def test_hand_over_accepts_pays_and_moves_exactly_the_amount(self):
        result = scenario(self.OPEN + [
            dict(action='delivery_resolve', handler='handler', outcome='hand_over'),
            dict(action='assert_dialogue', dialogue='hand_in', choices=['seq_12']),
            dict(action='assert_ledger', count=0),
            dict(action='dialogue_choose', dialogue='hand_in', sequence='seq_12'),
            dict(action='assert_ledger', count=1), dict(action='assert_delivery', handler='handler', phase='idle', result='Success'),
            dict(action='assert', values={'hunt_quest.hunt_Canceled': True}),
            dict(action='assert_dialogue', dialogue='hand_in', choices=[]),      # a stale Success: the objective is not started
            dict(action='dialogue_end', dialogue='hand_in')], self.FRESH)
        self.assertEqual(result['status'], 'PASS', result['error'])
        items = lambda name: result['graph']['object_snapshots'][name][INVENTORY]['queries'][0]['result']
        self.assertEqual(items('player-bag'), {MEAT: [dict(amount=1, health=0.2), dict(amount=1, health=0.9)]})
        self.assertEqual(items('giver-bag'), {MEAT: [dict(amount=2, health=0.9)]})

    def test_closing_the_window_rejects_and_takes_nothing(self):
        result = scenario(self.OPEN + [
            dict(action='delivery_resolve', handler='handler', outcome='close', result='Canceled'),
            dict(action='assert_dialogue', dialogue='hand_in', choices=['seq_13']),
            dict(action='dialogue_choose', dialogue='hand_in', sequence='seq_13'), dict(action='dialogue_end', dialogue='hand_in'),
            dict(action='assert_ledger', count=0), dict(action='assert', values={'hunt_quest.hunt_Started': True})], self.FRESH)
        self.assertEqual(result['status'], 'PASS', result['error'])
        self.assertEqual(result['graph']['object_snapshots']['player-bag'][INVENTORY]['queries'][0]['result'], self.FRESH)

    def test_the_dialogue_waits_for_the_window_and_an_open_window_is_not_a_pass(self):
        waiting = scenario(self.OPEN, self.FRESH)
        self.assertEqual(waiting['status'], 'UNSUPPORTED')
        self.assertIn('delivery window', waiting['error'])
        early = scenario(self.OPEN + [dict(action='assert_dialogue', dialogue='hand_in', choices=[])], self.FRESH)
        self.assertEqual(early['status'], 'ERROR')
        self.assertIn('resolve it', early['error'])

    def test_the_player_cannot_hand_over_what_he_does_not_hold(self):
        # 2 fresh open the conversation; a hand-over needs them in the window too.
        thin = {MEAT: [dict(amount=2, health=0.9)]}
        ok = scenario(self.OPEN + [dict(action='delivery_resolve', handler='handler', outcome='hand_over'),
                                   dict(action='assert_delivery', handler='handler', result='Success'),
                                   dict(action='dialogue_choose', dialogue='hand_in', sequence='seq_12'),
                                   dict(action='dialogue_end', dialogue='hand_in')], thin)
        self.assertEqual(ok['status'], 'PASS', ok['error'])
        graph = Graph(Source.blobs(CLEAN), 'level', **world({MEAT: [dict(amount=2, health=0.4)]}))
        self.assertFalse(graph.value('hunt_quest.hunt_TrackedCompleted'))

    def test_every_delivery_guess_must_be_declared(self):
        result = scenario(self.OPEN, self.FRESH, assumptions={'dialogue.nested_end_topic': 'root'})
        self.assertEqual(result['status'], 'UNSUPPORTED')
        self.assertIn('delivery.', result['error'])
        with self.assertRaisesRegex(ValueError, 'Unknown assumption'):
            Graph(Source.blobs(FILES), 'level', assumptions={'made.up': True})

    def test_nested_end_topic_stays_unsupported_until_declared(self):
        strict = Graph(Source.blobs(CLEAN), 'level', objects={})
        self.assertEqual({u['reason'] for u in strict.unsupported}, {'Nested EndTopic requires conversation-stack support'})
        self.assertEqual(Graph(Source.blobs(CLEAN), 'level', **world()).unsupported, [])


class ReferenceTests(unittest.TestCase):
    def test_scripts_and_conditions_are_read_from_the_source_text(self):
        self.assertEqual(parse_script("QuestSystem.ActivateQuest('q')"), [('lifecycle', 'ActivateQuest', 'q')])
        guarded = ("if QuestSystem.IsObjectiveStarted('q', 'b') then \r\nQuestSystem.OpenInventory('q', dc['R'].this.id,'a','b') "
                   "\r\nelse QuestSystem.OpenInventory('q',dc['R'].this.id,'c') end")
        self.assertEqual(parse_script(guarded), [('window', 'q', 'R', 'b', ['a', 'b'], ['c'])])
        with self.assertRaises(Unsupported):
            parse_script("Game.DoSomething()")
        model, dialogues = source_model()
        reference = Reference(model, dialogues, {'q_other': 'Completed'})
        self.assertTrue(reference.condition("IsQuestCompleted('q_other') AND (!IsQuestStarted('hunt_quest') | 0)"))
        with self.assertRaises(Unsupported):
            reference.condition("HourOfDay() > 5")
        with self.assertRaises(Unsupported):
            reference.condition("IsQuestCompleted('q_undeclared')")

    def test_hand_in_completes_pays_and_takes_the_tracked_count(self):
        model, dialogues = source_model()
        r = Reference(model, dialogues)
        r.set_items({MEAT: [dict(amount=3, health=1.0)]})
        r.begin_talk(0); r.choose('1'); r.leave()
        self.assertEqual(r.state['objectives'], {'hunt': 'Started'})
        r.begin_talk(1); r.choose('10'); r.choose('11'); r.window(True)
        self.assertEqual((r.state['objectives']['hunt'], [e['kind'] for e in r.state['ledger']]),
                         ('Completed', ['money', 'soul_reputation']))
        self.assertEqual(r.offered(), ('12', []))
        r.choose('12')
        self.assertEqual((r.state['objectives']['hunt'], r.state['items']), ('Canceled', {MEAT: [dict(amount=1, health=1.0)]}))


class WalkTests(unittest.TestCase):
    def test_the_container_is_cut_to_the_quest_closure(self):
        result, kept, externals = walk()
        self.assertNotIn('unrelated', kept)
        self.assertEqual(externals, {})
        self.assertEqual(result['unsupported_nodes'], [])

    def test_every_path_agrees_with_the_source_model(self):
        result, _, _ = walk()
        self.assertEqual((result['status'], result['mismatch_count'], result['blocked'], result['truncated']), ('PASS', 0, [], 0),
                         table([result]))
        states = {e['state'] for e in result['ends']}
        self.assertIn('quest Started; hunt=Canceled', states)
        self.assertIn('giver dead; quest Started; hunt=Canceled', states)
        done = next(e for e in result['ends'] if e['state'] == 'quest Started; hunt=Canceled')
        self.assertEqual(done['kcd1_events'], ['start_quest hunt_quest', 'start hunt', 'complete hunt', 'cancel hunt'])
        for name in ('delivery.result_after_close', 'dialogue.unprompted_sequence', 'delivery.exactly_from_larger_stack'):
            self.assertTrue(result['assumptions'][name]['used'], name)
        resets, _, _ = walk(assumptions={'delivery.result_after_close': 'resets'})
        self.assertEqual(resets['status'], 'PASS', table([resets]))

    def test_a_broken_lowering_is_a_mismatch_with_its_path(self):
        cases = {
            'the hand-in no longer completes': ('<Edge From="accepted.A" To="complete_hunt"/>', '', 'objective hunt'),
            'the reward row is gone': ('<MoneyReward Amount="kcd1_small"/>', '', 'rewards paid'),
            'the wrong money row': ('kcd1_small', 'kcd1_large', 'money rows'),
            'stale meat counts': ('<Constant Name="MinimumHealth" Value="0.5"/></Function>\n  <MemberFunction Name="tracked"',
                                  '</Function>\n  <MemberFunction Name="tracked"', 'offered at topic 2'),
            'the window asks for more': ('<Constant Name="Amount" Value="2"/><Constant Name="MinimumHealth" Value="0.5"/></Function>\n  <Function Name="filter"',
                                         '<Constant Name="Amount" Value="3"/><Constant Name="MinimumHealth" Value="0.5"/></Function>\n  <Function Name="filter"', None),
            'the offer never starts the quest': ('<Edge From="offer.go" To="start"/>', '', 'quest started'),
        }
        for label, (old, new, field) in cases.items():
            with self.subTest(label):
                files = {k: v.decode().replace(old, new).encode() for k, v in FILES.items()}
                self.assertNotEqual(files, FILES)
                result, _, _ = walk(files)
                self.assertEqual(result['status'], 'FAIL', label)
                fields = {d['field'] for m in result['mismatches'] for d in m['differences']}
                if field: self.assertIn(field, fields)
                self.assertTrue(all(m['path'] for m in result['mismatches']))

    def test_another_quest_in_the_closure_must_have_a_declared_state(self):
        from quest_lab.walk import external_contracts
        level = LEVEL.replace('<offer Name="offer"/>', '<offer Name="offer"/><q_story Name="q_story"><Edge From="x.y" To="start"/></q_story>') \
                     .replace('<Edge From="hunt_quest.hunt_Started" To="started"/>', '<Edge From="q_story.completed" To="started"/>')
        blobs, kept, externals = slice_container(dict(FILES, **{'level.xml': wrap(level)}), 'level.xml', ['hunt_quest', 'offer', 'hand_in'])
        self.assertEqual(externals, {'q_story': ['completed']})
        with self.assertRaisesRegex(ValueError, 'does not declare the state of q_story'):
            external_contracts(externals, {})
        contracts = external_contracts(externals, {'q_story': 'Completed'})
        graph = Graph(Source.blobs(dict(blobs, **{'quest.xml': FILES['quest.xml']})), 'level', contracts, **world())
        self.assertEqual(graph.unsupported, [])
        self.assertTrue(graph.value('hand_in.started'))


@unittest.skipUnless((KCD1 / 'Data/Tables.pak').exists() and (KCD2 / 'Data/Tables.pak').exists(), 'needs retail KCD1 and KCD2')
class RetailWalkTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from quest_lab.ported import run
        cls.result = run(KCD1, KCD2, only=['a_huntsman_alex'])['quests'][0]

    def test_ales_agrees_with_kcd1_on_every_path_but_the_unconverted_controller_rule(self):
        r = self.result
        self.assertEqual((r['blocked'], r['truncated'], r['structure'], r['unsupported_nodes']), ([], 0, [], []))
        self.assertTrue(all(s['status'] == 'PASS' for s in r['lab_scenarios']), r['lab_scenarios'])
        # KCD1's controller cancels the quest when the giver dies; the port does not convert it (controller_pending).
        self.assertEqual({(c['move'], tuple(c['fields'])) for c in r['mismatch_classes']} - {('death', ('quest started',))}, set())
        order = next(e['kcd1_events'] for e in r['ends'] if e['state'].startswith('quest Completed; hare=Canceled'))
        self.assertEqual([e for e in order if e.startswith('complete ') and 'save' not in e],
                         ['complete hare', 'complete boar', 'complete deer', 'complete mushrooms', 'complete boarM',
                          'complete doe', 'complete endOfFun'])


if __name__ == '__main__':
    unittest.main()
