import copy
import sys
import unittest
from pathlib import Path
import xml.etree.ElementTree as E
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from campaign_combat_work import emit
from campaign_combat_work_graph import wire, after_privacy, after_dialogue
from campaign_combat import assemble
from campaign_quest_graph import definition, xml
from test_campaign_combat_runtime import Graph


def fixture():
    return dict(privacy=dict(guard=dict(objective='resolved', function='IsObjectiveCompleted', negate=True), label='private'),
        dialogue=dict(guard=dict(objective='collect', function='IsObjectiveUnchanged', negate=False), alias='example_result'),
        work=dict(role='resting_place', behavior='use'), bark=dict(alias='example_bark', delay='37s', low=4, high=6))


class CombatWorkTests(unittest.TestCase):
    def graph(self):
        root, host = definition('Module', 'fixture')
        nodes = E.SubElement(host, 'Nodes')
        fight = E.SubElement(nodes, 'fight', Name='fight')
        p = dict(preparation=dict(guard=dict(objective='tool_taken', function='IsObjectiveCompleted', negate=True)),
                 outcomes=dict(won=dict(aftermath=fixture())))
        phases = wire(nodes, 'fight', p, dict(host='host', tool='slot', area='area', place='place'),
                      'actor', 'quest', fight, ['quest.done'])
        after_privacy(nodes, 'fight', fixture(), 'quest', 'fight.won', phases)
        after_dialogue(nodes, 'fight', E.Element('dialog', Name='result_dialogue'), phases)
        return Graph(xml(root))

    def test_privacy_then_guarded_dialogue_then_work(self):
        g = self.graph(); g.values['quest.collect_Unchanged'] = True
        g.fire('fight.won')
        self.assertTrue(g.states['fight_work_privacy'])
        self.assertFalse(g.states['fight_work_routine'])
        g.fire('fight_work_privacy_enable.Success')
        self.assertTrue(g.states['fight_work_waiting_dialogue'])
        self.assertFalse(g.states['fight_work_routine'])
        g.fire('fight_work_dialogue_release.OnFinished')
        self.assertTrue(g.states['fight_work_routine'])
        self.assertFalse(g.states['fight_work_waiting_dialogue'])

    def test_already_consumed_dialogue_goes_directly_to_work(self):
        g = self.graph(); g.values['quest.collect_Unchanged'] = False
        g.fire('fight.won'); g.fire('fight_work_privacy_enable.Success')
        self.assertTrue(g.states['fight_work_routine'])
        self.assertFalse(g.states['fight_work_waiting_dialogue'])

    def test_cancel_blocks_late_dialogue_completion(self):
        g = self.graph(); g.values['quest.collect_Unchanged'] = True
        g.fire('fight.won'); g.fire('fight_work_privacy_enable.Success')
        g.fire('quest.done'); g.fire('fight_work_dialogue_release.OnFinished')
        self.assertFalse(g.states['fight_work_routine'])

    def test_new_fight_cancels_previous_routine(self):
        g = self.graph(); g.states['fight_work_routine'] = True
        g.fire('fight.requested')
        self.assertFalse(g.states['fight_work_routine'])

    def test_native_callback_after_cancellation_does_not_start_routine(self):
        g = self.graph()
        g.fire('fight.won'); g.fire('quest.done')
        g.fire('fight_work_privacy_enable.Success')
        self.assertFalse(g.states['fight_work_routine'])
        self.assertFalse(g.states['fight_work_waiting_dialogue'])

    def test_native_failure_does_not_report_preparation_success(self):
        g = self.graph(); g.fire('fight.prepare')
        g.fire('fight_work_prepare_enable.Fail')
        self.assertFalse(g.states['fight_work_prepare'])
        self.assertNotIn('fight_work_prepare_finish.B', g.events)

    def test_work_requests_native_scheduler_kick_and_instance_callbacks(self):
        g = self.graph()
        for phase in ('prepare', 'privacy', 'routine'):
            node = g.nodes['fight_work_' + phase + '_enable']
            self.assertEqual(node.get('EventSet'), 'resultNotification')
            self.assertEqual(node.find("Constant[@Name='ForceKick']").get('Value'), 'true')
        self.assertFalse(any(n.tag == 'AIConceptSignalTrigger' for n in g.nodes.values()))

    def test_dialogue_activity_precedes_effects_and_is_idempotent(self):
        from campaign_dialogue_activity import expose, ACTIVITY_PORT
        host = E.fromstring('<FaderDialog><Ports/><Dialogue><Decision><Sequences><Sequence Name="s"><Triggers><Port Name="quest_effect"/></Triggers><Elements/></Sequence></Sequences></Decision></Dialogue></FaderDialog>')
        expose(host); expose(host)
        self.assertEqual([n.get('Name') for n in host.findall('.//Sequence/Triggers/Port')],
                         [ACTIVITY_PORT, 'quest_effect'])
        self.assertEqual(len(host.findall('Ports/Port')), 1)

    def test_work_and_bark_are_parallel_with_authored_delay_and_hysteresis(self):
        files = emit('arbitrary', fixture())
        r = E.fromstring(files['AI/arbitrary_work.xml'])
        p = r.find("BehaviorTree[@name='routine']/Root/Behavior/FuseBox/Child/Sequence/Parallel")
        self.assertEqual([n.tag for n in p], ['Loop', 'EntityContextElement'])
        self.assertEqual(p.find('.//Wait').get('duration'), "'37s'")
        d = p.find('.//DistanceGate')
        self.assertEqual((d.get('Low'), d.get('High')), ('4', '6'))
        self.assertIn('example_bark', d.find('InstantSendMessageToNPC').get('values'))
        prep = r.find("BehaviorTree[@name='prepare']/Root/Behavior/FuseBox/Child/Sequence")
        self.assertEqual(prep[0].tag, 'SuppressFailure')
        self.assertEqual(r.find("BehaviorTree[@name='prepare']/Root/Behavior/FuseBox/OnSuccess/Callback_empty").get('EventName'), "'Success'")
        self.assertIsNone(prep.find('.//CreateItem'))

    def test_campaign_assembly_reports_failed_binding_without_partial_outputs(self):
        source = {'Quests/example.xml': b'original'}
        reg = {'world/registration/objects_mission0.xml': b'world', 'world/registration/waitinglinks.xml': b'links',
               'world/registration/tables/ai/scheduler.xml': b'scheduler'}
        discovery = dict(candidates=[dict(quest='quest', tag='custom')], unresolved=[])
        with patch('campaign_combat.discover', return_value=discovery), patch('campaign_combat.convert', side_effect=ValueError('missing actor')):
            files, world, report = assemble([{'quest': 'quest'}], {'quest': {}}, source, reg, 'example', Path('.'))
        self.assertEqual(files, source); self.assertEqual(world, reg)
        self.assertEqual(report['unresolved'][0]['phase'], 'binding')
        self.assertFalse(report['converted'])

    def test_campaign_assembly_publishes_shared_converter_outputs(self):
        source = {'Quests/example.xml': b'original'}
        reg = {'world/registration/objects_mission0.xml': b'world', 'world/registration/waitinglinks.xml': b'links',
               'world/registration/tables/ai/scheduler.xml': b'scheduler'}
        discovery = dict(candidates=[dict(quest='quest', tag='custom')], unresolved=[])
        changes = {'Quests/example.xml': b'updated', 'AI/work.xml': b'work'}
        world_changes = {'objects_mission0.xml': b'updated world', 'tables/ai/scheduler.xml': b'compiled activities'}
        with patch('campaign_combat.discover', return_value=discovery), patch('campaign_combat.convert',
                return_value=(changes, world_changes, {'source': 'retained'})) as converter:
            files, world, report = assemble([{'quest': 'quest'}], {'quest': {}}, source, reg, 'example', Path('.'))
        self.assertEqual(converter.call_args.args[5:7], ('Quests/example.xml', 'Quests/example.xml'))
        self.assertEqual(files['AI/work.xml'], b'work')
        self.assertEqual(files['Quests/example.xml'], b'updated')
        self.assertEqual(world['world/registration/objects_mission0.xml'], b'updated world')
        self.assertEqual(world['world/registration/waitinglinks.xml'], b'links')
        self.assertEqual(converter.call_args.args[1]['tables/ai/scheduler.xml'], b'scheduler')
        self.assertEqual(world['world/registration/tables/ai/scheduler.xml'], b'compiled activities')
        self.assertEqual(len(report['converted']), 1)
        self.assertFalse(report['unresolved'])
        self.assertEqual(source['Quests/example.xml'], b'original')


if __name__ == '__main__': unittest.main()
