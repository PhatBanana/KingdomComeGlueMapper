import sys
from pathlib import Path
import unittest
import xml.etree.ElementTree as ET

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from campaign_combat_runtime import emit
from campaign_behavior_requests import resolve
from campaign_quest_bridge import UnsupportedOperation


class Graph:
    """Exercise trigger ordering, not a substitute for the game AI runtime."""
    def __init__(self, blob):
        self.root = ET.fromstring(blob)
        self.nodes = {n.get('Name'): n for n in self.root.findall('./Skald/Module/Nodes/*')}
        self.values = {'dialogue_busy': False, 'party_ready': False, 'player_health.Value': 80}
        self.states = {name: False for name, node in self.nodes.items() if node.tag == 'State'}
        self.events = []

    def value(self, ref):
        if ref in self.values: return self.values[ref]
        name, _, port = ref.partition('.')
        if name in self.states: return self.states[name]
        node = self.nodes[name]
        a = {n.get('Name'): n.get('Value') for n in node.findall('Constant')}
        a.update({e.get('To'): self.value(e.get('From')) for e in node.findall('Edge')})
        method = node.get('MethodName', '').split('::')[-1]
        if method == 'Not': return not a['Value']
        if method == 'And': return a['A'] and a['B']
        if method == 'Or': return a['A'] or a['B']
        if method == 'DivideFloat': return float(a['A']) / float(a['B'])
        raise AssertionError('Unsupported value: ' + ref)

    def fire(self, event):
        self.events.append(event)
        for name, node in self.nodes.items():
            for e in node.findall('Edge'):
                if e.get('From') != event: continue
                port = e.get('To')
                if node.tag == 'State':
                    if port in ('SetTrue', 'SetFalse'): self.states[name] = port == 'SetTrue'
                    elif port == 'Exec': self.states[name] = self.value(node.find('Edge[@To="Value"]').get('From'))
                elif node.tag == 'TriggerSequence' and port == 'Exec':
                    for label in 'ABCD': self.fire(name + '.' + label)
                elif node.tag == 'If' and port == 'Exec':
                    cond = node.find('Edge[@To="Condition"]')
                    self.fire(name + ('.True' if self.value(cond.get('From')) else '.False'))
                elif node.tag == 'Output': self.events.append('output.' + port)


def fixture():
    return dict(weapon='unarmed', initial_health=90, player_health_divisor=4,
        actor_threshold=35, buffs=['11111111-1111-1111-1111-111111111111'],
        wake_buff='22222222-2222-2222-2222-222222222222', reaction_grace='7s',
        partners=['arbitrary_companion'], distance_low=20, distance_high=25)


class CombatRuntimeTests(unittest.TestCase):
    def test_source_assault_suppression_survives_stop_then_expires(self):
        p = fixture(); p['suppress_assault_reactions'] = True
        graph = Graph(emit('example', p))
        context = graph.nodes['assault_reaction_suppression']
        enabled = context.find("Edge[@To='IsActive']").get('From')
        self.assertEqual(context.find("Constant[@Name='Context']").get('Value'), 'combat_indifference')
        self.assertFalse(graph.value(enabled))
        graph.fire('request')
        self.assertTrue(graph.value(enabled))
        graph.fire('actor_low_health.OnMatch')
        self.assertTrue(graph.value(enabled))
        graph.fire('stop_actor.onstopped'); graph.fire('stop_watch.OnChanged')
        self.assertTrue(graph.value(enabled))
        graph.fire('grace_timer.OnFinished')
        self.assertFalse(graph.value(enabled))
        self.assertNotIn('assault_reaction_suppression', Graph(emit('ordinary', fixture())).nodes)

    def test_protection_is_added_before_start_and_removed_after_stop(self):
        graph = Graph(emit('example', fixture()))
        self.assertFalse(any(n.tag == 'BuffEffect' for n in graph.nodes.values()))
        add, remove = graph.nodes['protection_add_0'], graph.nodes['protection_remove_0']
        self.assertEqual(add.get('MethodName'), 'wh::rpgmodule::AddBuff')
        self.assertEqual(remove.get('MethodName'), 'wh::rpgmodule::RemoveBuff')
        graph.fire('request')
        self.assertLess(graph.events.index(add.find("Edge[@To='Exec']").get('From')),
                        graph.events.index('output.started'))
        graph.fire('cancel')
        remove_event = remove.find("Edge[@To='Exec']").get('From')
        self.assertNotIn(remove_event, graph.events)
        graph.fire('stop_actor.onstopped'); graph.fire('stop_watch.OnChanged')
        self.assertIn(remove_event, graph.events)
        self.assertLess(graph.events.index(remove_event), graph.events.index('output.stopped'))

    def test_diagnostic_preserves_runtime_graph_and_traces_preparation(self):
        from trace_campaign_combat import instrument
        plan = fixture(); plan['preparation'] = {'optional': True}
        original = emit('gm_combat_example', plan)
        files, events = instrument({'Quests/example.xml': original})
        traced = ET.fromstring(files['Quests/example.xml'])
        nodes = traced.find('./Skald/Module/Nodes')
        for n in list(nodes):
            if n.get('Name', '').startswith('gm_trace_'):
                nodes.remove(n)
        baseline = ET.fromstring(original)
        for tree in (traced, baseline):
            for n in tree.iter():
                if n.text and not n.text.strip(): n.text = None
                if n.tail and not n.tail.strip(): n.tail = None
        self.assertEqual(ET.tostring(traced), ET.tostring(baseline))
        self.assertIn('prepared', events)
        self.assertIn('accept.False', events)

    def test_tool_cleanup_is_acknowledged_before_health_or_combat_changes(self):
        plan = fixture(); plan['preparation'] = {'optional': True}
        graph = Graph(emit('example', plan))
        graph.fire('request')
        self.assertIn('output.prepare', graph.events)
        self.assertFalse(graph.states['fighting'])
        self.assertNotIn('initialize.B', graph.events)
        graph.fire('prepared')
        self.assertTrue(graph.states['fighting'])
        self.assertEqual(graph.states['player_threshold'], 20)

    def test_canceled_cleanup_cannot_start_combat_from_late_ack(self):
        plan = fixture(); plan['preparation'] = {'optional': True}
        graph = Graph(emit('example', plan))
        graph.fire('request'); graph.fire('cancel'); graph.fire('prepared')
        self.assertFalse(graph.states['fighting'])
        self.assertFalse(graph.states['pending'])
        self.assertNotIn('initialize.B', graph.events)

    def test_duplicate_dialogue_release_does_not_repeat_cleanup(self):
        plan = fixture(); plan['preparation'] = {'optional': True}
        graph = Graph(emit('example', plan))
        graph.fire('request'); graph.fire('dialogue_finished'); graph.fire('dialogue_finished')
        self.assertEqual(graph.events.count('output.prepare'), 1)

    def test_dialogue_entered_during_cleanup_defers_combat_start(self):
        plan = fixture(); plan['preparation'] = {'optional': True}
        graph = Graph(emit('example', plan))
        graph.fire('request'); graph.values['dialogue_busy'] = True
        graph.fire('prepared')
        self.assertFalse(graph.states['fighting'])
        graph.values['dialogue_busy'] = False; graph.fire('dialogue_finished')
        self.assertTrue(graph.states['fighting'])
        self.assertEqual(graph.events.count('output.prepare'), 1)

    def test_pending_fight_waits_for_dialogue_release(self):
        graph = Graph(emit('example', fixture()))
        graph.values['dialogue_busy'] = True
        graph.fire('request')
        self.assertTrue(graph.states['pending'])
        self.assertFalse(graph.states['fighting'])
        graph.fire('dialogue_finished')
        self.assertFalse(graph.states['fighting'])
        graph.values['dialogue_busy'] = False
        graph.fire('dialogue_finished')
        self.assertTrue(graph.states['fighting'])
        self.assertFalse(graph.states['pending'])
        self.assertEqual(graph.states['player_threshold'], 20)
        graph.values['player_health.Value'] = 40
        self.assertEqual(graph.states['player_threshold'], 20)

    def test_outcome_waits_for_stop_and_first_result_wins(self):
        graph = Graph(emit('example', fixture()))
        graph.fire('request')
        graph.fire('actor_low_health.OnMatch')
        self.assertFalse(graph.states['fighting'])
        self.assertTrue(graph.states['stopping'])
        self.assertNotIn('output.won', graph.events)
        graph.fire('surrender.OnNotification')
        self.assertFalse(graph.states['result_lost'])
        graph.fire('stop_actor.onstopped')
        graph.fire('stop_watch.OnChanged')
        self.assertIn('output.won', graph.events)
        self.assertNotIn('output.lost', graph.events)

    def test_party_handoff_waits_for_every_active_fighter(self):
        graph = Graph(emit('example', fixture()))
        graph.values['party_ready'] = True
        graph.fire('request'); graph.fire('actor_low_health.OnMatch')
        graph.fire('stop_actor.onstopped'); graph.fire('stop_watch.OnChanged')
        self.assertNotIn('output.won', graph.events)
        graph.fire('stop_partner_0.onstopped'); graph.fire('stop_watch.OnChanged')
        self.assertIn('output.won', graph.events)

    def test_cancel_pending_cannot_start_after_conversation(self):
        graph = Graph(emit('example', fixture()))
        graph.values['dialogue_busy'] = True
        graph.fire('request'); graph.fire('cancel')
        graph.values['dialogue_busy'] = False
        graph.fire('dialogue_finished')
        self.assertFalse(graph.states['fighting'])

    def test_duplicate_request_does_not_reset_health_threshold(self):
        graph = Graph(emit('example', fixture()))
        graph.fire('request')
        graph.values['player_health.Value'] = 40
        graph.fire('request')
        self.assertEqual(graph.states['player_threshold'], 20)
        self.assertEqual(graph.events.count('initialize.B'), 1)

    def test_callback_tag_can_name_a_different_tree_and_file(self):
        tree = {'root': {}, 'variables': []}
        model = dict(controller_registration=dict(entry_points=[dict(kind='behavior_callback',
            name='public_tag', file='quests/shared.xml', tree='actual_program')]),
            behavior_documents={'libs/ai/quests/shared.xml': {'trees': {'actual_program': tree}}})
        self.assertIs(resolve(model, dict(source='$this.id', tree='public_tag'))['program'], tree)
        with self.assertRaises(UnsupportedOperation): resolve(model, dict(source='$other', tree='public_tag'))
        model['controller_registration']['entry_points'] *= 2
        with self.assertRaises(UnsupportedOperation): resolve(model, dict(source='$this.id', tree='public_tag'))


if __name__ == '__main__': unittest.main()
