import sys
from pathlib import Path
import unittest
import xml.etree.ElementTree as E
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from campaign_training_host import bind, guard_authorization
from campaign_training_worker import emit,basic_equipment_policy
from campaign_training_equipment import lower
from campaign_behavior import BehaviorCompiler
from test_campaign_behavior import catalog
from test_campaign_training_plan import equipment,ITEM
from test_campaign_combat_runtime import Graph


class TrainingHostTests(unittest.TestCase):
    def test_continuation_cannot_authorize_before_arrival(self):
        root=E.Element('Document')
        nodes=E.SubElement(E.SubElement(E.SubElement(root,'Skald'),'Module'),'Nodes')
        speech=E.SubElement(nodes,'Conversation',Name='speech')
        E.SubElement(speech,'Edge',From='existing_eligibility',To='active')
        objectives=dict(arrival='reach_workplace',completion='finished',authorization='accepted')
        self.assertTrue(guard_authorization(nodes,'lesson','other_quest',objectives,[speech]))
        graph=Graph(E.tostring(root)); active=speech.find("Edge[@To='active']").get('From')
        for started,arrived,finished,eligible,expected in [
                (True,False,False,True,False), # the reported premature continuation
                (True,True,False,True,True),
                (True,True,True,True,False),
                (False,True,False,True,False),
                (True,True,False,False,False)]:
            graph.values.update({'other_quest.started':started,
                'other_quest.reach_workplace_Completed':arrived,
                'other_quest.finished_Completed':finished,'existing_eligibility':eligible})
            self.assertEqual(graph.value(active),expected)
        before=E.tostring(root)
        self.assertFalse(guard_authorization(nodes,'lesson','other_quest',objectives,[speech]))
        self.assertEqual(E.tostring(root),before)

    def test_changed_arrival_contract_is_rejected(self):
        nodes=E.Element('Nodes');speech=E.SubElement(nodes,'Conversation',Name='speech')
        E.SubElement(speech,'Edge',From='q.started',To='active')
        objectives=dict(arrival='arrival',completion='done')
        guard_authorization(nodes,'lesson','q',objectives,[speech])
        before=E.tostring(nodes)
        with self.assertRaises(ValueError):
            guard_authorization(nodes,'lesson','q',dict(arrival='other',completion='done'),[speech])
        self.assertEqual(before,E.tostring(nodes))

    def test_authorization_binding_ignores_dialogue_action_nodes(self):
        from setup_training_upgrade import conversations,validate_references
        nodes=E.Element('Nodes')
        dialog=E.SubElement(nodes,'talk',Name='speech_1')
        E.SubElement(nodes,'TriggerSequence',Name='speech_1_effects')
        E.SubElement(nodes,'If',Name='speech_1_gate')
        files={'talk.xml':b'<Document><Skald><FaderDialog Name="talk"><Ports/></FaderDialog></Skald></Document>'}
        self.assertEqual(conversations(nodes,files,'speech_'),[dialog])
        root=E.Element('Document');level=E.SubElement(E.SubElement(root,'Skald'),'Level');level.append(nodes)
        waiter=E.SubElement(nodes,'SceneFinishedWaiter',Name='test_waiter')
        E.SubElement(waiter,'Edge',From='speech_1_effects.AfterPlay',To='Enqueue')
        with self.assertRaises(ValueError):validate_references(root,files,'test_')
        waiter[0].set('From','speech_1.AfterPlay')
        validate_references(root,files,'test_')

    def fixture(self):
        root=E.Element('Document');nodes=E.SubElement(E.SubElement(E.SubElement(root,'Skald'),'Module'),'Nodes')
        lesson=E.SubElement(nodes,'Lesson',Name='lesson')
        worker=E.SubElement(nodes,'EnableBehavior',Name='worker',Signature='arbitrary',EventSet='arbitrary_events')
        speech=E.SubElement(nodes,'Conversation',Name='speech')
        bind(nodes,lesson,worker,dialogue_nodes=[speech])
        return Graph(E.tostring(root)),lesson,worker

    def test_active_worker_must_acknowledge_stop_and_cleanup(self):
        graph,lesson,worker=self.fixture()
        graph.fire('lesson.prepare')
        self.assertTrue(graph.value(worker.find("Edge[@To='IsActive']").get('From')))
        graph.fire('lesson.stop_workers');graph.fire('lesson.cleanup')
        for port in ('workers_stopped','cleanup_done'):
            self.assertFalse(any(e.get('From') in graph.events for e in lesson.findall("Edge[@To='"+port+"']")))
        self.assertTrue(graph.value(worker.find("Edge[@To='stopRequested']").get('From')))
        self.assertTrue(graph.value(worker.find("Edge[@To='cleanupRequested']").get('From')))
        self.assertTrue(graph.value(worker.find("Edge[@To='IsActive']").get('From')))
        graph.fire('worker.Cleaned')
        self.assertFalse(graph.value(worker.find("Edge[@To='IsActive']").get('From')))

    def test_cancel_before_preparation_has_no_equipment_to_restore(self):
        graph,lesson,_=self.fixture()
        graph.fire('lesson.stop_workers');graph.fire('lesson.cleanup')
        for port in ('workers_stopped','cleanup_done'):
            self.assertTrue(any(e.get('From') in graph.events for e in lesson.findall("Edge[@To='"+port+"']")))

    def test_dialogue_release_waits_until_scene_finished(self):
        graph,lesson,_=self.fixture()
        busy=lesson.find("Edge[@To='dialogue_busy']").get('From')
        graph.fire('speech.BeforePlay');self.assertTrue(graph.value(busy))
        graph.fire('speech.AfterPlay');self.assertTrue(graph.value(busy))
        waiter=next(n for n in graph.nodes.values() if n.tag=='SceneFinishedWaiter')
        graph.fire(waiter.get('Name')+'.OnFinished');self.assertFalse(graph.value(busy))

    def test_readiness_requires_worker_callback_and_is_released_on_stop(self):
        graph,lesson,_=self.fixture();ready=lesson.find("Edge[@To='tutor_ready']").get('From')
        graph.fire('lesson.prepare');graph.fire('worker.Prepared');self.assertFalse(graph.value(ready))
        graph.fire('worker.Ready');self.assertTrue(graph.value(ready))
        graph.fire('worker.WorkersStopped');self.assertFalse(graph.value(ready))

    def test_worker_uses_shared_handles_and_guards_partial_preparation(self):
        compiler=BehaviorCompiler([],'Generic',catalog(),registered={'items':{ITEM:ITEM}})
        roots,variables,_=lower(compiler,'other_quest','arbitrary.xml',*equipment(),
            [dict(name='loan',type='_wuid',form='single',values='')])
        files=emit('generic',roots,variables,b'<database/>')
        root=E.fromstring(files['AI/generic.xml'])
        self.assertEqual(root.find('.//Variables/Variable').get('isPersistent'),'1')
        gate=root.find('.//VariableExistsGate')
        self.assertEqual(gate.get('VarToTest'),'$loan')
        self.assertEqual(gate.find('Then/RemoveItem').get('Item'),'$loan')
        self.assertIsNotNone(root.find(".//EntityContext/Sequence/Callback_empty[@EventName=\"'Ready'\"]"))
        seq=root.find('.//Root/Behavior/Sequence')
        self.assertEqual(seq[2].get('EventName'),"'WorkersStopped'")
        self.assertIsNotNone(seq[-2].find("FuseBox/OnSuccess/Callback_empty[@EventName=\"'Cleaned'\"]"))
        self.assertEqual(seq[-1].tag,'Wait')
        self.assertEqual(seq[-1].get('duration'),"'-1'")
        self.assertIsNotNone(seq[0].find('FuseBox/Child/Sequence/WaitAction'))

    def test_unknown_draw_operation_is_not_silently_removed(self):
        for target,values in [('another_actor','set($enum:weaponSet.primary)'),('__player','unknown')]:
            root=dict(op='Root',children=[dict(op='InstantSendMessageToNPC',attributes=
                dict(type='player:drawWeapon',target=target,values=values),children=[])])
            with self.assertRaises(ValueError):basic_equipment_policy('prepare',root,dict(leases=[]))

if __name__=='__main__':unittest.main()
