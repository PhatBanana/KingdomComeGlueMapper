import unittest
import xml.etree.ElementTree as E
from unittest.mock import patch
from campaign_training_entry import resolve, stage

class TrainingEntryTests(unittest.TestCase):
    def source(self):
        q=E.fromstring('''<Entity Name="different_quest"><EntityLinks><Link Name="QuestPlace['pit']" TargetId="2" TargetGuid="0"/></EntityLinks></Entity>''')
        area=E.fromstring('''<Entity EntityId="2" EntityGuid="12"><EntityLinks><Link Name="" TargetId="999"/><Link Name="position" TargetId="7"/><Link Name="position" TargetId="8"/></EntityLinks></Entity>''')
        points=[E.Element('Entity',EntityId=str(i),EntityGuid=str(i),EntityClass='TagPoint',Pos=p,Rotate='1,0,0,0') for i,p in ((7,'17,28,39'),(8,'41,52,63'))]
        b=b'''<BehaviorTrees><BehaviorTree name="ask"><Root><OnInit><GraphSearch><LinkDataFilter tag="QuestPlace" condition="$QuestPlace == 'pit'" Child="arena"/></GraphSearch></OnInit><Behavior><InstantSendMessageToNPC target="arena" type="duel:startDuelWithPlayer" values="difficulty(-1)"/></Behavior></Root></BehaviorTree></BehaviorTrees>'''
        a=b'''<BehaviorTrees><BehaviorTree name="router"><Root><Behavior><IfCondition condition="$startDuelMessage.difficulty == -1"><InstantSendMessageToNPC type="combat:stimulus:customBehaviorRequest" values="entity($__player),behaviorName('lessonRoutine'),behaviorSource($this.id)"/></IfCondition></Behavior></Root></BehaviorTree><BehaviorTree name="lessonRoutine"><Root><OnInit><GraphSearch Origin="__area.id"><LinkTagFilter tag="position"/><Nodalyzer Child="positions"/></GraphSearch></OnInit><Behavior><FaderBarrier><Sequence><Teleport Position="positions[0]" Target="__player"/><Teleport Position="positions[1]" Target="this.id"/></Sequence></FaderBarrier></Behavior></Root></BehaviorTree></BehaviorTrees>'''
        return b,a,[q,area,*points]
    def test_authored_roles_order_and_transforms_are_used(self):
        b,a,es=self.source()
        with patch('campaign_training_entry.world_entity',side_effect=lambda archive,e,entities:e):
            r=resolve(b,a,'ask','different_quest',es,None)
        self.assertEqual([p['Pos'] for p in r['positions']],['17,28,39','41,52,63'])
        self.assertEqual([p['role'] for p in r['positions']],['player','tutor'])
        self.assertEqual(r['area_role'],'pit')
    def test_missing_or_ambiguous_point_fails(self):
        b,a,es=self.source();es[1].find('EntityLinks').remove(es[1].find('EntityLinks')[2])
        with self.assertRaisesRegex(ValueError,'two ordered'):resolve(b,a,'ask','different_quest',es,None)
    def test_scene_release_precedes_equipment_and_cancel_disarms(self):
        mission=E.fromstring('<Objects><Entity Name="world" EntityClass="SmartObjectHolder" EntityId="1" EntityGuid="00000001-0000-0000"/><Entity Name="teacher" EntityId="2" EntityGuid="00000002-0000-0000"/></Objects>')
        project=E.fromstring('<Database><Skald><Project Name="world"><Assets/></Project></Skald></Database>')
        entry=E.fromstring('<Database><Skald><Level><Nodes><lesson Name="lesson"/><If Name="lesson_host_stop_workers"><Edge From="lesson_host_active.State" To="Condition"/></If><State Name="lesson_host_active"><Edge From="lesson_host_prepare.B" To="SetTrue"/></State></Nodes></Level></Skald></Database>')
        record={'positions':[dict(role=r,Pos=p,Rotate='1,0,0,0') for r,p in [('player','1,2,3'),('tutor','4,5,6')]]}
        links,guids=stage(mission,project,entry,'lesson',mission[1],record,'native_scene','hero_asset')
        nodes=entry.find('Skald/Level/Nodes')
        self.assertEqual(nodes.find("State[@Name='lesson_host_active']/Edge").get('From'),'lesson_entry_stopped.False')
        self.assertIsNotNone(nodes.find("SceneFinishedWaiter/Edge[@From='lesson_entry_play.AfterPlay']"))
        self.assertIsNotNone(nodes.find("If[@Name='lesson_entry_stopped']/Edge[@From='lesson_host_stop_requested.State'][@To='Condition']"))
        self.assertIsNotNone(nodes.find("If[@Name='lesson_entry_ready']/Edge[@From='lesson_entry_pending.State'][@To='Condition']"))
        player=next(e for e in mission if e.get('Name')=='lesson_entry_player')
        tutor=next(e for e in mission if e.get('Name')=='lesson_entry_tutor')
        self.assertEqual(player.find('EntityLinks/Link').get('Name'),"useAsset['hero_asset']")
        self.assertEqual(tutor.find('EntityLinks/Link').get('TargetGuid'),mission[1].get('EntityGuid'))
        self.assertEqual(len(guids),3)
        self.assertEqual(len(links),5)

    def test_cancel_drains_entry_before_next_invocation(self):
        from campaign_training_host import bind
        from campaign_quest_graph import xml
        from test_campaign_combat_runtime import Graph
        from test_campaign_training_runtime import TrainingGraph
        mission=E.fromstring('<Objects><Entity Name="world" EntityClass="SmartObjectHolder" EntityId="1" EntityGuid="00000001-0000-0000"/><Entity Name="teacher" EntityId="2" EntityGuid="00000002-0000-0000"/></Objects>')
        project=E.fromstring('<Database><Skald><Project Name="world"><Assets/></Project></Skald></Database>')
        entry=E.fromstring('<Database><Skald><Level><Nodes/></Level></Skald></Database>')
        nodes=entry.find('Skald/Level/Nodes')
        lesson=E.SubElement(nodes,'Lesson',Name='lesson')
        worker=E.SubElement(nodes,'EnableBehavior',Name='equipment',Signature='equipment',EventSet='equipment_events')
        dialog=E.SubElement(nodes,'Dialog',Name='talk')
        bind(nodes,lesson,worker,dialogue_nodes=[dialog])
        positions=[dict(role=r,Pos=p,Rotate='1,0,0,0') for r,p in [('player','1,2,3'),('tutor','4,5,6')]]
        stage(mission,project,entry,'lesson',mission[1],{'positions':positions},'native_scene','hero_asset')
        # External scene/AI signals are explicit; no native completion is faked.
        entry.find('Skald/Level').tag='Module'; lesson.tag='Output'
        host=Graph(xml(entry)); life=TrainingGraph()
        life.fire('request');life.fire('arrived');host.fire('lesson.prepare')
        self.assertTrue(host.states['lesson_entry_pending'])
        life.fire('cancel');host.fire('lesson.stop_workers')
        self.assertNotIn('output.workers_stopped',host.events)
        life.fire('request')
        self.assertEqual(life.events.count('output.arrive'),1)
        self.assertFalse(host.states['lesson_host_active'])
        host.fire('lesson_entry_release.OnFinished')
        self.assertIn('output.workers_stopped',host.events)
        self.assertFalse(host.states['lesson_host_active'])
        life.fire('workers_stopped');life.fire('cleanup_done')
        host.fire('lesson_entry_release.OnFinished')
        self.assertEqual(host.events.count('output.workers_stopped'),1)
        self.assertIn('output.canceled',life.events)

if __name__=='__main__':unittest.main()
