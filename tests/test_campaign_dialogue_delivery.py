import copy
from pathlib import Path
import string
import sys
import unittest
import xml.etree.ElementTree as E
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
import campaign_quest_tracking
from campaign_dialogue_delivery import aggregates, bind, canonical, delivered, parse, plan
from campaign_dialogue_effects import predicate
from campaign_dialogue_runtime import attach_dialogue
from campaign_quest_graph import emit_project
from test_campaign_quest_graph import model

QUEST = 'arbitrary_quest'
ITEMS = {'first': ('00000000-0000-0000-0000-00000000000a', '70', '0.5'),
         'returnHome': ('00000000-0000-0000-0000-00000000000b', '5', '0.5'),
         'disabled': ('00000000-0000-0000-0000-00000000000c', '25', '')}
NPC = {'GIVER': 'gm_soul_giver'}
CALL = "QuestSystem.OpenInventory('arbitrary_quest', dc['GIVER'].this.id,%s)"
BRANCHED = ("if QuestSystem.IsObjectiveStarted('arbitrary_quest', 'disabled') then \r\n"
            + CALL % "'returnHome','disabled'" + " \r\nelse \r\n" + CALL % "'first'" + " \r\nend")
DONE = "Port('c_first_done') OR (Port('c_disabled_done') AND Port('c_home_done'))"
# The same outcome read through an objective that restates "returnHome and disabled are completed".
JOINED = "Port('c_first_done') OR Port('c_second_done')"

# Port lists copied from retail KCD2 Libs/concept/definitions.xml (IPL_GameData.pak)
# for every node type the lowering writes. Unused I_Soul outputs are left out.
RETAIL = E.fromstring('''<Definitions>
<Definition TypeName="Function" Name="And" MethodName="math::boolean::And" DeclaringType="math::boolean">
  <Port Name="" Direction="In" Type="bool" IsVariadic="true"/><Port Name="bool" Direction="Out" Type="bool"/></Definition>
<Definition TypeName="Function" Name="Or" MethodName="math::boolean::Or" DeclaringType="math::boolean">
  <Port Name="" Direction="In" Type="bool" IsVariadic="true"/><Port Name="bool" Direction="Out" Type="bool"/></Definition>
<Definition TypeName="Function" Name="Not" MethodName="math::boolean::Not" DeclaringType="math::boolean">
  <Port Name="Value" Direction="In" Type="bool"/><Port Name="bool" Direction="Out" Type="bool"/></Definition>
<Definition TypeName="IfFunction" Name="If(Compare)" MethodName="Control::Compare" DeclaringType="Control">
  <Port Name="Exec" Direction="In" Type="trigger"/><Port Name="True" Direction="Out" Type="trigger"/>
  <Port Name="False" Direction="Out" Type="trigger"/><Port Name="ValueA" Direction="In" Type=""/>
  <Port Name="Op" Direction="In" Type="wh::conceptmodule::Operator"/><Port Name="ValueB" Direction="In" Type=""/></Definition>
<Definition TypeName="Function" Name="CreateItemClassDescriptor" MethodName="wh::entitymodule::CreateItemClassDescriptor" DeclaringType="wh::entitymodule">
  <Port Name="ItemClass" Direction="In" Type="wh::entitymodule::ItemClassId"/><Port Name="NegateClass" Direction="In" Type="bool"/>
  <Port Name="Amount" Direction="In" Type="int"/><Port Name="EquippedFilter" Direction="In" Type="wh::entitymodule::ItemFilterType"/>
  <Port Name="QuestFilter" Direction="In" Type="wh::entitymodule::ItemFilterType"/>
  <Port Name="StolenFilter" Direction="In" Type="wh::entitymodule::ItemFilterType"/>
  <Port Name="MinimumHealth" Direction="In" Type="float"/><Port Name="MaximumHealth" Direction="In" Type="float"/>
  <Port Name="ItemDescriptor" Direction="Out" Type="wh::entitymodule::ItemClassDescriptor*"/></Definition>
<Definition TypeName="Function" Name="CreateItemDelivery" MethodName="wh::entitymodule::CreateItemDelivery" DeclaringType="wh::entitymodule">
  <Port Name="DeliveryDescriptors" Direction="In" Type="wh::entitymodule::ItemDescriptors"/>
  <Port Name="DeliveryInventory" Direction="In" Type="wh::entitymodule::ItemHolder*"/>
  <Port Name="PlayerInventoryFilters" Direction="In" Type="wh::entitymodule::ItemDescriptors"/>
  <Port Name="DeliveryMode" Direction="In" Type="DeliveryMode"/><Port Name="Labels" Direction="In" Type="wh::framework::LocalizedStrings"/>
  <Port Name="AmountsAsGroschen" Direction="In" Type="bool"/><Port Name="Legalize" Direction="In" Type="bool"/>
  <Port Name="ItemDelivery" Direction="Out" Type="wh::entitymodule::ItemDelivery*"/></Definition>
<Definition TypeName="ObjectProperties" Name="I_SoulProperties" DeclaringType="wh::rpgmodule::I_Soul">
  <Port Name="I_Soul" Direction="In" Type="wh::rpgmodule::I_Soul*"/><Port Name="Inventory" Direction="Out" Type="wh::entitymodule::Inventory*"/></Definition>
<Definition TypeName="If" Name="If">
  <Port Name="Exec" Direction="In" Type="trigger"/><Port Name="Condition" Direction="In" Type="bool"/>
  <Port Name="True" Direction="Out" Type="trigger"/><Port Name="False" Direction="Out" Type="trigger"/></Definition>
<Definition TypeName="ItemDeliveryHandler" Name="ItemDeliveryHandler">
  <Port Name="BeginDelivery" Direction="In" Type="trigger"/><Port Name="AcceptDelivery" Direction="In" Type="trigger"/>
  <Port Name="RejectDelivery" Direction="In" Type="trigger"/><Port Name="ItemDelivery" Direction="In" Type="wh::entitymodule::ItemDelivery*"/>
  <Port Name="OnResultAvailable" Direction="Out" Type="trigger"/><Port Name="OnAccept" Direction="Out" Type="trigger"/>
  <Port Name="OnReject" Direction="Out" Type="trigger"/><Port Name="DeliveryResult" Direction="Out" Type="DeliveryResult"/>
  <Port Name="DeliveryItems" Direction="Out" Type="wh::entitymodule::Items"/></Definition>
<Definition TypeName="MakeArray" Name="MakeArray">
  <Port Name="Value" Direction="In" Type="" IsVariadic="true"/><Port Name="Array" Direction="Out" Type=""/></Definition>
<Definition TypeName="TriggerSequence" Name="TriggerSequence">
  <Port Name="Exec" Direction="In" Type="trigger"/><Port Name="OnExec" Direction="Out" Type="trigger" IsVariadic="true"/></Definition>
<Type TypeName="DeliveryResult"><Enumeration Name="Success"/><Enumeration Name="Canceled"/><Enumeration Name="WrongItems"/>
  <Enumeration Name="MissingItems"/><Enumeration Name="StolenMismatch"/><Enumeration Name="QualityMismatch"/>
  <Enumeration Name="PriceMismatch"/><Enumeration Name="Invalid"/></Type>
</Definitions>''')
# Array and label types as written by retail zlodej_zeli/kvasene_zeli.xml.
RETAIL_ARRAYS = {'wh::entitymodule::HomogenousItemDescriptors', 'wh::framework::LocalizedStrings'}


def source(join=None):
    """first, returnHome and disabled are manual item hand-ins; second is untracked.

    join lists the objectives whose completion starts `second`, which then completes at once
    (KCD1 condition '1'): an aggregate objective when they are exactly one delivered group.
    """
    m = model()
    if join:
        rows = m['tables']['quest_objective']['rows']
        ids = {r['objective_name']: r['objective_id'] for r in rows}
        next(r for r in rows if r['objective_name'] == 'second')['condition'] = '1'
        pairs = [('1', '3'), ('3', '4'), *((ids[o], ids['second']) for o in join), (ids['second'], '2')]
        m['tables']['quest_transition']['rows'] = [dict(quest_id='42', from_objective_id=a, to_objective_id=b,
                                                        enabled='True') for a, b in pairs]
        m['graph']['edges'] = [dict(nodeOut=a, nodeIn=b, portOut='Out', portIn='In', enabled='1') for a, b in pairs]
    ids = {r['objective_name']: r['objective_id'] for r in m['tables']['quest_objective']['rows']}
    m['tables']['quest_tracked_asset'] = dict(rows=[dict(quest_id='42', objective_id=ids[o], quest_asset_id=str(90 + i),
        count=ITEMS[o][1], map_asset_id='') for i, o in enumerate(ITEMS)])
    m['tables']['quest_item'] = dict(rows=[dict(quest_id='42', quest_asset_id=str(90 + i), item_id=ITEMS[o][0],
        item_category_id='', item_category_type_id='', item_category_subtype_id='', min_health=ITEMS[o][2])
        for i, o in enumerate(ITEMS)])
    names = {ids[o]: dict(name='Bring ' + o) for o in ITEMS}
    bindings = dict(player_asset='player', item_map={v[0]: v[0] for v in ITEMS.values()},
                    registered_items=[v[0] for v in ITEMS.values()])
    return m, bindings, {QUEST: dict(name='Feast', description='Hunt.', objectives=names)}


def dialogue(scripts=(BRANCHED, BRANCHED), accept=DONE, reject='!(' + DONE + ')', pair=('action_home', 'action_disabled'),
             extra_outcome=False):
    root = E.Element('Database', Name='brambora')
    host = E.SubElement(E.SubElement(root, 'Skald'), 'FaderDialog', Name='handin')
    ports = E.SubElement(host, 'Ports')
    for name in ('active', 'c_first_done', 'c_home_done', 'c_disabled_done', 'c_first_started', 'c_second_done'):
        E.SubElement(ports, 'Port', Name=name, Direction='In', Type='bool')
    for name in ('effects_2', 'action_home', 'action_disabled', 'action_first'):
        E.SubElement(ports, 'Port', Name=name, Direction='Out', Type='trigger')
    d1 = E.SubElement(E.SubElement(E.SubElement(host, 'Dialogue'), 'Decision', Name='d1'), 'Sequences')
    opened = E.SubElement(d1, 'Sequence', Name='seq_1', EndType='Decision', EntryCondition="Port('active')",
                          ExitScript=scripts[0])
    E.SubElement(opened, 'Elements')
    d2 = E.SubElement(E.SubElement(opened, 'Decision', Name='d2'), 'Sequences')
    thanks = E.SubElement(d2, 'Sequence', Name='seq_2', EndType='Decision', EntryCondition=accept)
    triggers = E.SubElement(thanks, 'Triggers')
    E.SubElement(triggers, 'Port', Name='gm_sequence_active'); E.SubElement(triggers, 'Port', Name='effects_2')
    E.SubElement(thanks, 'Elements')
    d3 = E.SubElement(E.SubElement(thanks, 'Decision', Name='d3'), 'Sequences')
    for name, started in (('seq_4', pair), ('seq_5', ('action_first',))):
        order = E.SubElement(d3, 'Sequence', Name=name)
        for port in started: E.SubElement(E.SubElement(order, 'Triggers'), 'Port', Name=port)
        E.SubElement(order, 'Elements')
    later = E.SubElement(d2, 'Sequence', Name='seq_3', EndType='EndDialogue', EntryCondition=reject)
    E.SubElement(later, 'Elements')
    if extra_outcome:
        E.SubElement(E.SubElement(d2, 'Sequence', Name='seq_9'), 'Elements')
    again = E.SubElement(d1, 'Sequence', Name='seq_6', EndType='GoTo', GoToDecision='d2', ExitScript=scripts[1])
    E.SubElement(again, 'Elements')
    return E.tostring(root)


def staged(join=None, **changes):
    """(dialogue, container, quest, tracking) as the stage holds them after attach_dialogue."""
    m, bindings, names = source(join)
    files, _ = emit_project([m], 'Example', localization=names)
    path = 'Example/' + QUEST + '.xml'
    files[path], tracking = campaign_quest_tracking.bind(files[path], m, bindings)
    output = lambda objective, state: dict(quest=QUEST, output=objective + '_' + state)
    action = lambda verb, objective: dict(quest=QUEST, input=verb + '_' + objective, source={})
    cancel = lambda objective, port: dict(action('cancel', objective), predicate=predicate("Port('" + port + "')"))
    report = dict(active_port='active',
        conditions=dict(c_first_done=output('first', 'Completed'), c_home_done=output('returnHome', 'Completed'),
                        c_disabled_done=output('disabled', 'Completed'), c_first_started=output('first', 'Started'),
                        c_second_done=output('second', 'Completed')),
        actions=dict(action_home=action('start', 'returnHome'), action_disabled=action('start', 'disabled'),
                     action_first=action('start', 'first')),
        action_programs=dict(effects_2=[cancel('disabled', 'c_disabled_done'), cancel('first', 'c_first_done'),
                                        cancel('returnHome', 'c_home_done')]))
    blob = dialogue(**changes)
    files = attach_dialogue(files, 'Example', blob, report, QUEST + '.available')
    return files['Example/handin.xml'], files['Example.xml'], files[path], campaign_quest_tracking.plan(m, bindings)


def lowered(**changes):
    blob, entry, quest, tracking = staged(**changes)
    found = plan(blob, entry, quest, tracking, NPC)
    new_blob, new_entry = bind(blob, entry, quest, found, tracking, NPC, assets={'gm_soul_giver', 'player'})
    return E.fromstring(new_blob), E.fromstring(new_entry), found, (new_blob, new_entry, quest, tracking)


def constants(node):
    return {c.get('Name'): c.get('Value') for c in node.findall('Constant')}


def froms(node, port):
    return [e.get('From') for e in node.findall('Edge') if e.get('To') == port]


class ScriptTests(unittest.TestCase):
    def test_single_call(self):
        self.assertEqual(parse(" QuestSystem.OpenInventory('q', dc.GIVER.this.id, 'a', 'b'); "),
                         dict(quest='q', role='GIVER', branches=[dict(guard=None, objectives=['a', 'b'])]))

    def test_started_branch(self):
        self.assertEqual(parse(BRANCHED), dict(quest=QUEST, role='GIVER', branches=[
            dict(guard='disabled', objectives=['returnHome', 'disabled']), dict(guard=None, objectives=['first'])]))

    def test_anything_else_is_not_parsed(self):
        for script in ('', "QuestSystem.OpenInventory('q', dc.GIVER.this.id)", "QuestSystem.OpenInventory('q', 5, 'a')",
                       CALL % "'first'" + " Utils.Foo()", CALL % "'first'" + CALL % "'first'",
                       BRANCHED.replace('IsObjectiveStarted', 'IsObjectiveCompleted'),
                       BRANCHED.replace("dc['GIVER'].this.id,'first'", "dc['OTHER'].this.id,'first'"),
                       BRANCHED.replace("IsObjectiveStarted('arbitrary_quest'", "IsObjectiveStarted('other'"),
                       "if x then " + CALL % "'first'" + " end",
                       "QuestSystem.OpenInventory('q', dc.GIVER.this.id, name)"):
            with self.subTest(script=script):
                self.assertIsNone(parse(script))


class PlanTests(unittest.TestCase):
    def test_groups_come_from_what_one_sequence_starts(self):
        found = plan(*staged(), NPC)
        self.assertEqual(found['pending'], [])
        self.assertEqual(found['sites'], ['seq_1', 'seq_6'])
        self.assertEqual([g['objectives'] for g in found['groups']], [['returnHome', 'disabled'], ['first']])
        self.assertEqual([g['name'] for g in found['groups']], ['returnHome_disabled', 'first'])
        self.assertEqual((found['decision'], found['accept_sequence'], found['reject_sequence']), ('d2', 'seq_2', 'seq_3'))
        self.assertEqual(found['programs'], [dict(port='effects_2', steps=['handin_effects_2_0'])])
        self.assertEqual((found['role'], found['soul_asset'], found['runtime_verified']), ('GIVER', 'gm_soul_giver', False))

    def test_objectives_started_apart_are_separate_deliveries(self):
        apart = "Port('c_first_done') OR Port('c_disabled_done') OR Port('c_home_done')"
        change = dict(scripts=(CALL % "'returnHome','disabled','first'",) * 2, pair=('action_home',))
        found = plan(*staged(accept=apart, reject='!(' + apart + ')', **change), NPC)
        self.assertEqual(found['pending'], [])
        # The source outcome condition pairs the two, which this grouping does not explain.
        self.assertTrue(plan(*staged(**change), NPC)['pending'])
        self.assertEqual([g['objectives'] for g in found['groups']], [['returnHome'], ['disabled'], ['first']])

    def test_descriptors_are_the_tracking_plans(self):
        blob, entry, quest, tracking = staged()
        found = plan(blob, entry, quest, tracking, NPC)
        tracked = {r['objective']: r['requirements'] for r in tracking['converted']}
        self.assertEqual(set(tracked), set(ITEMS))
        for group in found['groups']:
            wanted = [(o, q['target_item'], q['count'], q['minimum_health']) for o in group['objectives'] for q in tracked[o]]
            self.assertEqual([(d['objective'], d['item_class'], d['amount'], d['minimum_health'])
                              for d in group['descriptors']], wanted)
        self.assertEqual(found['groups'][1]['descriptors'][0]['label'],
                         E.fromstring(quest).find(".//Objective[@Name='first']/LocalizedName").get('StringName'))
        changed = copy.deepcopy(tracking)
        changed['converted'][0]['requirements'][0]['count'] = 71
        moved = plan(blob, entry, quest, changed, NPC)
        self.assertEqual(moved['groups'][1]['descriptors'][0]['amount'], 71)
        # The quest file still tracks 70: the two would disagree, so nothing is written.
        with self.assertRaises(ValueError): bind(blob, entry, quest, moved, changed, NPC)

    def test_outcome_conditions_must_be_the_delivered_groups_and_their_negation(self):
        self.assertEqual(plan(*staged(accept="(Port('c_home_done') AND Port('c_disabled_done')) OR Port('c_first_done')",
            reject="!(Port('c_first_done') OR (Port('c_home_done') AND Port('c_disabled_done')))"), NPC)['pending'], [])
        for change in (dict(accept="Port('c_first_done') OR Port('c_disabled_done') OR Port('c_home_done')"),
                       dict(accept="Port('c_first_done')"),
                       dict(accept=DONE + " OR Port('c_first_started')"),
                       dict(accept="(" + DONE + ") AND !SequenceUsed('seq_2')"),
                       dict(reject="!(Port('c_first_done'))"), dict(reject=''), dict(reject=DONE),
                       dict(accept='!(' + DONE + ')', reject='!(' + DONE + ')'),
                       dict(extra_outcome=True)):
            with self.subTest(change=change):
                blob, entry, quest, tracking = staged(**change)
                found = plan(blob, entry, quest, tracking, NPC)
                self.assertEqual([p['reason'] for p in found['pending']],
                                 ['outcome conditions are not "a delivered group is completed" and its negation'])
                with self.assertRaises(ValueError): bind(blob, entry, quest, found, tracking, NPC)

    def test_canonical_form_ignores_only_order_and_grouping(self):
        outputs = dict(a='first_Completed', b='disabled_Completed', c='returnHome_Completed')
        shape = lambda text: canonical(predicate(text), outputs)
        expected = delivered([['returnHome', 'disabled'], ['first']])
        self.assertEqual(shape("(Port('c') AND Port('b')) OR Port('a')"), expected)
        self.assertEqual(shape("Port('a') OR ((Port('b')) AND Port('c'))"), expected)
        self.assertEqual(shape("!(Port('a') OR Port('b') AND Port('c'))"), ('not', expected))
        self.assertNotEqual(shape("(Port('a') OR Port('b')) AND Port('c')"), expected)
        self.assertNotEqual(shape("Port('a') OR (Port('b') AND Port('x'))"), expected)

    def test_unprovable_shapes_stay_pending(self):
        cases = {
            'unsupported hand-in script': dict(scripts=(BRANCHED + ' Utils.Foo()', BRANCHED)),
            'hand-in scripts of one dialogue differ': dict(scripts=(BRANCHED, CALL % "'first'")),
            'objective listed twice': dict(scripts=(CALL % "'first','first'",) * 2),
            'quest does not expose objective nowhere': dict(scripts=(CALL % "'nowhere'",) * 2),
            'objective has no converted item tracking: second': dict(scripts=(CALL % "'second'",) * 2),
            'group spans both script branches: disabled, returnHome': dict(scripts=(
                BRANCHED.replace("'returnHome','disabled'", "'disabled'").replace("'first'", "'first','returnHome'"),) * 2),
            'script guard is not the started-check of one delivered group': dict(scripts=(
                BRANCHED.replace("'returnHome','disabled'", "'returnHome','disabled','first'").replace(",'first') \r\nend", ",'second') \r\nend"),) * 2),
            'hand-in for another quest: other': dict(scripts=(CALL.replace('arbitrary_quest', 'other') % "'first'",) * 2),
        }
        for reason, change in cases.items():
            with self.subTest(reason=reason):
                found = plan(*staged(**change), NPC)
                self.assertEqual([p['reason'] for p in found['pending']], [reason])
        blob, entry, quest, tracking = staged()
        self.assertEqual(plan(blob, entry, quest, tracking, {})['pending'][0]['reason'], 'no soul asset for dialogue role GIVER')
        auto = copy.deepcopy(tracking)
        auto['converted'][0]['mode'] = 'auto'
        self.assertEqual(plan(blob, entry, quest, auto, NPC)['pending'][0]['reason'],
                         'objective is not a manual item hand-in: first')

    def test_dialogue_without_a_hand_in_is_left_alone(self):
        blob, entry, quest, tracking = staged()
        root = E.fromstring(blob)
        for sequence in root.iter('Sequence'): sequence.attrib.pop('ExitScript', None)
        found = plan(E.tostring(root), entry, quest, tracking, NPC)
        self.assertEqual((found['sites'], found['groups'], found['pending']), ([], [], []))
        self.assertEqual(bind(E.tostring(root), entry, quest, found, tracking, NPC), (E.tostring(root), entry))


class BindTests(unittest.TestCase):
    def test_dialogue_follows_the_retail_delivery_idiom(self):
        dialogue_root, _, found, _ = lowered()
        host = dialogue_root.find('./Skald/FaderDialog')
        ports = {p.get('Name'): (p.get('Direction'), p.get('Type')) for p in host.findall('Ports/Port')}
        for port in ('delivery_begin', 'delivery_accept', 'delivery_reject'):
            self.assertEqual(ports[port], ('Out', 'trigger'))
        for port in ('delivery_result_returnHome_disabled', 'delivery_result_first'):
            self.assertEqual(ports[port], ('In', 'DeliveryResult'))
        for port in ('delivery_started_returnHome', 'delivery_started_disabled', 'c_first_started', 'c_second_done'):
            self.assertEqual(ports[port], ('In', 'bool'))
        self.assertNotIn('delivery_started_first', ports)
        self.assertNotIn('effects_2', ports)
        sequences = {s.get('Name'): s for s in host.iter('Sequence')}
        triggers = lambda name: [p.get('Name') for p in sequences[name].findall('Triggers/Port')]
        for name in ('seq_1', 'seq_6'):
            self.assertIsNone(sequences[name].get('ExitScript'))
            self.assertEqual(triggers(name), ['delivery_begin'])
        self.assertEqual(triggers('seq_2'), ['gm_sequence_active', 'delivery_accept'])
        self.assertEqual(triggers('seq_3'), ['delivery_reject'])
        success = ("(Port('delivery_result_returnHome_disabled') == Enum('DeliveryResult','Success')"
                   " AND Port('delivery_started_returnHome') AND Port('delivery_started_disabled'))"
                   " OR (Port('delivery_result_first') == Enum('DeliveryResult','Success') AND Port('c_first_started'))")
        self.assertEqual(sequences['seq_2'].get('EntryCondition'), success)
        self.assertEqual(sequences['seq_3'].get('EntryCondition'), '!(' + success + ')')
        self.assertIn('Success', {e.get('Name') for e in RETAIL.find("Type[@TypeName='DeliveryResult']")})
        self.assertFalse([s.get('ExitScript') for s in sequences.values() if s.get('ExitScript')])

    def test_each_group_gets_one_delivery_with_the_tracked_descriptors(self):
        _, entry, found, _ = lowered()
        nodes = {n.get('Name'): n for n in entry.find('./Skald/Project/Nodes')}
        stem = 'lowered_delivery_handin_'
        self.assertEqual(nodes[stem + 'npc'].find('Asset').attrib, dict(Name='I_Soul', Alias='gm_soul_giver'))
        self.assertEqual(sorted(n for n in nodes if n.endswith('_handler')),
                         [stem + 'first_handler', stem + 'returnHome_disabled_handler'])
        pair, single = stem + 'returnHome_disabled_', stem + 'first_'
        self.assertEqual(constants(nodes[single + 'item_0']), dict(ItemClass=ITEMS['first'][0], Amount='70', MinimumHealth='0.5'))
        self.assertEqual(constants(nodes[single + 'filter_0']), dict(ItemClass=ITEMS['first'][0]))
        self.assertEqual(constants(nodes[pair + 'item_0']), dict(ItemClass=ITEMS['returnHome'][0], Amount='5', MinimumHealth='0.5'))
        self.assertEqual(constants(nodes[pair + 'item_1']), dict(ItemClass=ITEMS['disabled'][0], Amount='25'))
        self.assertEqual([(e.get('From'), e.get('To')) for e in nodes[pair + 'items'].findall('Edge')],
                         [(pair + 'item_0.ItemDescriptor', 'A'), (pair + 'item_1.ItemDescriptor', 'B')])
        self.assertEqual([(e.get('From'), e.get('To')) for e in nodes[pair + 'filters'].findall('Edge')],
                         [(pair + 'filter_0.ItemDescriptor', 'A'), (pair + 'filter_1.ItemDescriptor', 'B')])
        self.assertEqual(sorted(constants(nodes[pair + 'labels'])), ['A', 'B'])
        delivery = nodes[pair + 'delivery']
        self.assertEqual({e.get('To'): e.get('From') for e in delivery.findall('Edge')},
            dict(DeliveryDescriptors=pair + 'items.Array', PlayerInventoryFilters=pair + 'filters.Array',
                 Labels=pair + 'labels.Array', DeliveryInventory=stem + 'npc.Inventory'))
        self.assertEqual(constants(delivery), {})        # DeliveryMode stays at the retail default, Exactly
        for descriptor in (d for g in found['groups'] for d in g['descriptors']):
            tracked = constants(E.fromstring(lowered()[3][2]).find(
                ".//Function[@Name='lowered_track_" + descriptor['objective_id'] + "_0_descriptor']"))
            own = constants(nodes[stem + next(g['name'] for g in found['groups'] if descriptor in g['descriptors'])
                                  + '_item_' + str(next(g['descriptors'].index(descriptor) for g in found['groups']
                                                        if descriptor in g['descriptors']))])
            self.assertEqual(own, tracked)

    def test_one_started_group_takes_begin_accept_and_reject(self):
        _, entry, _, _ = lowered()
        nodes = {n.get('Name'): n for n in entry.find('./Skald/Project/Nodes')}
        pair, single = 'lowered_delivery_handin_returnHome_disabled_', 'lowered_delivery_handin_first_'
        both = nodes[pair + 'started_0']
        self.assertEqual((froms(both, 'A'), froms(both, 'B')),
                         ([QUEST + '.returnHome_Started'], [QUEST + '.disabled_Started']))
        for verb, port, target in (('begin', 'delivery_begin', 'BeginDelivery'), ('accept', 'delivery_accept', 'AcceptDelivery'),
                                   ('reject', 'delivery_reject', 'RejectDelivery')):
            # The script's `if` branch is the first gate; the `else` objectives follow on False.
            self.assertEqual(froms(nodes[pair + verb], 'Exec'), ['handin.' + port])
            self.assertEqual(froms(nodes[pair + verb], 'Condition'), [pair + 'started_0.bool'])
            self.assertEqual(froms(nodes[single + verb], 'Exec'), [pair + verb + '.False'])
            self.assertEqual(froms(nodes[single + verb], 'Condition'), [QUEST + '.first_Started'])
            self.assertEqual(froms(nodes[pair + 'handler'], target), [pair + verb + '.True'])
            self.assertEqual(froms(nodes[single + 'handler'], target), [single + verb + '.True'])
        instance = nodes['handin']
        self.assertEqual(froms(instance, 'delivery_result_first'), [single + 'handler.DeliveryResult'])
        self.assertEqual(froms(instance, 'delivery_result_returnHome_disabled'), [pair + 'handler.DeliveryResult'])
        self.assertEqual(froms(instance, 'delivery_started_disabled'), [QUEST + '.disabled_Started'])
        self.assertEqual(froms(instance, 'c_first_started'), [QUEST + '.first_Started'])

    def test_accept_completes_then_runs_the_source_effect_program(self):
        _, entry, _, _ = lowered()
        nodes = {n.get('Name'): n for n in entry.find('./Skald/Project/Nodes')}
        pair, single = 'lowered_delivery_handin_returnHome_disabled_', 'lowered_delivery_handin_first_'
        self.assertEqual(froms(nodes[pair + 'accepted'], 'Exec'), [pair + 'handler.OnAccept'])
        quest = nodes[QUEST]
        self.assertEqual(froms(quest, 'complete_returnHome'), [pair + 'accepted.A'])
        self.assertEqual(froms(quest, 'complete_disabled'), [pair + 'accepted.A'])
        self.assertEqual(froms(quest, 'complete_first'), [single + 'accepted.A'])
        # The cancel-if-completed chain keeps its order and now starts after the completion.
        self.assertEqual(froms(nodes['handin_effects_2_0'], 'Exec'), [pair + 'accepted.B', single + 'accepted.B'])
        self.assertEqual(froms(nodes['handin_effects_2_1'], 'Exec'), ['handin_effects_2_0.B'])
        self.assertEqual(froms(nodes['handin_effects_2_2'], 'Exec'), ['handin_effects_2_1.B'])
        self.assertEqual([froms(quest, 'cancel_' + o) for o in ('disabled', 'first', 'returnHome')],
                         [['handin_effects_2_0_gate.True'], ['handin_effects_2_1_gate.True'], ['handin_effects_2_2_gate.True']])
        self.assertFalse([e for n in nodes.values() for e in n.findall('Edge') if e.get('From') == 'handin.effects_2'])

    def test_every_emitted_node_and_port_exists_in_retail(self):
        for change in ({}, dict(join=('returnHome', 'disabled'), accept=JOINED, reject='!(' + JOINED + ')'),
                       dict(join=('returnHome', 'disabled'))):
            with self.subTest(change=change):
                self.retail_ports(lowered(**change)[1])

    def retail_ports(self, entry):
        container = entry.find('./Skald/Project/Nodes')
        emitted = {n.get('Name'): n for n in container if n.get('Name').startswith('lowered_delivery_')}
        self.assertEqual({n.tag for n in emitted.values()} - {'IfFunction'},
                         {'Function', 'ObjectProperties', 'MakeArray', 'ItemDeliveryHandler', 'If', 'TriggerSequence'})

        def definition(node):
            for d in RETAIL.findall('Definition'):
                if d.get('TypeName') != node.tag: continue
                if node.tag in ('Function', 'IfFunction') and d.get('MethodName') != node.get('MethodName'): continue
                if node.tag in ('Function', 'IfFunction') and d.get('DeclaringType') != node.get('DeclaringType'): continue
                if node.tag == 'ObjectProperties' and d.get('DeclaringType') != node.get('DeclaringType'): continue
                return d
            self.fail('No retail definition for ' + node.get('Name'))

        def has(node, port, direction):
            ports = [p for p in definition(node).findall('Port') if p.get('Direction') == direction]
            if any(p.get('Name') == port for p in ports): return True
            # Variadic ports are written A, B, C ... in retail files.
            return any(p.get('IsVariadic') == 'true' for p in ports) and port in string.ascii_uppercase
        for node in emitted.values():
            for child in node:
                target = child.get('Name') if child.tag in ('Constant', 'Asset') else child.get('To')
                self.assertTrue(has(node, target, 'In'), node.get('Name') + ' <- ' + str(target))
            if node.tag == 'MakeArray':
                self.assertIn(node.get('TypeT'), RETAIL_ARRAYS)
        for node in container:
            for e in node.findall('Edge'):
                source, _, port = e.get('From').partition('.')
                if source in emitted:
                    self.assertTrue(has(emitted[source], port, 'Out'), e.get('From'))

    def test_refusals_and_second_run(self):
        blob, entry, quest, tracking = staged()
        found = plan(blob, entry, quest, tracking, NPC)
        with self.assertRaises(ValueError): bind(blob, entry, quest, found, tracking, NPC, assets={'player'})
        with self.assertRaises(ValueError): bind(blob, entry, quest, dict(found, decision='d9'), tracking, NPC)
        new_blob, new_entry = bind(blob, entry, quest, found, tracking, NPC)
        self.assertNotIn(b'QuestSystem.', new_blob)
        again = plan(new_blob, new_entry, quest, tracking, NPC)
        self.assertEqual((again['sites'], again['pending']), ([], []))
        self.assertEqual(bind(new_blob, new_entry, quest, again, tracking, NPC), (new_blob, new_entry))
        # A fresh hand-in dialogue of the same name over an already lowered container is a collision.
        with self.assertRaises(ValueError): bind(blob, new_entry, quest, plan(blob, new_entry, quest, tracking, NPC), tracking, NPC)

    def test_an_aggregate_objective_is_proven_from_the_quest_graph(self):
        host = lambda join: E.fromstring(staged(join=join)[2]).find('./Skald/Quest')
        self.assertEqual(aggregates(host(('returnHome', 'disabled'))), {'second': frozenset(('returnHome', 'disabled'))})
        self.assertEqual(aggregates(host(('first', 'returnHome', 'disabled')))['second'],
                         frozenset(('first', 'returnHome', 'disabled')))
        # In the unchanged model returnHome waits for first and second but does not complete by itself.
        self.assertEqual(aggregates(host(None)), {})
        for damage in ('timer', 'second start', 'second completion', 'condition'):
            with self.subTest(damage=damage):
                quest = host(('returnHome', 'disabled'))
                nodes = {n.get('Name'): n for n in quest.find('Nodes')}
                if damage == 'timer':
                    nodes['complete_5_queued'].find("Constant[@Name='Duration']").set('Value', '1h')
                elif damage == 'second start':
                    E.SubElement(nodes['objective_5'], 'Edge', From='advance_4.True', To='SetStarted')
                elif damage == 'second completion':
                    E.SubElement(nodes['objective_5'], 'Edge', From='advance_4.True', To='SetCompleted')
                else:
                    nodes['ready_5_predecessors_0'].set('MethodName', 'math::boolean::Or')
                self.assertEqual(aggregates(quest), {})

    def test_the_outcome_may_test_a_group_through_its_aggregate(self):
        for accept in (JOINED, DONE):
            with self.subTest(accept=accept):
                found = plan(*staged(join=('returnHome', 'disabled'), accept=accept, reject='!(' + accept + ')'), NPC)
                self.assertEqual(found['pending'], [])
                self.assertEqual([g.get('aggregate') for g in found['groups']], ['second', None])
                self.assertEqual((found['accept_sequence'], found['reject_sequence']), ('seq_2', 'seq_3'))
                self.assertTrue(any('same trigger chain' in a for a in found['assumptions']))
                self.assertTrue(any('tracking predicate' in a for a in found['assumptions']))
        reason = ['outcome conditions are not "a delivered group is completed" and its negation']
        # Not an aggregate of the delivered group: nothing joins, or it also waits for another objective.
        for join in (None, ('first', 'returnHome', 'disabled'), ('returnHome',)):
            with self.subTest(join=join):
                found = plan(*staged(join=join, accept=JOINED, reject='!(' + JOINED + ')'), NPC)
                self.assertEqual([p['reason'] for p in found['pending']], reason)
        self.assertNotIn('aggregate', plan(*staged(), NPC)['groups'][0])
        self.assertEqual(len(plan(*staged(), NPC)['assumptions']), 5)

    def joined(self):
        return lowered(join=('returnHome', 'disabled'), accept=JOINED, reject='!(' + JOINED + ')')

    def test_members_of_an_aggregate_group_are_delivered_in_every_combination(self):
        _, _, found, _ = self.joined()
        group = found['groups'][0]
        self.assertEqual([(u['name'], u['objectives'], u['others']) for u in group['parts']], [
            ('returnHome_disabled', ['returnHome', 'disabled'], []),
            ('returnHome', ['returnHome'], ['disabled']), ('disabled', ['disabled'], ['returnHome'])])
        self.assertEqual([[d['objective'] for d in u['descriptors']] for u in group['parts']],
                         [['returnHome', 'disabled'], ['returnHome'], ['disabled']])
        self.assertNotIn('parts', found['groups'][1])
        self.assertEqual(found['completed_ports'], dict(returnHome_Completed='c_home_done', disabled_Completed='c_disabled_done'))
        # Without an aggregate the group stays one delivery, as before.
        plain = plan(*staged(), NPC)
        self.assertNotIn('parts', plain['groups'][0])
        self.assertNotIn('completed_ports', plain)

    def test_the_accepting_sequence_needs_the_part_that_completes_the_group(self):
        dialogue_root, _, _, _ = self.joined()
        sequences = {s.get('Name'): s for s in dialogue_root.iter('Sequence')}
        success = lambda port: "Port('delivery_result_" + port + "') == Enum('DeliveryResult','Success')"
        wanted = ('(' + success('returnHome_disabled') + " AND Port('delivery_started_returnHome') AND Port('delivery_started_disabled'))"
                  " OR (" + success('returnHome') + " AND Port('delivery_started_returnHome') AND Port('c_disabled_done'))"
                  " OR (" + success('disabled') + " AND Port('delivery_started_disabled') AND Port('c_home_done'))"
                  " OR (" + success('first') + " AND Port('c_first_started'))")
        self.assertEqual(sequences['seq_2'].get('EntryCondition'), wanted)
        self.assertEqual(sequences['seq_3'].get('EntryCondition'), '!(' + wanted + ')')
        ports = {p.get('Name'): (p.get('Direction'), p.get('Type')) for p in dialogue_root.iter('Port') if p.get('Direction')}
        for port in ('delivery_result_returnHome_disabled', 'delivery_result_returnHome', 'delivery_result_disabled'):
            self.assertEqual(ports[port], ('In', 'DeliveryResult'))

    def test_the_chain_opens_the_delivery_for_exactly_the_fillable_members(self):
        _, entry, _, _ = self.joined()
        nodes = {n.get('Name'): n for n in entry.find('./Skald/Project/Nodes')}
        stem = 'lowered_delivery_handin_'
        whole = stem + 'returnHome_disabled_'
        for member in ('returnHome', 'disabled'):
            has = nodes[whole + 'has_' + member + '_0']
            self.assertEqual((froms(has, 'A'), froms(has, 'B')),
                             ([QUEST + '.' + member + '_Started'], [QUEST + '.' + member + '_TrackedCompleted']))
            self.assertEqual(froms(nodes[whole + 'lacks_' + member], 'Value'), [whole + 'has_' + member + '_0.bool'])
            self.assertEqual(froms(nodes[whole + 'idle_' + member], 'Value'), [QUEST + '.' + member + '_Started'])
        none = nodes[whole + 'none_0']
        self.assertEqual((froms(none, 'A'), froms(none, 'B')), ([whole + 'lacks_returnHome.bool'], [whole + 'lacks_disabled.bool']))
        only = stem + 'returnHome_'
        exact, empty = nodes[only + 'exact_0'], nodes[only + 'empty_1']
        self.assertEqual((froms(exact, 'A'), froms(exact, 'B')), ([whole + 'has_returnHome_0.bool'], [whole + 'lacks_disabled.bool']))
        self.assertEqual(froms(nodes[only + 'empty_0'], 'A') + froms(nodes[only + 'empty_0'], 'B'),
                         [whole + 'none_0.bool', QUEST + '.returnHome_Started'])
        self.assertEqual(froms(empty, 'B'), [whole + 'idle_disabled.bool'])
        gate = nodes[only + 'started_0']
        self.assertEqual((gate.get('MethodName'), froms(gate, 'A'), froms(gate, 'B')),
                         ('math::boolean::Or', [only + 'exact_0.bool'], [only + 'empty_1.bool']))
        # One chain through every delivery: the whole pair, each member alone, then the other group.
        order = [whole, only, stem + 'disabled_', stem + 'first_']
        for verb in ('begin', 'accept', 'reject'):
            self.assertEqual(froms(nodes[order[0] + verb], 'Exec'), ['handin.delivery_' + verb])
            for before, after in zip(order, order[1:]):
                self.assertEqual(froms(nodes[after + verb], 'Exec'), [before + verb + '.False'])
        self.assertEqual(froms(nodes[only + 'begin'], 'Condition'), [only + 'started_0.bool'])
        self.assertEqual(froms(nodes[stem + 'first_begin'], 'Condition'), [QUEST + '.first_Started'])
        self.assertEqual(constants(nodes[only + 'item_0']), dict(ItemClass=ITEMS['returnHome'][0], Amount='5', MinimumHealth='0.5'))
        self.assertEqual(len([n for n in nodes if n.endswith('_handler')]), 4)

    def test_a_handed_in_part_is_accepted_whichever_sequence_follows(self):
        _, entry, _, _ = self.joined()
        nodes = {n.get('Name'): n for n in entry.find('./Skald/Project/Nodes')}
        stem = 'lowered_delivery_handin_'
        for part in ('returnHome_disabled_', 'returnHome_', 'disabled_'):
            g = stem + part
            settle, handler = nodes[g + 'settle'], nodes[g + 'handler']
            self.assertEqual((settle.tag, settle.get('TypeT'), settle.get('MethodName'), constants(settle)),
                             ('IfFunction', 'DeliveryResult', 'Control::Compare', dict(Op='Equals', ValueB='Success')))
            self.assertEqual((froms(settle, 'Exec'), froms(settle, 'ValueA')), ([g + 'reject.True'], [g + 'handler.DeliveryResult']))
            self.assertEqual(froms(handler, 'AcceptDelivery'), [g + 'accept.True', g + 'settle.True'])
            self.assertEqual(froms(handler, 'RejectDelivery'), [g + 'settle.False'])
        single = stem + 'first_'
        self.assertNotIn(single + 'settle', nodes)
        self.assertEqual(froms(nodes[single + 'handler'], 'RejectDelivery'), [single + 'reject.True'])

    def test_accept_completes_the_aggregate_before_the_effect_program(self):
        _, entry, found, _ = self.joined()
        nodes = {n.get('Name'): n for n in entry.find('./Skald/Project/Nodes')}
        stem = 'lowered_delivery_handin_'
        pair, single = stem + 'returnHome_disabled_', stem + 'first_'
        quest = nodes[QUEST]
        self.assertEqual(froms(quest, 'complete_returnHome'), [pair + 'accepted.A', stem + 'returnHome_accepted.A'])
        self.assertEqual(froms(quest, 'complete_disabled'), [pair + 'accepted.A', stem + 'disabled_accepted.A'])
        parts = [pair, stem + 'returnHome_', stem + 'disabled_']
        for g in parts:
            gate, finished = nodes[g + 'aggregate'], nodes[g + 'finished']
            self.assertEqual((gate.tag, froms(gate, 'Exec'), froms(gate, 'Condition')),
                             ('If', [g + 'accepted.B'], [QUEST + '.second_Started']))
            # The source effects of the accepting sequence run only once the whole group is in.
            self.assertEqual((froms(finished, 'Exec'), froms(finished, 'Condition')),
                             ([g + 'accepted.C'], [QUEST + '.second_Completed']))
        self.assertEqual(froms(quest, 'complete_second'), [g + 'aggregate.True' for g in parts])
        self.assertNotIn(single + 'aggregate', nodes)
        self.assertEqual(froms(nodes['handin_effects_2_0'], 'Exec'), [g + 'finished.True' for g in parts] + [single + 'accepted.B'])

    def test_the_lab_compares_a_delivery_result_by_member_name(self):
        from quest_lab import Unsupported
        from quest_lab.pure import compare, comparison
        node = E.fromstring('<IfFunction TypeT="DeliveryResult" MethodName="Control::Compare" DeclaringType="Control"/>')
        self.assertTrue(comparison(node))
        value = lambda a, op='Equals': compare(dict(Op=op, ValueA=a, ValueB='Success'), 'DeliveryResult')
        self.assertEqual([value('Success'), value('Canceled'), value(None), value('Canceled', 'NotEquals')],
                         [True, False, False, True])
        with self.assertRaises(Unsupported): value('Sucess')
        with self.assertRaises(Unsupported): value('Success', 'Less')

    def test_an_aggregate_of_one_member_stays_one_delivery(self):
        change = dict(scripts=(CALL % "'returnHome','disabled','first'",) * 2, pair=('action_home',), join=('disabled',))
        accept = "Port('c_first_done') OR Port('c_second_done') OR Port('c_home_done')"
        _, entry, found, _ = lowered(accept=accept, reject='!(' + accept + ')', **change)
        group = next(g for g in found['groups'] if g['objectives'] == ['disabled'])
        self.assertEqual(group['aggregate'], 'second')
        self.assertNotIn('parts', group)
        nodes = {n.get('Name'): n for n in entry.find('./Skald/Project/Nodes')}
        g = 'lowered_delivery_handin_disabled_'
        self.assertNotIn(g + 'settle', nodes)
        self.assertEqual(froms(nodes['handin_effects_2_0'], 'Exec')[1], g + 'accepted.C')

    def test_unlabelled_objective_omits_the_optional_labels(self):
        blob, entry, quest, tracking = staged()
        root = E.fromstring(quest)
        for objective in root.iter('Objective'):
            if objective.get('Name') == 'first': objective.remove(objective.find('LocalizedName'))
        quest = E.tostring(root)
        found = plan(blob, entry, quest, tracking, NPC)
        self.assertEqual([g['labelled'] for g in found['groups']], [True, False])
        _, new_entry = bind(blob, entry, quest, found, tracking, NPC)
        nodes = {n.get('Name'): n for n in E.fromstring(new_entry).find('./Skald/Project/Nodes')}
        self.assertNotIn('lowered_delivery_handin_first_labels', nodes)
        self.assertEqual(froms(nodes['lowered_delivery_handin_first_delivery'], 'Labels'), [])


if __name__ == '__main__':
    unittest.main()
