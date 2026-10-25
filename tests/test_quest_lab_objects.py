import copy
import json
from pathlib import Path
import sys
import unittest
import operator
import xml.etree.ElementTree as E

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from quest_lab import Unsupported
from quest_lab.graph import Graph
from quest_lab.objects import SOUL, COMBAT, INVENTORY
from quest_lab.runner import Runner
from quest_lab.source import Source


def source(nodes, ports=''):
    return Source.blobs({'x.xml': f'<Database><Skald><Module Name="M"><Ports>{ports}</Ports><Nodes>{nodes}</Nodes></Module></Skald></Database>'.encode()})


NODES = '''<ObjectProperties Name="soul" DeclaringType="wh::rpgmodule::I_Soul"><Edge From="actor" To="I_Soul"/></ObjectProperties>
<MemberFunction Name="money" DeclaringType="wh::entitymodule::Inventory" MethodName="GetMoney">
<Edge From="soul.Inventory" To="Inventory"/></MemberFunction>'''
PORTS = '<Port Name="actor" Direction="In" Type="wh::rpgmodule::I_Soul*"/>'


def balance(amount):
    return {INVENTORY: {'queries':[dict(method='GetMoney', arguments={}, result=amount)]}}


def objects():
    return {'alice':{SOUL:{'properties':{'Inventory':'bag-a'}}},
            'bob':{SOUL:{'properties':{'Inventory':'bag-b'}}}, 'bag-a':balance(99), 'bag-b':balance(101)}


class ObjectTests(unittest.TestCase):
    def test_production_importer_inventory_conditions_follow_bound_actor_for_all_operators(self):
        from campaign_dialogue_conditions import QuestConditions
        from campaign_dialogue_runtime import inventory_predicate
        item='00000000-0000-0000-0000-000000000001'
        ops={'>':operator.gt, '>=':operator.ge, '<':operator.lt, '<=':operator.le, '==':operator.eq, '!=':operator.ne}
        for symbol, predicate in ops.items():
            for amount in (0,1,10):
                compiler=QuestConditions([],registered_items=[item],participant_assets={'buyer':'subject'})
                compiler.compile(f"CountOfActorItems('{item}')['buyer'] {symbol} {amount}")
                nodes=E.Element('Nodes'); ref=inventory_predicate(nodes,'check',next(iter(compiler.bindings.values())))
                content=''.join(E.tostring(n,encoding='unicode') for n in nodes)
                records=objects();records['bag-a']={INVENTORY:{'queries':[dict(method='Items',arguments={},result={item:0})]}}
                # The other actor holds many items; they cannot satisfy this actor's condition.
                records['bag-b']={INVENTORY:{'queries':[dict(method='Items',arguments={},result={item:100})]}}
                g=Graph(source(content),'M',assets={'subject':'alice'},objects=records)
                self.assertEqual(g.unsupported,[])
                for count in (0,1,9,10,11):
                    with self.subTest(operator=symbol,amount=amount,count=count):
                        g.objects.replace('bag-a',{INVENTORY:{'queries':[dict(method='Items',arguments={},result={item:count})]}})
                        self.assertEqual(g.value(ref),predicate(count,amount))

    def test_actor_inventory_chain_follows_actual_binding_and_logs_reads(self):
        g = Graph(source(NODES, PORTS), 'M', objects=objects()); self.assertEqual(g.unsupported, [])
        for actor, expected in [('alice',99), ('bob',101), ('alice',99)]:
            g.set_inputs({'actor':actor}); self.assertEqual(g.value('money.Amount'),expected)
        reads=[r for r in g.trace if r['kind']=='object_read']
        self.assertEqual([r['receiver'] for r in reads],['alice','bag-a','bob','bag-b','alice','bag-a'])
        self.assertTrue(all(r['boundary']=='explicit_engine_observation' for r in reads))

    def test_absent_null_wrong_type_or_missing_property_never_defaults_to_zero(self):
        for actor, records in [('absent',objects()), ('alice',{'alice':{INVENTORY:{}}}),
                ('alice',{'alice':{SOUL:{}}}), ('alice',{'alice':{SOUL:{'properties':{'Inventory':None}}}})]:
            g=Graph(source(NODES,PORTS),'M',objects=records); g.set_inputs({'actor':actor})
            with self.subTest(records=records), self.assertRaises(Unsupported): g.value('money.Amount')
        g=Graph(source(NODES,PORTS),'M')
        self.assertTrue(any('object snapshots' in u['reason'] for u in g.unsupported))

    def test_queries_key_on_context_and_argument_and_cannot_reuse_other_observations(self):
        nodes='''<MemberFunction Name="stat" DeclaringType="wh::rpgmodule::I_Soul" MethodName="GetDerivedStat">
        <Edge From="actor" To="Soul"/><Constant Name="DerivedStat" Value="rch"/><Edge From="context" To="Context"/></MemberFunction>'''
        ports=PORTS+'<Port Name="context" Direction="In" Type="wh::rpgmodule::I_Soul*"/>'
        q=lambda context,value:dict(method='GetDerivedStat',arguments={'DerivedStat':'rch','Context':context},result=value)
        g=Graph(source(nodes,ports),'M',objects={'alice':{SOUL:{'queries':[q('bob',3),q('charlie',7)]}}})
        for context,expected in [('bob',3),('charlie',7)]:
            g.set_inputs({'actor':'alice','context':context});self.assertEqual(g.value('stat.Value'),expected)
        g.set_inputs({'context':'unknown'})
        with self.assertRaisesRegex(Unsupported,'exact query observation'):g.value('stat.Value')

    def test_query_result_types_and_duplicates_are_rejected_before_use(self):
        for bad in [-1,1.5,True]:
            with self.subTest(value=bad), self.assertRaises(Unsupported): Graph(source(NODES,PORTS),'M',objects={'bag':balance(bad)})
        duplicate=balance(99);duplicate[INVENTORY]['queries']*=2
        with self.assertRaisesRegex(ValueError,'Duplicate'): Graph(source(NODES,PORTS),'M',objects={'bag':duplicate})
        with self.assertRaisesRegex(ValueError,'Unmodeled native query'):
            Graph(source(NODES,PORTS),'M',objects={'soul':{SOUL:{'queries':[dict(method='Kill',arguments={},result=True)]}}})

    def test_snapshot_changes_are_explicit_atomic_and_replayed(self):
        g=Graph(source(NODES,PORTS),'M',objects=objects());g.set_inputs({'actor':'alice'})
        saved=json.loads(json.dumps(g.snapshot()))
        g.objects.replace('bag-a',balance(75));self.assertEqual(g.value('money.Amount'),75)
        before=copy.deepcopy(g.objects.records)
        with self.assertRaises(Unsupported):g.objects.replace('bag-a',balance(-1))
        self.assertEqual(g.objects.records,before)
        g.restore(saved);self.assertEqual(g.value('money.Amount'),99)
        other=objects();other['bag-a']=balance(10)
        with self.assertRaisesRegex(ValueError,'mismatch'):Graph(source(NODES,PORTS),'M',objects=other).restore(saved)
        with self.assertRaises(ValueError):g.objects.replace('new',balance(2))

    def test_old_contract_can_model_boundary_but_cannot_override_snapshot_queries(self):
        contract={'soul':dict(reason='explicit legacy boundary',inputs={'I_Soul':'value'},outputs={'Inventory':'string'})}
        with self.assertRaisesRegex(ValueError,'Cannot replace interpreted'):
            Graph(source(NODES,PORTS),'M',objects=objects(),contracts=contract)

    def test_query_outputs_cannot_be_injected_and_snapshot_action_runs_in_scenario(self):
        s=dict(schema=1,entry='M',objects=objects(),inputs={'actor':'alice'},steps=[
            dict(action='assert',values={'money.Amount':99}),dict(action='save',name='before'),
            dict(action='object_snapshot',identity='bag-a',facets=balance(60)),
            dict(action='assert',values={'money.Amount':60}),dict(action='load',name='before'),
            dict(action='assert',values={'money.Amount':99})])
        r=Runner(s,source=source(NODES,PORTS)).run();self.assertEqual(r['status'],'PASS',r['error'])
        self.assertFalse(r['native_runtime_verified'])
        g=Graph(source(NODES,PORTS),'M',objects=objects())
        with self.assertRaises(ValueError):g.set_inputs({'money.Amount':100000})

    def test_wrong_declaring_type_or_extra_input_is_not_silently_ignored(self):
        for nodes in [NODES.replace('wh::entitymodule::Inventory','other::Inventory'),
                      NODES.replace('<Edge From="soul.Inventory" To="Inventory"/>','<Edge From="soul.Inventory" To="Inventory"/><Constant Name="Extra" Value="1"/>')]:
            self.assertTrue(Graph(source(nodes,PORTS),'M',objects=objects()).unsupported)

    def test_count_only_inventory_returns_independent_value(self):
        nodes='''<MemberFunction Name="items" DeclaringType="wh::entitymodule::Inventory" MethodName="Items">
        <Asset Name="Inventory" Alias="bag"/></MemberFunction>'''
        g=Graph(source(nodes),'M',assets={'bag':'bag-id'},objects={'bag-id':{INVENTORY:{'queries':[
            dict(method='Items',arguments={},result={'class-id':2})]}}})
        result=g.value('items.Items');result['class-id']=0
        self.assertEqual(g.value('items.Items'),{'class-id':2})
