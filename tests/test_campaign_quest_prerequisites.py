import copy
from pathlib import Path
import sys
import unittest
import xml.etree.ElementTree as E

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from campaign_dialogue_runtime import attach_dialogue
from campaign_quest_prerequisites import (assumed_prerequisites, host, instances, premise, premise_report, register,
                                          story, story_chain, switch)
from quest_lab.graph import Graph
from quest_lab.source import Source
from test_campaign_dialogue_presentation import model as dialogue

ENTRY = (b'<Database><Skald><Level Name="level"><Definitions/><Nodes>'
         b'<existing Name="existing"/></Nodes></Level></Skald></Database>')
REAL = (b'<Database><Skald><Module Name="q_first"><Ports><Port Name="done" Direction="In" Type="bool"/>'
        b'<Port Name="untouched" Direction="In" Type="bool"/><Port Name="completed" Direction="Out" Type="bool"/>'
        b'<Port Name="unchanged" Direction="Out" Type="bool"/></Ports><Nodes><Output Name="Output">'
        b'<Edge From="done" To="completed"/><Edge From="untouched" To="unchanged"/></Output></Nodes></Module></Skald></Database>')
PORTS = dict(completed=('Out', 'bool'), unchanged=('Out', 'bool'))


def master(extra=()):
    names = ('q_first', 'q_second', 'q_third', 'q_fourth')
    objectives = [dict(objective_id=str(i), objective_name=n, condition="IsQuestCompleted('%s')" % n)
                  for i, n in enumerate(names, 21)]
    objectives += [dict(objective_id='90', objective_name='side_gate', condition="IsQuestCompleted('q_second')"),
                   dict(objective_id='91', objective_name='q_loose', condition="IsQuestCompleted('q_loose')"),
                   dict(objective_id='92', objective_name='q_mixed', condition="IsQuestCompleted('q_mixed') OR 1")]
    transitions = [dict(from_objective_id='2', to_objective_id='21', enabled='False'),
                   dict(from_objective_id='21', to_objective_id='22', enabled='True'),
                   dict(from_objective_id='22', to_objective_id='23', enabled='True'),
                   dict(from_objective_id='23', to_objective_id='24', enabled='True'),
                   dict(from_objective_id='24', to_objective_id='23', enabled='False'),
                   dict(from_objective_id='90', to_objective_id='91', enabled='True'), *extra]
    return dict(tables=dict(quest_objective=dict(rows=objectives), quest_transition=dict(rows=transitions)))


def entry_with_head():
    return register(ENTRY, 'q_first.xml', 'q_first')


def staged(chain, premises, entry=None, ports=PORTS):
    return story(entry or entry_with_head(), chain, premises, lambda name: ports, 'premise', 'premise.xml',
                 'story_switch', 'switch.xml')


def defaults(blob):
    root = E.fromstring(blob).find('Skald/Module')
    return {s.get('Name'): s.find("Constant[@Name='DefaultValue']").get('Value')
            for s in root.findall('Nodes/State')}


class ModuleTests(unittest.TestCase):
    def test_host_has_one_true_bool_output(self):
        module = E.fromstring(host('gm_host')).find('Skald/Module')
        self.assertEqual([(p.get('Name'), p.get('Direction'), p.get('Type')) for p in module.findall('Ports/Port')],
                         [('active', 'Out', 'bool')])
        self.assertEqual(defaults(host('gm_host')), {'stub_active': 'true'})

    def test_premise_has_a_quests_state_outputs_and_no_constant_true(self):
        module = E.fromstring(premise('premise')).find('Skald/Module')
        self.assertEqual([(p.get('Name'), p.get('Direction'), p.get('Type')) for p in module.findall('Ports/Port')],
                         [('assumed', 'In', 'bool'), ('activated', 'In', 'bool'),
                          *((n, 'Out', 'bool') for n in ('available', 'started', 'completed', 'failed', 'unchanged'))])
        self.assertEqual(defaults(premise('premise')), {'never': 'false'})
        output = {e.get('To'): e.get('From') for e in module.find("Nodes/Output").findall('Edge')}
        self.assertEqual(output, dict(available='reachable.bool', started='never.State', completed='assumed',
                                      failed='never.State', unchanged='untold.bool'))
        with self.assertRaises(ValueError): premise('not valid')

    def test_switch_passes_its_single_input(self):
        module = E.fromstring(switch('story_switch')).find('Skald/Module')
        self.assertEqual([(p.get('Name'), p.get('Direction')) for p in module.findall('Ports/Port')],
                         [('story_unchanged', 'In'), ('assumed', 'Out')])
        self.assertEqual([(e.get('From'), e.get('To')) for e in module.find('Nodes/Output')], [('story_unchanged', 'assumed')])

    def test_premise_truth_table_in_the_lab(self):
        outer = (b'<Database><Skald><Module Name="Outer"><Definitions><Definition File="premise.xml"/></Definitions><Ports>'
                 b'<Port Name="assumed" Direction="In" Type="bool"/><Port Name="activated" Direction="In" Type="bool"/>'
                 b'</Ports><Nodes><premise Name="q_x"><Edge From="assumed" To="assumed"/>'
                 b'<Edge From="activated" To="activated"/></premise></Nodes></Module></Skald></Database>')
        graph = Graph(Source.blobs({'outer.xml': outer, 'premise.xml': premise('premise')}), 'Outer')
        self.assertEqual(graph.unsupported, [])
        expected = {(False, False): dict(available=False, started=False, completed=False, failed=False, unchanged=True),
                    (False, True): dict(available=True, started=False, completed=False, failed=False, unchanged=True),
                    (True, False): dict(available=True, started=False, completed=True, failed=False, unchanged=False),
                    (True, True): dict(available=True, started=False, completed=True, failed=False, unchanged=False)}
        for (assumed, activated), outputs in expected.items():
            graph.set_inputs(dict(assumed=assumed, activated=activated))
            self.assertEqual({port: bool(graph.value('q_x.' + port)) for port in outputs}, outputs, (assumed, activated))


class RegisterTests(unittest.TestCase):
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

    def test_named_instances_share_one_module_file(self):
        one = register(ENTRY, 'premise.xml', 'premise', instance='q_a', edges=[('s.assumed', 'assumed')])
        two = register(one, 'premise.xml', 'premise', instance='q_b', edges=[('q_a.completed', 'activated')])
        level = E.fromstring(two).find('Skald/Level')
        self.assertEqual([d.get('File') for d in level.findall('Definitions/Definition')], ['premise.xml'])
        self.assertEqual(instances(two), dict(existing=('existing', []), q_a=('premise', [('s.assumed', 'assumed')]),
                                              q_b=('premise', [('q_a.completed', 'activated')])))
        with self.assertRaisesRegex(ValueError, 'already registered: q_a'):
            register(two, 'premise.xml', 'premise', instance='q_a')
        with self.assertRaisesRegex(ValueError, 'already registered: existing'):
            register(two, 'premise.xml', 'premise', instance='existing')


class ChainTests(unittest.TestCase):
    def test_chain_is_read_from_the_named_objectives_and_enabled_transitions(self):
        chain = story_chain(master(), ['q_third'])
        self.assertEqual(chain, [
            dict(quest='q_first', objective_id='21', condition="IsQuestCompleted('q_first')", after=None),
            dict(quest='q_second', objective_id='22', condition="IsQuestCompleted('q_second')", after='q_first'),
            dict(quest='q_third', objective_id='23', condition="IsQuestCompleted('q_third')", after='q_second')])
        self.assertEqual([l['quest'] for l in story_chain(master(), ['q_fourth', 'q_second'])],
                         ['q_first', 'q_second', 'q_third', 'q_fourth'])
        self.assertEqual(story_chain(master(), []), [])

    def test_unknown_forked_and_non_story_predecessors_are_refused(self):
        with self.assertRaisesRegex(ValueError, 'not in the source story chain: q_absent'):
            story_chain(master(), ['q_absent'])
        with self.assertRaisesRegex(ValueError, 'not in the source story chain: q_mixed'):
            story_chain(master(), ['q_mixed'])                     # its condition is not the plain one
        with self.assertRaisesRegex(ValueError, 'not linear at q_loose'):
            story_chain(master(), ['q_loose'])                     # it follows a side gate, not a story quest
        fork = [dict(from_objective_id='21', to_objective_id='23', enabled='True')]
        with self.assertRaisesRegex(ValueError, 'not linear at q_third'):
            story_chain(master(fork), ['q_third'])
        twice = master()
        twice['tables']['quest_objective']['rows'].append(dict(objective_id='99', objective_name='q_second',
                                                               condition="IsQuestCompleted('q_second')"))
        with self.assertRaisesRegex(ValueError, 'two master objectives: q_second'):
            story_chain(twice, ['q_third'])


class StoryTests(unittest.TestCase):
    def test_switch_and_premises_are_wired_in_chain_order(self):
        chain = story_chain(master(), ['q_third'])
        entry, report = staged(chain, ['q_second', 'q_third'])
        self.assertEqual(report, dict(switch=dict(name='story_switch', signal='q_first.unchanged'),
                                      premises=['q_second', 'q_third'], real=['q_first']))
        found = instances(entry)
        self.assertEqual(found['story_switch'], ('story_switch', [('q_first.unchanged', 'story_unchanged')]))
        self.assertEqual(found['q_second'], ('premise', [('story_switch.assumed', 'assumed'), ('q_first.completed', 'activated')]))
        self.assertEqual(found['q_third'], ('premise', [('story_switch.assumed', 'assumed'), ('q_second.completed', 'activated')]))
        self.assertEqual(found['q_first'], ('q_first', []))
        self.assertEqual(staged(chain, ['q_second', 'q_third'], entry=entry)[0], entry)
        self.assertEqual(staged([], ['q_second'], entry=ENTRY), (ENTRY, dict(switch=None, premises=[], real=[])))

    def test_real_and_premise_never_overlap(self):
        chain = story_chain(master(), ['q_third'])
        with self.assertRaisesRegex(ValueError, 'neither registered nor a declared premise: q_third'):
            staged(chain, ['q_second'])
        with self.assertRaisesRegex(ValueError, 'registered for real; delete its premise row: q_first'):
            staged(chain, ['q_first', 'q_second', 'q_third'])
        with self.assertRaisesRegex(ValueError, 'needs the first story quest registered for real: q_first'):
            staged(chain, ['q_first', 'q_second', 'q_third'], entry=ENTRY)
        with self.assertRaisesRegex(ValueError, 'does not expose its state: q_first'):
            staged(chain, ['q_second', 'q_third'], ports=dict(completed=('Out', 'bool')))
        entry, _ = staged(chain, ['q_second', 'q_third'])
        with self.assertRaisesRegex(ValueError, 'Premise instance has no premise row: q_second'):
            staged(chain, ['q_third'], entry=entry)
        rewired = entry.replace(b'From="q_first.unchanged"', b'From="q_first.completed"')
        with self.assertRaisesRegex(ValueError, 'switch is already registered differently'):
            staged(chain, ['q_second', 'q_third'], entry=rewired)
        loose = entry.replace(b'From="q_second.completed"', b'From="q_first.completed"')
        with self.assertRaisesRegex(ValueError, 'Premise is already registered differently: q_third'):
            staged(chain, ['q_second', 'q_third'], entry=loose)

    def test_the_wired_chain_in_the_lab(self):
        chain = story_chain(master(), ['q_third'])
        entry, _ = staged(chain, ['q_second', 'q_third'])
        entry = entry.replace(b'<Level Name="level">', b'<Level Name="level"><Ports><Port Name="done" Direction="In" Type="bool"/>'
                              b'<Port Name="untouched" Direction="In" Type="bool"/></Ports>')
        entry = entry.replace(b'<q_first Name="q_first" />', b'<q_first Name="q_first"><Edge From="done" To="done"/>'
                              b'<Edge From="untouched" To="untouched"/></q_first>').replace(b'<existing Name="existing" />', b'')
        graph = Graph(Source.blobs({'level.xml': entry, 'q_first.xml': REAL, 'premise.xml': premise('premise'),
                                    'switch.xml': switch('story_switch')}), 'level')
        self.assertEqual(graph.unsupported, [])
        read = lambda: {q + '.' + p: bool(graph.value(q + '.' + p)) for q in ('q_second', 'q_third')
                        for p in ('available', 'completed', 'unchanged')}
        graph.set_inputs(dict(untouched=True, done=False))          # the story never began
        self.assertEqual(read(), {'q_second.available': True, 'q_second.completed': True, 'q_second.unchanged': False,
                                  'q_third.available': True, 'q_third.completed': True, 'q_third.unchanged': False})
        graph.set_inputs(dict(untouched=False, done=False))         # the first quest is being played
        self.assertEqual(read(), {'q_second.available': False, 'q_second.completed': False, 'q_second.unchanged': True,
                                  'q_third.available': False, 'q_third.completed': False, 'q_third.unchanged': True})
        graph.set_inputs(dict(untouched=False, done=True))          # ... and is completed: only the next is activated
        self.assertEqual(read(), {'q_second.available': True, 'q_second.completed': False, 'q_second.unchanged': True,
                                  'q_third.available': False, 'q_third.completed': False, 'q_third.unchanged': True})


class DialogueBindingTests(unittest.TestCase):
    def attach(self, activation, output):
        project = register(register(b'<Database><Skald><Project Name="project"><Definitions/><Nodes/></Project></Skald></Database>',
                                    'host.xml', 'gm_host'), 'premise.xml', 'premise', instance='q_huntPtacek')
        files = {'project.xml': project, 'host.xml': host('gm_host'), 'premise.xml': premise('premise')}
        blob = (b'<Database><Skald><FaderDialog Name="conversation"><Ports>'
                b'<Port Name="active" Direction="In" Type="bool"/>'
                b'<Port Name="offer" Direction="In" Type="bool"/>'
                b'</Ports></FaderDialog></Skald></Database>')
        report = dict(actions={}, active_port='active',
                      conditions=dict(offer=dict(quest='q_huntPtacek', output=output)))
        return attach_dialogue(files, 'project', blob, report, activation, 'project.xml')

    def test_attach_dialogue_accepts_host_activation_and_a_premise_under_the_quests_name(self):
        result = self.attach('gm_host.active', 'completed')
        edges = E.fromstring(result['project.xml']).findall('.//conversation/Edge')
        self.assertEqual({(e.get('From'), e.get('To')) for e in edges},
                         {('gm_host.active', 'active'), ('q_huntPtacek.completed', 'offer')})

    def test_attach_dialogue_still_refuses_undeclared_ports(self):
        with self.assertRaisesRegex(ValueError, 'Incompatible project port'):
            self.attach('gm_host.missing', 'completed')
        with self.assertRaisesRegex(ValueError, 'Incompatible project port'):
            self.attach('gm_host.active', 'missing')


class ReportTests(unittest.TestCase):
    def models(self):
        d = dialogue()
        first = d['topics']['1']['sequences'][0]
        first['entry']['entry_condition'] = "IsQuestCompleted('q_third') AND IsReady"
        second = copy.deepcopy(first)
        second['source']['sequence_id'] = '11'
        second['entry']['entry_condition'] = 'viaFunction'
        third = copy.deepcopy(first)
        third['source']['sequence_id'] = '12'
        third['entry']['entry_condition'] = "IsQuestCompleted('unrelated')"
        d['topics']['1']['sequences'] += [second, third]
        d['functions'] = {'viaFunction': "IsQuestCompleted('q_third')"}
        return [d]

    def test_report_lists_condition_text_and_reading_sequences(self):
        rows = assumed_prerequisites(self.models(), ['q_third', 'q_absent'])
        by_quest = {r['quest']: r for r in rows}
        row = by_quest['q_third']
        self.assertEqual([c['text'] for c in row['conditions']], ["IsQuestCompleted('q_third') AND IsReady", 'viaFunction'])
        self.assertEqual([s['sequence'] for s in row['sequences']], ['10', '11'])
        self.assertEqual(row['sequences'][0], dict(dialogue='opening', topic='1', sequence='10'))
        self.assertEqual(by_quest['q_absent']['conditions'], [])
        with self.assertRaises(ValueError): assumed_prerequisites(self.models(), ['not valid'])

    def test_every_chain_quest_is_reported_with_the_source_condition(self):
        chain = story_chain(master(), ['q_third'])
        _, registered = staged(chain, ['q_second', 'q_third'])
        rows = premise_report(chain, registered, self.models(), 'q_master_main')
        self.assertEqual([(r['quest'], r['premise'], r['after']) for r in rows],
                         [('q_first', False, None), ('q_second', True, 'q_first'), ('q_third', True, 'q_second')])
        self.assertEqual(rows[2]['source'], dict(quest='q_master_main', objective_id='23',
                                                 condition="IsQuestCompleted('q_third')"))
        self.assertEqual((rows[2]['switch'], rows[2]['signal'], rows[2]['when_signal_true'], rows[2]['when_signal_false']),
                         ('story_switch', 'q_first.unchanged', 'completed', 'not started'))
        self.assertEqual([s['sequence'] for s in rows[2]['sequences']], ['10', '11'])
        self.assertEqual(rows[1]['conditions'], [])
        self.assertNotIn('switch', rows[0])


if __name__ == '__main__': unittest.main()
