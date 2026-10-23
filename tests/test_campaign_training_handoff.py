import sys
from pathlib import Path
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from campaign_training_handoff import resolve


def fixture(actor='teacher',arrival='reach',authorization='agree',completion='finish',priority=41):
    return f'''<BehaviorTrees><BehaviorTree name="walk"><Root>
<OnInit><GraphSearch><LinkDataFilter tag="QuestPlace" condition="$QuestPlace == 'different_court'" Child="place"/></GraphSearch></OnInit>
<Behavior><Sequence><QuestObjectiveCondition quest="" objective="{arrival}" function="IsObjectiveStarted"><Then><Sequence>
<Move destinationSpecification="place"/><SetQuestObjective quest="" objective="{arrival}" function="CompleteObjective"/>
</Sequence></Then></QuestObjectiveCondition><CallBehavior Target="place" BehaviorName="use"/></Sequence></Behavior>
</Root></BehaviorTree><BehaviorTree name="controller"><Variables><Variable name="result" type="duel:duelResult"/></Variables><Root><Behavior><Sequence>
<InstantSendMessageToNPC target="t_actors[{actor}]" type="daycycle:change" values="name('walk'),once(true),priority({priority}),immediate(true)"/>
<ProcessMessage variable="event"><IfCondition condition="$event.State == $enum:ObjectiveState.Started &amp; $event.ObjectiveName == '{authorization}'"><Sequence>
<InstantSendMessageToNPC target="t_actors[{actor}]" type="daycycle:change" values="name('teach'),once(true),priority({priority+2}),immediate(true)"/>
</Sequence></IfCondition></ProcessMessage>
<ProcessMessage variable="result"><QuestObjectiveCondition quest="" objective="{completion}" function="IsObjectiveCompleted"><Else>
<SetQuestObjective quest="" objective="{completion}" function="CompleteObjective"/></Else></QuestObjectiveCondition></ProcessMessage>
</Sequence></Behavior></Root></BehaviorTree></BehaviorTrees>'''.encode()


class TrainingHandoffTests(unittest.TestCase):
    def test_arbitrary_source_actor_objectives_place_and_priority(self):
        for actor,a,b,c,p in [('teacher','reach','agree','finish',41),('instructor','arrived_here','accept_lesson','passed',73)]:
            result=resolve(fixture(actor,a,b,c,p),'walk','teach')
            self.assertEqual(result['actor_role'],actor)
            self.assertEqual(result['objectives'],dict(arrival=a,authorization=b,completion=c))
            self.assertEqual(result['priority'],p+2)
            self.assertEqual(result['arrival']['place_role'],'different_court')
            self.assertEqual(result['speed'],'Slow')

    def test_mismatched_actor_or_conditional_policy_is_rejected(self):
        blob=fixture()
        changed=blob.replace(b'name(\'teach\'),once(true)',b'name(\'teach\'),once(false)')
        with self.assertRaises(ValueError):resolve(changed,'walk','teach')
        changed=blob.replace(b"ObjectiveState.Started",b"ObjectiveState.Completed")
        with self.assertRaises(ValueError):resolve(changed,'walk','teach')

    def test_missing_or_ambiguous_completion_fails_closed(self):
        blob=fixture()
        with self.assertRaises(ValueError):resolve(blob.replace(b'duel:duelResult',b'unknown'),'walk','teach')
        event=blob[blob.index(b'<ProcessMessage variable="result">'):blob.index(b'</ProcessMessage>',blob.index(b'<ProcessMessage variable="result">'))+len(b'</ProcessMessage>')]
        with self.assertRaises(ValueError):resolve(blob.replace(event,event+event),'walk','teach')

if __name__=='__main__':unittest.main()
