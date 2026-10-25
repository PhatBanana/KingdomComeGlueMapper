from pathlib import Path
import sys
import unittest
import xml.etree.ElementTree as E

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from quest_lab import Unsupported
from quest_lab.graph import Graph
from quest_lab.pure import compare, operation
from quest_lab.source import Source


def source(xml):
    return Source.blobs({'test.xml': ('<Database><Skald>' + xml + '</Skald></Database>').encode()})


class ValueTests(unittest.TestCase):
    def test_native_round_only_accepts_values_whose_rounding_is_unambiguous(self):
        op=operation(E.Element('Function',MethodName='wh::conceptmodule::math::Round',DeclaringType='wh::conceptmodule::math'))[2]
        for value in (-12,0,99,125.0): self.assertEqual(op({'Number':value}),float(value))
        for value in (0.5,1.25,-1.5,float('inf'),True):
            with self.assertRaises(Unsupported):op({'Number':value})

    def test_currency_conversion_operations_reject_unknown_overflow_and_zero_division(self):
        def op(method, declaring='math::conversion'):
            return operation(E.Element('Function', MethodName=method, DeclaringType=declaring))[2]
        to_int = op('math::conversion::ToInt(uint)')
        to_float = op('math::conversion::ToFloat(int)')
        divide = op('wh::conceptmodule::math::DivideFloat', 'wh::conceptmodule::math')
        multiply = op('wh::conceptmodule::math::MultiplyFloat', 'wh::conceptmodule::math')
        self.assertEqual(divide({'A':to_float({'int':to_int({'uint':125})}), 'B':10}), 12.5)
        self.assertEqual(multiply({'A':2.5,'B':10}),25.0)
        for v in (-1, 2**31, True, 1.5):
            with self.assertRaises(Unsupported): to_int({'uint':v})
        with self.assertRaises(Unsupported): divide({'A':1,'B':0})
        with self.assertRaises(Unsupported): multiply({'A':float('inf'),'B':2})

    def test_both_compare_node_forms_use_native_operator_names_and_equal_boundaries(self):
        xml = '''<Module Name="M"><Ports><Port Name="a" Type="float" Direction="In"/>
        <Port Name="b" Type="float" Direction="In"/><Port Name="go" Type="trigger" Direction="In"/>
        <Port Name="yes" Type="trigger" Direction="Out"/></Ports><Nodes>
        <Function Name="value" DeclaringType="Control" MethodName="Control::Compare" TypeT="float">
        <Constant Name="Op" Value="LessEquals"/><Edge From="a" To="ValueA"/><Edge From="b" To="ValueB"/></Function>
        <IfFunction Name="branch" DeclaringType="Control" MethodName="Control::Compare" TypeT="float">
        <Constant Name="Op" Value="GreaterEquals"/><Edge From="a" To="ValueA"/><Edge From="b" To="ValueB"/>
        <Edge From="go" To="Exec"/></IfFunction><Output Name="out"><Edge From="branch.True" To="yes"/></Output>
        </Nodes></Module>'''
        g = Graph(source(xml), 'M'); self.assertEqual(g.unsupported, [])
        for a, b, expected in [(0, 1, True), (1, 1, True), (2, 1, False)]:
            g.set_inputs({'a': a, 'b': b})
            self.assertEqual(g.value('value.bool'), expected)
            before = g.events['output.yes']; g.fire('go')
            self.assertEqual(g.events['output.yes'] - before, int(a >= b))

    def test_comparison_rejects_implicit_coercion_and_unknown_native_types(self):
        for typ, a, b, op in [('float', True, 1, 'Equals'), ('float', float('nan'), 0, 'Less'),
                             ('int', 1.0, 1, 'Equals'), ('uint', -1, 0, 'Less'),
                             ('int', 2**31, 1, 'Greater'), ('bool', True, 1, 'Equals'),
                             ('string', 'a', 'b', 'Less'), ('float', 1, 2, 'LessOrEqual')]:
            with self.subTest(typ=typ, op=op), self.assertRaises(Unsupported):
                compare(dict(ValueA=a, ValueB=b, Op=op), typ)
        for typ in ('wh::framework::TimeOfDay', 'NativeEnum'):
            g = Graph(source(f'''<Module Name="M"><Nodes><Function Name="c" TypeT="{typ}"
                DeclaringType="Control" MethodName="Control::Compare"><Constant Name="Op" Value="Equals"/>
                <Constant Name="ValueA" Value="same"/><Constant Name="ValueB" Value="same"/>
                </Function></Nodes></Module>'''), 'M')
            self.assertTrue(g.unsupported)
            with self.assertRaises(Unsupported): g.value('c.bool')

    def test_reference_comparison_uses_explicit_identity_not_object_or_display_name(self):
        typ = 'wh::rpgmodule::I_Soul*'
        for a, b, expected in [('actor-a','actor-a',True), ('actor-a','actor-b',False),
                               ('actor-a',None,False), (None,None,True)]:
            self.assertEqual(compare(dict(ValueA=a, ValueB=b, Op='Equals'), typ), expected)
        for a in ({'name':'Henry'}, '', 42):
            with self.assertRaises(Unsupported): compare(dict(ValueA=a, ValueB='actor-a', Op='Equals'), typ)

    def test_exact_comparison_values_and_wrong_declaring_type(self):
        for typ, a, b, op, expected in [('int', 2, 1, 'Greater', True), ('int', 1, 1, 'Less', False),
                ('bool', False, True, 'NotEquals', True), ('string', 'one', 'One', 'Equals', False)]:
            self.assertEqual(compare(dict(ValueA=a, ValueB=b, Op=op), typ), expected)
        g = Graph(source('''<Module Name="M"><Nodes><Function Name="c" TypeT="float"
            DeclaringType="Other" MethodName="Control::Compare"/></Nodes></Module>'''), 'M')
        self.assertTrue(g.unsupported)

    def test_nested_instance_assets_override_defaults_and_remain_independent(self):
        child = '''<Module Name="Child"><Ports><AssetPort Name="who" Direction="In" Type="Souls" Alias="player"/>
          <Port Name="target" Direction="Out" Type="Souls"/></Ports><Nodes><Output Name="out">
          <Edge From="who" To="target"/></Output></Nodes></Module>'''
        parent = '''<Module Name="Parent"><Ports><Port Name="from_parent" Direction="In" Type="Souls"/></Ports><Nodes>
          <Child Name="a"><Asset Name="who" Alias="keeper"/></Child>
          <Child Name="b"><Asset Name="who" Alias="guard"/></Child><Child Name="defaults"/>
          <Child Name="connected"><Edge From="from_parent" To="who"/></Child></Nodes></Module>'''
        g = Graph(source(child + parent), 'Parent', assets={'player':['player-id'], 'keeper':['keeper-id'], 'guard':['guard-id']})
        self.assertEqual(g.unsupported, [])
        for name, expected in [('a','keeper-id'), ('b','guard-id'), ('defaults','player-id')]:
            self.assertEqual(g.value(name+'.target'), [expected])
        g.set_inputs({'from_parent':['external-id']}); self.assertEqual(g.value('connected.target'), ['external-id'])
        g = Graph(source(child + parent), 'Parent', assets={'player':['player-id']})
        with self.assertRaisesRegex(Unsupported, 'keeper'): g.value('a.target')

    def test_child_binding_conflicts_are_errors_not_silent_overrides(self):
        child = '''<Module Name="Child"><Ports><AssetPort Name="who" Direction="In" Type="Souls" Alias="player"/>
          </Ports><Nodes/></Module>'''
        for bindings in ['<Asset Name="who" Alias="a"/><Asset Name="who" Alias="b"/>',
                '<Edge From="input" To="who"/><Asset Name="who" Alias="a"/>',
                '<Constant Name="who" Value="a"/><Asset Name="who" Alias="b"/>',
                '<Edge From="input" To="who"/><Constant Name="who" Value="a"/>']:
            with self.subTest(bindings=bindings), self.assertRaisesRegex(ValueError, 'Multiple'):
                Graph(source(child + '<Module Name="M"><Nodes><Child Name="child">' + bindings + '</Child></Nodes></Module>'), 'M')


if __name__ == '__main__': unittest.main()
