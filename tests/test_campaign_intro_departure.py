import sys
from pathlib import Path
import unittest
import xml.etree.ElementTree as E
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from campaign_intro_departure import plan,emit
from setup_quest_invitation import bind_quest
from test_campaign_behavior import catalog

SOURCE=b'''<BehaviorTrees><BehaviorTree name="dispatch"><Root>
<InstantSendMessageToNPC target="$t_actors['guest']" type="daycycle:change" values="name('leave'),once(true),immediate(true),priority(61)"/>
</Root></BehaviorTree><BehaviorTree name="leave"><Root><OnInit>
<LinkDataFilter tag="QuestPlace" condition="$QuestPlace == 'destination'" Child="spot"/>
</OnInit><Behavior><Sequence>
<QuestObjectiveCondition quest="" objective="arrived" function="IsObjectiveStarted"><Then><Sequence>
<Move destinationSpecification="spot" speed="Walk" stopWithinDistance="1.2" successDistance="3"/>
<SetQuestObjective quest="" objective="arrived" function="CompleteObjective"/>
</Sequence></Then></QuestObjectiveCondition>
<CallBehavior Target="spot" BehaviorName="use"/>
</Sequence></Behavior></Root></BehaviorTree></BehaviorTrees>'''


class DepartureTests(unittest.TestCase):
    def test_source_movement_acknowledged_before_indefinite_stance(self):
        source=plan(SOURCE,'leave')
        self.assertEqual((source['objective'],source['place_role'],source['priority']),('arrived','destination',61))
        self.assertEqual(source['actor_role'],'guest')
        files=emit('generic_departure',source,catalog())
        tree=E.fromstring(files['AI/generic_departure.xml'])
        seq=tree.find('.//Behavior/Sequence')
        move,callback=list(seq.find('IfCondition/Sequence'))
        self.assertEqual((move.tag,callback.tag),('Move','Callback_empty'))
        self.assertEqual(move.get('stopWithinDistance'),'1.2')
        self.assertEqual(move.get('destinationSpecification'),'$workPlace')
        self.assertEqual(callback.get('EventName'),"'Success'")
        self.assertIsNotNone(seq.find('EntityContextElement/CallBehavior'))
        self.assertIsNone(tree.find('.//SetSpatialInfo'))
        self.assertIsNone(tree.find('.//Wait'))
        for old,new in [(b'function="CompleteObjective"',b'function="StartObjective"'),
                        (b'Target="spot"',b'Target="other"'),(b'once(true)',b'once(false)'),
                        (b"$t_actors['guest']",b'__player')]:
            with self.assertRaises(ValueError):plan(SOURCE.replace(old,new),'leave')

    def test_invitation_handoff_uses_persistent_quest_state_and_not_failure(self):
        entry=E.fromstring('''<Database><Skald><Level><Definitions/><Nodes>
        <EnableBehavior Name="intro_enable"><Edge From="old_active.bool" To="IsActive"/></EnableBehavior>
        </Nodes></Level></Skald></Database>''')
        source=dict(plan(SOURCE,'leave'),parent_quest='parent',parent_objective='training')
        quest=b'<Database><Skald><Quest Name="child"/></Skald></Database>'
        bind_quest(entry,quest,source,'intro','depart')
        nodes=entry.find('Skald/Level/Nodes');child=nodes.find('child')
        self.assertEqual([e.get('From') for e in child.findall("Edge[@To='complete_arrived']")],['depart_enable.Success'])
        self.assertFalse([e for e in child.findall('Edge') if '.Fail' in e.get('From')])
        enable=nodes.find("EnableBehavior[@Name='depart_enable']")
        self.assertEqual(enable.find("Edge[@To='arrivalPending']").get('From'),'child.arrived_Started')
        self.assertIsNone(nodes.find('GameStart'))
        self.assertIsNotNone(nodes.find('Watch'))
        self.assertIsNone(entry.find('.//Timer'))
        with self.assertRaises(ValueError):bind_quest(entry,quest,source,'intro','depart')

if __name__=='__main__':unittest.main()
