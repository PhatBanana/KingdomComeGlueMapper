import sys
from pathlib import Path
import unittest
import xml.etree.ElementTree as E
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from campaign_training_dialogue import bind as dialogue, native_phases
from campaign_training_schedule import bind as schedule
from test_campaign_combat_runtime import Graph


def schedule_fixture():
    root = E.Element('Document'); skald = E.SubElement(root, 'Skald'); q = E.SubElement(skald, 'Quest')
    ports = E.SubElement(q, 'Ports')
    for name, direction, typ in [('arrive_Started','Out','bool'), ('begin_Started','Out','bool'),
            ('complete_arrive','In','trigger'), ('complete_done','In','trigger'), ('source_state_changed','Out','trigger')]:
        E.SubElement(ports, 'Port', Name=name, Direction=direction, Type=typ)
    host = E.Element('Document'); hskald = E.SubElement(host, 'Skald')
    nodes = E.SubElement(E.SubElement(hskald, 'Module'), 'Nodes')
    life = E.SubElement(nodes, 'Lesson', Name='lesson'); quest = E.SubElement(nodes, 'Quest', Name='quest')
    worker = E.SubElement(nodes, 'EnableBehavior', Name='walker', EventSet='resultNotification')
    return host, nodes, life, quest, worker, E.tostring(root)


class TrainingBindingsTests(unittest.TestCase):
    def test_arrival_cancel_cleanup_allows_retry_without_restarting_objective(self):
        host, nodes, life, quest, worker, definition = schedule_fixture()
        schedule(nodes, life, quest, definition, worker,
                 dict(arrival='arrive', authorization='begin', completion='done'), ['cancel'], ['reconcile'])
        graph = Graph(E.tostring(host))
        graph.values.update({'quest.arrive_Started': True, 'lesson.busy': False})
        request_event = life.find("Edge[@To='request']").get('From')
        graph.fire('quest.source_state_changed')
        self.assertEqual(graph.events.count(request_event), 1)
        graph.values['lesson.busy'] = True
        graph.fire('lesson.arrive'); graph.fire('cancel'); graph.fire('reconcile')
        self.assertEqual(graph.events.count(request_event), 1)
        graph.fire('lesson.canceled')  # lifecycle has stopped workers AND restored equipment
        graph.values['lesson.busy'] = False
        graph.fire('reconcile')
        self.assertEqual(graph.events.count(request_event), 2)

    def test_busy_lifecycle_does_not_consume_a_new_arrival_request(self):
        host, nodes, life, quest, worker, definition = schedule_fixture()
        schedule(nodes, life, quest, definition, worker,
                 dict(arrival='arrive', authorization='begin', completion='done'), ['cancel'], ['reconcile'])
        graph = Graph(E.tostring(host))
        graph.values.update({'quest.arrive_Started': True, 'lesson.busy': True})
        request_event = life.find("Edge[@To='request']").get('From')
        graph.fire('reconcile')
        self.assertNotIn(request_event, graph.events)
        graph.values['lesson.busy'] = False
        graph.fire('reconcile')
        self.assertEqual(graph.events.count(request_event), 1)

    def test_already_active_arrival_worker_rejected_without_partial_graph_changes(self):
        host, nodes, life, quest, worker, definition = schedule_fixture()
        E.SubElement(worker, 'Constant', Name='IsActive', Value='true')
        before = E.tostring(host)
        with self.assertRaisesRegex(ValueError, 'already scheduled'):
            schedule(nodes, life, quest, definition, worker,
                     dict(arrival='arrive', authorization='begin', completion='done'), ['cancel'])
        self.assertEqual(E.tostring(host), before)

    def test_internal_lifecycle_stop_releases_pending_dialogue_locks(self):
        host, nodes, life, _, _, _ = schedule_fixture()
        scenes = {0: dict(node=E.SubElement(nodes, 'Dialogue', Name='instruction'), play_port='Play')}
        dialogue(nodes, life, scenes, [dict(phase=0, custom_step=True)], ['external_cancel'])
        graph = Graph(E.tostring(host))
        pending = next(iter(graph.states))
        graph.states[pending] = True
        graph.fire('lesson.stop_workers')  # e.g. readiness loss, no external cancel event
        self.assertFalse(graph.states[pending])

    def test_native_contract_distinguishes_phase_instruction_from_custom_step(self):
        blob = b'''<Root><Nodes><CombatTutorialNode Name="training"><Edge From="a.ready" To="CustomStepEvent"/></CombatTutorialNode>
        <Switch Name="phase" SwitchValues="0 1"><Constant Name="0Value1" Value="First_starting"/><Constant Name="1Value1" Value="Second_starting"/><Edge From="training.Phase" To="Switch"/></Switch>
        <State Name="progress"><Edge From="phase.Value1" To="Value"/><Edge From="a.ready" To="SetFirst_active"/><Edge From="b.ready" To="SetSecond_active"/></State></Nodes></Root>'''
        phases = native_phases(blob)
        self.assertEqual([p['custom_step'] for p in phases], [True, False])
        nodes = E.Element('Nodes'); life = E.SubElement(nodes, 'Lesson', Name='lesson')
        scenes = {i:dict(node=E.SubElement(nodes,'Dialogue',Name='scene'+str(i)),play_port='Play') for i in (0,1)}
        dialogue(nodes, life, scenes, phases, ['cancel'])
        self.assertEqual(len(life.findall("Edge[@To='instruction_ack']")), 1)
        self.assertEqual(len(nodes.findall('SceneFinishedWaiter')), 2)
        self.assertFalse(any(e.get('From','').endswith('.AfterPlay') for e in life.findall('Edge')))
        for state in nodes.findall('State'):
            self.assertIsNotNone(state.find("Edge[@From='cancel'][@To='SetFalse']"))

    def test_missing_dialogue_mapping_is_not_implicitly_skipped(self):
        with self.assertRaises(ValueError):
            dialogue(E.Element('Nodes'),E.Element('Lesson',Name='lesson'),{},[dict(phase=0,custom_step=True)],[])

    def test_schedule_preserves_authorization_and_only_completes_after_cleanup(self):
        root = E.Element('Document'); skald = E.SubElement(root,'Skald'); q = E.SubElement(skald,'Quest')
        ports = E.SubElement(q,'Ports')
        for name,direction,typ in [('arrive_Started','Out','bool'),('begin_Started','Out','bool'),
                ('complete_arrive','In','trigger'),('complete_done','In','trigger'),('source_state_changed','Out','trigger')]:
            E.SubElement(ports,'Port',Name=name,Direction=direction,Type=typ)
        nodes=E.Element('Nodes');life=E.SubElement(nodes,'Lesson',Name='lesson');quest=E.SubElement(nodes,'Quest',Name='quest')
        worker=E.SubElement(nodes,'EnableBehavior',Name='walker',EventSet='resultNotification')
        schedule(nodes,life,quest,E.tostring(root),worker,dict(arrival='arrive',authorization='begin',completion='done'),['cancel'])
        self.assertEqual(life.find("Edge[@To='lesson_authorized']").get('From'),'quest.begin_Started')
        self.assertEqual(quest.find("Edge[@To='complete_done']").get('From'),'lesson.finished')
        self.assertFalse(any(e.get('From')=='walker.Success' for e in life.findall('Edge')))
        before=E.tostring(nodes)
        with self.assertRaises(ValueError):
            schedule(nodes,life,quest,E.tostring(root),worker,dict(arrival='arrive',authorization='begin',completion='done'),['cancel'])
        self.assertEqual(E.tostring(nodes),before)


if __name__ == '__main__': unittest.main()
