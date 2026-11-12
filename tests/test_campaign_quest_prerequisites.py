import copy
from pathlib import Path
import sys
import unittest
import xml.etree.ElementTree as E

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from campaign_dialogue_runtime import attach_dialogue
from campaign_quest_prerequisites import assumed_prerequisites, host, register, stub
from test_campaign_dialogue_presentation import model as dialogue

ENTRY = (b'<Database><Skald><Level Name="level"><Definitions/><Nodes>'
         b'<existing Name="existing"/></Nodes></Level></Skald></Database>')


def defaults(blob):
    root = E.fromstring(blob).find('Skald/Module')
    return {s.get('Name'): s.find("Constant[@Name='DefaultValue']").get('Value')
            for s in root.findall('Nodes/State')}


class PrerequisiteTests(unittest.TestCase):
    def test_stub_ports_and_defaults_follow_the_state(self):
        for state, expected in (('completed', dict(available='true', started='false', completed='true',
                                                   failed='false', unchanged='false')),
                                ('unchanged', dict(available='false', started='false', completed='false',
                                                   failed='false', unchanged='true'))):
            with self.subTest(state=state):
                blob = stub('q_other', state)
                module = E.fromstring(blob).find('Skald/Module')
                self.assertEqual(module.get('Name'), 'q_other')
                ports = [(p.get('Name'), p.get('Direction'), p.get('Type')) for p in module.findall('Ports/Port')]
                self.assertEqual(ports, [(n, 'Out', 'bool') for n in expected])
                self.assertEqual(defaults(blob), {'stub_' + n: v for n, v in expected.items()})
                output = module.find("Nodes/Output[@Name='Output']")
                self.assertEqual({(e.get('From'), e.get('To')) for e in output.findall('Edge')},
                                 {('stub_' + n + '.State', n) for n in expected})

    def test_stub_refuses_unknown_state_and_bad_name(self):
        with self.assertRaises(ValueError): stub('q_other', 'started')
        with self.assertRaises(ValueError): stub('not valid', 'completed')

    def test_host_has_one_true_bool_output(self):
        module = E.fromstring(host('gm_host')).find('Skald/Module')
        self.assertEqual([(p.get('Name'), p.get('Direction'), p.get('Type')) for p in module.findall('Ports/Port')],
                         [('active', 'Out', 'bool')])
        self.assertEqual(defaults(host('gm_host')), {'stub_active': 'true'})

    def test_register_adds_definition_and_instance_and_refuses_collisions(self):
        out = register(ENTRY, '../gm/q_other.xml', 'q_other')
        level = E.fromstring(out).find('Skald/Level')
        self.assertEqual([d.get('File') for d in level.findall('Definitions/Definition')], ['../gm/q_other.xml'])
        self.assertEqual([n.get('Name') for n in level.find('Nodes')], ['existing', 'q_other'])
        self.assertEqual(level.find('Nodes')[1].tag, 'q_other')
        with self.assertRaisesRegex(ValueError, 'already registered'):
            register(out, '../gm/other_file.xml', 'q_other')
        with self.assertRaisesRegex(ValueError, 'already registered'):
            register(out, '../gm/q_other.xml', 'q_second')
        with self.assertRaisesRegex(ValueError, 'already registered'):
            register(ENTRY, '../gm/x.xml', 'existing')
        with self.assertRaises(ValueError): register(b'<Database><Skald/></Database>', 'a.xml', 'q')

    def attach(self, activation, output):
        files = {'project.xml': (
            b'<Database><Skald><Project Name="project"><Definitions>'
            b'<Definition File="host.xml"/><Definition File="stub.xml"/></Definitions>'
            b'<Nodes><gm_host Name="gm_host"/><q_huntPtacek Name="q_huntPtacek"/></Nodes></Project></Skald></Database>'),
            'host.xml': host('gm_host'), 'stub.xml': stub('q_huntPtacek', 'completed')}
        blob = (b'<Database><Skald><FaderDialog Name="conversation"><Ports>'
                b'<Port Name="active" Direction="In" Type="bool"/>'
                b'<Port Name="offer" Direction="In" Type="bool"/>'
                b'</Ports></FaderDialog></Skald></Database>')
        report = dict(actions={}, active_port='active',
                      conditions=dict(offer=dict(quest='q_huntPtacek', output=output)))
        return attach_dialogue(files, 'project', blob, report, activation, 'project.xml')

    def test_attach_dialogue_accepts_host_activation_and_stub_condition(self):
        result = self.attach('gm_host.active', 'completed')
        edges = E.fromstring(result['project.xml']).findall('.//conversation/Edge')
        self.assertEqual({(e.get('From'), e.get('To')) for e in edges},
                         {('gm_host.active', 'active'), ('q_huntPtacek.completed', 'offer')})

    def test_attach_dialogue_still_refuses_undeclared_ports(self):
        with self.assertRaisesRegex(ValueError, 'Incompatible project port'):
            self.attach('gm_host.missing', 'completed')
        with self.assertRaisesRegex(ValueError, 'Incompatible project port'):
            self.attach('gm_host.active', 'missing')

    def test_report_lists_condition_text_and_reading_sequences(self):
        d = dialogue()
        first = d['topics']['1']['sequences'][0]
        first['entry']['entry_condition'] = "IsQuestCompleted('q_huntPtacek') AND IsReady"
        second = copy.deepcopy(first)
        second['source']['sequence_id'] = '11'
        second['entry']['entry_condition'] = 'viaFunction'
        third = copy.deepcopy(first)
        third['source']['sequence_id'] = '12'
        third['entry']['entry_condition'] = "IsQuestCompleted('unrelated')"
        d['topics']['1']['sequences'] += [second, third]
        d['functions'] = {'viaFunction': "IsQuestCompleted('q_huntPtacek')"}
        rows = assumed_prerequisites([d], {'q_huntPtacek': 'completed', 'q_absent': 'unchanged'})
        by_quest = {r['quest']: r for r in rows}
        row = by_quest['q_huntPtacek']
        self.assertEqual(row['state'], 'completed')
        self.assertEqual([c['text'] for c in row['conditions']],
                         ["IsQuestCompleted('q_huntPtacek') AND IsReady", 'viaFunction'])
        self.assertEqual([s['sequence'] for s in row['sequences']], ['10', '11'])
        self.assertEqual(row['sequences'][0], dict(dialogue='opening', topic='1', sequence='10'))
        self.assertEqual(by_quest['q_absent']['conditions'], [])
        with self.assertRaises(ValueError): assumed_prerequisites([d], {'q': 'started'})


if __name__ == '__main__': unittest.main()
