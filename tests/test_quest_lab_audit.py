import json
from pathlib import Path
import sys
import tempfile
import unittest
import xml.etree.ElementTree as E
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from quest_lab import Unsupported
from quest_lab.audit import audit, structural_checks, write
from quest_lab.graph import Graph
from quest_lab.source import Source
from quest_lab.pure import matches, descriptor, integer


def wrap(text):
    return ('<Database><Skald>' + text + '</Skald></Database>').encode()


class AuditTests(unittest.TestCase):
    def test_new_game_executing_a_small_prefix_does_not_imply_complete_coverage(self):
        s = Source.blobs({'x.xml': wrap('''<Project Name="P"><Nodes><GameStart Name="start"/>
          <State Name="requested" TypeT="bool"><Constant Name="DefaultValue" Value="false"/>
          <Edge From="start.OnStart" To="SetTrue"/></State><NativeEngine Name="waiting"/>
          </Nodes></Project>''')})
        result = audit(s)['new_game'][0]
        self.assertEqual(result['status'], 'PARTIAL_UNSUPPORTED')
        self.assertEqual(result['probe_status'], 'EXECUTED')
        self.assertEqual(result['visited_nodes'], 1)
        self.assertEqual(result['nodes'], 3)
        self.assertFalse(result['native_runtime_verified'])

    def test_equivalent_definition_copies_ignore_formatting_and_empty_includes(self):
        s = Source.blobs({'a.xml': wrap('<Module Name="M"><Nodes/></Module>'),
                          'b.xml': wrap('<Module Name="M">\n<Nodes />\n<Definitions/>\n</Module>')})
        self.assertEqual(s.definition('M')[0], 'a.xml')
        s.add('c.xml', wrap('<Module Name="M"><Nodes><Trace Name="different"/></Nodes></Module>'))
        with self.assertRaises(Unsupported): s.definition('M')

    def test_boolean_iffunction_uses_explicit_constant_ports(self):
        s = Source.blobs({'x.xml': wrap('''<Module Name="M"><Ports>
          <ConstantPort Name="ready" Direction="In" Type="bool" Value="false"/>
          <Port Name="go" Direction="In" Type="trigger"/>
          <Port Name="done" Direction="Out" Type="trigger"/></Ports><Nodes>
          <IfFunction Name="gate" MethodName="math::boolean::And"><Edge From="go" To="Exec"/>
          <Edge From="ready" To="A"/><Constant Name="B" Value="true"/></IfFunction>
          <Output Name="out"><Edge From="gate.True" To="done"/></Output></Nodes></Module>''')})
        g = Graph(s, 'M')
        self.assertEqual(g.unsupported, [])
        g.fire('go'); self.assertEqual(g.events['output.done'], 0)
        g.set_inputs({'ready': True}); g.fire('go')
        self.assertEqual(g.events['output.done'], 1)

    def test_audit_distinguishes_missing_source_from_executed_local_probe(self):
        s = Source.blobs({'x.xml': wrap('''<Quest Name="Present"><Ports>
          <Port Name="start" Direction="In" Type="trigger"/></Ports><Nodes>
          <State Name="progress" TypeT="bool"><Constant Name="DefaultValue" Value="false"/>
          <Edge From="start" To="SetTrue"/></State></Nodes></Quest>''')})
        r = audit(s, [{'quest_name': n, 'quest_id': str(i), 'group': 'Main'}
                      for i, n in enumerate(['Present', 'Missing'])])
        self.assertEqual(r['quests'][0]['status'], 'LOCAL_PROBES_EXECUTED')
        self.assertEqual({x['name']: x['status'] for x in r['source_inventory']},
                         {'Present': 'DEFINITION_PRESENT', 'Missing': 'NOT_PRESENT_IN_PACKAGE'})
        self.assertFalse(r['quests'][0]['native_runtime_verified'])
        with tempfile.TemporaryDirectory() as d:
            write(r, d)
            self.assertIn('Missing', (Path(d)/'audit.html').read_text(encoding='utf-8'))
            self.assertEqual(len(json.loads((Path(d)/'audit.json').read_text())['quests']), 1)

    def test_probes_restore_pristine_state_after_an_unsupported_callback(self):
        s = Source.blobs({'x.xml': wrap('''<Quest Name="Q"><Ports>
          <Port Name="a_bad" Direction="In" Type="trigger"/>
          <Port Name="z_good" Direction="In" Type="trigger"/></Ports><Nodes>
          <If Name="bad"><Edge From="a_bad" To="Exec"/><Edge From="engine.value" To="Condition"/></If>
          <Engine Name="engine"/><State Name="state" TypeT="bool"><Constant Name="DefaultValue" Value="false"/>
          <Edge From="z_good" To="SetTrue"/></State></Nodes></Quest>''')})
        r = audit(s)['quests'][0]
        self.assertEqual(r['status'], 'PARTIAL_UNSUPPORTED')
        self.assertEqual([x['status'] for x in r['probes']], ['UNSUPPORTED', 'EXECUTED'])
        self.assertTrue(r['probes'][1]['states']['state'])

    def test_missing_node_is_fault_but_implicit_host_port_is_not(self):
        s = Source.blobs({'x.xml': wrap('''<Level Name="L"><Nodes>
          <Trace Name="T"><Edge From="OnWake" To="Exec"/><Edge From="missing.Bool" To="Value"/></Trace>
          </Nodes></Level>''')})
        r = structural_checks(s)
        self.assertEqual(len(r['findings']), 1)
        self.assertEqual(r['findings'][0]['source'], 'missing.Bool')
        self.assertEqual(len(r['unresolved_interfaces']), 1)

    def test_counted_inventory_does_not_complete_with_wrong_or_insufficient_items(self):
        target = descriptor({'ItemClass':'fixture-item', 'Amount':10})
        for items, expected in [({},False), ({'other':10},False), ({'fixture-item':9},False),
                                ({'fixture-item':10},True), ({'fixture-item':11},True)]:
            self.assertEqual(matches({'ItemDescriptor':target,'InputItems':items}), expected)
        with self.assertRaises(Unsupported):
            matches({'ItemDescriptor':dict(target, quality=1), 'InputItems':{'fixture-item':10}})
        with self.assertRaises(Unsupported):
            matches({'ItemDescriptor':target, 'InputItems':{'fixture-item':-1}})

    def test_pure_inventory_binding_executes_actual_graph_nodes(self):
        s = Source.blobs({'x.xml': wrap('''<Module Name="M"><Ports>
          <Port Name="items" Direction="In" Type="InventoryItems"/>
          <Port Name="ready" Direction="Out" Type="bool"/></Ports><Nodes>
          <Function Name="descriptor" DeclaringType="wh::entitymodule" MethodName="wh::entitymodule::CreateItemClassDescriptor">
          <Constant Name="ItemClass" Value="fixture-item"/><Constant Name="Amount" Value="2"/></Function>
          <MemberFunction Name="match" DeclaringType="wh::entitymodule::ItemDescriptor" MethodName="FullyMatchesItems">
          <Edge From="descriptor.ItemDescriptor" To="ItemDescriptor"/><Edge From="items" To="InputItems"/></MemberFunction>
          <Output Name="Output"><Edge From="match.bool" To="ready"/></Output></Nodes></Module>''')})
        g = Graph(s, 'M'); self.assertEqual(g.unsupported, [])
        with self.assertRaises(Unsupported): g.value('output.ready')
        g.set_inputs({'items':{'fixture-item':1}}); self.assertFalse(g.value('output.ready'))
        g.set_inputs({'items':{'fixture-item':2}}); self.assertTrue(g.value('output.ready'))

    def test_numeric_conversions_reject_nonfinite_and_out_of_range_values(self):
        self.assertEqual(integer(-1.9), -1)
        for value, unsigned in [(float('nan'),False), (float('inf'),False), (2**31,False),(-1,True),(True,False)]:
            with self.assertRaises(Unsupported): integer(value, unsigned)

    def test_native_trigger_fanin_is_not_misreported_as_invalid_data_wiring(self):
        s = Source.blobs({'x.xml': wrap('''<Module Name="M"><Ports>
          <Port Name="a" Direction="In" Type="trigger"/><Port Name="b" Direction="In" Type="trigger"/>
          </Ports><Nodes><NativeMessage Name="message"><Edge From="a" To="Exec"/>
          <Edge From="b" To="Exec"/></NativeMessage></Nodes></Module>''')})
        unknown = Graph(s, 'M')
        self.assertTrue(unknown.unsupported)
        self.assertEqual(unknown.report()['unresolved_native_bindings'],
                         [dict(node='message',port='Exec',sources=['a','b'])])
        with self.assertRaisesRegex(Unsupported, 'Native input wiring is not modeled'): unknown.fire('a')
        native = wrap('''<Module Name="M"><Ports><Port Name="a" Direction="In" Type="trigger"/>
          <Port Name="b" Direction="In" Type="trigger"/></Ports><Nodes>
          <Function Name="door" MethodName="native::OpenDoor"><Edge From="a" To="Exec"/>
          <Edge From="b" To="Exec"/></Function></Nodes></Module>''')
        graph = Graph(Source.blobs({'x.xml':native}), 'M')
        self.assertTrue(graph.unsupported)
        with self.assertRaisesRegex(Unsupported, 'explicit interface contract'): graph.fire('a')

    def test_source_dry_run_uses_retail_reader_and_accounts_for_absent_graph(self):
        from quest_lab.demo import model
        from quest_lab.source_audit import run
        m = model()
        m['tables']['quest']['rows'].append(dict(quest_id='43',quest_name='missing_quest',group='Test',is_activated='False'))
        graph = E.Element('Graph'); nodes = E.SubElement(graph, 'Nodes'); edges = E.SubElement(graph, 'Edges')
        for identity, spec in m['graph']['nodes'].items():
            node = E.SubElement(nodes,'Node',Id=identity,**spec['attributes'])
            for child in spec.get('payload', []): E.SubElement(node,child['op'],**child['attributes'])
            if identity=='1': E.SubElement(node,'Inputs',Name=m['quest'])
        for edge in m['graph']['edges']: E.SubElement(edges,'Edge',**edge)
        with tempfile.TemporaryDirectory() as d:
            data = Path(d)/'Data'; data.mkdir()
            with zipfile.ZipFile(data/'Tables.pak','w') as z:
                for name, values in m['tables'].items():
                    root=E.Element('root'); table=E.SubElement(root,'table',name=name); rows=E.SubElement(table,'rows')
                    for row in values['rows']: E.SubElement(rows,'row',**row)
                    z.writestr('Libs/Tables/quest/'+name+'.xml',E.tostring(root))
            with zipfile.ZipFile(data/'GameData.pak','w') as z:
                z.writestr('Libs/quests/flowgraphs/example_quest.xml',E.tostring(graph))
            report=run(d)
        self.assertEqual(len(report['quests']),2)
        statuses={q['name']:q['status'] for q in report['quests']}
        self.assertEqual(statuses['example_quest'],'LOCAL_STATE_PROBES_EXECUTED')
        self.assertEqual(statuses['missing_quest'],'SOURCE_GRAPH_ABSENT')
        self.assertGreater(report['probes'],0)


if __name__ == '__main__': unittest.main()
