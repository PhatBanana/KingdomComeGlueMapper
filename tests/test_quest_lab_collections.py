from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from quest_lab import Unsupported
from quest_lab.graph import Graph
from quest_lab.source import Source


def source(nodes, ports='', types=''):
    return Source.blobs({'x.xml':f'<Database><Skald><Module Name="M"><Types>{types}</Types><Ports>{ports}</Ports><Nodes>{nodes}</Nodes></Module></Skald></Database>'.encode()})


class CollectionTests(unittest.TestCase):
    def test_array_order_duplicates_membership_and_empty_array(self):
        nodes='''<MakeArray Name="members" TypeT="wh::rpgmodule::Souls"><Asset Name="C" Alias="a"/>
          <Asset Name="A" Alias="a"/><Asset Name="B" Alias="b"/></MakeArray>
          <MakeArray Name="empty" TypeT="wh::rpgmodule::Souls"/>
          <ContainsElement Name="contains" TypeT="wh::rpgmodule::Souls"><Edge From="members.Array" To="Array"/>
          <Edge From="who" To="Value"/></ContainsElement>'''
        g=Graph(source(nodes,'<Port Name="who" Type="string" Direction="In"/>'),'M',assets={'a':'actor-a','b':'actor-b'})
        self.assertEqual(g.unsupported,[])
        self.assertEqual(g.value('members.Array'),['actor-a','actor-b','actor-a']);self.assertEqual(g.value('empty.Array'),[])
        for who,expected in [('actor-a',True),('actor-b',True),('actor-c',False)]:
            g.set_inputs({'who':who});self.assertEqual(g.value('contains.Result'),expected)

    def test_array_inputs_require_identities_and_contiguous_ports(self):
        for value in (None,42,['nested'],{'id':'object'}):
            g=Graph(source('<MakeArray Name="a" TypeT="wh::rpgmodule::Souls"><Asset Name="A" Alias="who"/></MakeArray>'),'M',assets={'who':value})
            with self.subTest(value=value),self.assertRaises(Unsupported):g.value('a.Array')
        g=Graph(source('<MakeArray Name="a" TypeT="wh::rpgmodule::Souls"><Constant Name="B" Value="x"/></MakeArray>'),'M')
        self.assertTrue(g.unsupported)
        g=Graph(source('<MakeArray Name="a" TypeT="Unknown"/>'),'M');self.assertTrue(g.unsupported)

    def test_switch_selects_lazily_and_matches_boolean_types_exactly(self):
        nodes='''<Switch Name="choose" TypeT="bool" ValueTypes="float float" SwitchValues="true false">
        <Edge From="condition" To="Switch"/><Constant Name="trueValue1" Value="10"/><Constant Name="trueValue2" Value="20"/>
        <Edge From="unbound" To="falseValue1"/><Constant Name="falseValue2" Value="30"/>
        <Constant Name="DefaultValue1" Value="-1"/><Constant Name="DefaultValue2" Value="-2"/></Switch>'''
        ports='<Port Name="condition" Type="bool" Direction="In"/><Port Name="unbound" Type="float" Direction="In"/>'
        g=Graph(source(nodes,ports),'M');self.assertEqual(g.unsupported,[])
        g.set_inputs({'condition':True});self.assertEqual(g.value('choose.Value1'),10);self.assertEqual(g.value('choose.Value2'),20)
        g.set_inputs({'condition':False});self.assertEqual(g.value('choose.Value2'),30)
        with self.assertRaises(Unsupported):g.value('choose.Value1')
        with self.assertRaises(Unsupported):g.set_inputs({'condition':1})

    def test_switch_enum_mapping_defaults_and_wrong_value_type(self):
        types='<Type TypeName="Phase"><StateTypeEnumeration Name="One"/><StateTypeEnumeration Name="Two"/></Type>'
        nodes='''<Switch Name="choose" TypeT="int" ValueTypes="Phase" SwitchValues="0">
        <Edge From="index" To="Switch"/><Constant Name="0Value1" Value="One"/><Constant Name="DefaultValue1" Value="Two"/></Switch>'''
        ports='<Port Name="index" Type="int" Direction="In"/>'
        g=Graph(source(nodes,ports,types),'M');self.assertEqual(g.unsupported,[])
        for index,expected in [(0,'One'),(1,'Two'),(-1,'Two')]:
            g.set_inputs({'index':index});self.assertEqual(g.value('choose.Value1'),expected)
        bad=Graph(source(nodes.replace('Value="One"','Value="Unknown"'),ports,types),'M')
        bad.set_inputs({'index':0})
        with self.assertRaises(Unsupported):bad.value('choose.Value1')

    def test_malformed_switch_or_duplicate_data_drivers_are_not_hidden(self):
        base='<Switch Name="s" TypeT="bool" ValueTypes="float" SwitchValues="true"><Constant Name="Switch" Value="true"/><Constant Name="trueValue1" Value="1"/><Constant Name="DefaultValue1" Value="0"/>{}</Switch>'
        with self.assertRaisesRegex(ValueError,'Multiple'):
            Graph(source(base.format('<Constant Name="trueValue1" Value="2"/>')),'M')
        with self.assertRaisesRegex(ValueError,'Multiple'):
            Graph(source(base.format('<Edge From="x" To="trueValue1"/>')),'M')
        with self.assertRaisesRegex(ValueError,'Duplicate switch'):
            Graph(source(base.format('').replace('SwitchValues="true"','SwitchValues="true true"')),'M')
        g=Graph(source(base.format('').replace('<Constant Name="DefaultValue1" Value="0"/>','')),'M')
        self.assertTrue(g.unsupported)
