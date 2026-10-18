import copy
import sys
import unittest
import xml.etree.ElementTree as E
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'tools'))
from campaign_dialogue_requests import lower, plans


def node(op, children=(), **attrs):
    return dict(op=op, attributes=attrs, children=list(children))


def fixture():
    def tree(n): return dict(root=node('Root', [node('Behavior',[n])]))
    request=node('IfCondition',[node('InstantSendMessageToNPC',target='this.id',type='cutscene',values="alias('delivery'), state($enum:cutsceneState.doStart), dialogFadeIn(true)")],condition="($event.ObjectiveName == 'deliver') & ($event.State == $enum:ObjectiveState.Started)")
    update=tree(node('ProcessMessage',[request],inbox='QuestMailbox',condition='',variable='event'))
    patch=tree(node('InstantSendMessageToNPC',target='t_actors[vendor]',type='daycycle:change',values="add(true),handle('delivery_task'),name('offer'),immediate(true),once(true),sourceId($this.id),priority(42),criticalPriority($enum:daycyclePatchCriticalPriority.cutscene_dialogFadingIn)"))
    expression=node('Expression',expressions="$t_dialogParticipants[0] = $__player, $t_dialogParameters.alias = 'offer_delivery', $t_dialogParameters.enableGreeting = false, $t_dialogParameters.enableEnding = false, $t_dialogParameters.waitOnReceiverDialogEnd = false,")
    loop=node('LoopUntil',[node('IncludeTree',File='final/dialogUtils.xml',Name='dialogInitiator')],until='Success',attemptCount='0')
    offer=tree(node('QuestObjectiveCondition',[node('Then',[node('Sequence',[expression,loop])])],quest='$__object.name',objective='deliver',function='IsObjectiveStarted'))
    model=dict(quest='sample',behavior_entry='libs/ai/sample.xml',tables={'quest_objective':dict(rows=[dict(objective_name='deliver',objective_id='71')])},behavior_documents={'libs/ai/sample.xml':dict(trees={'onUpdate':update,'delivery':patch,'offer':offer})},controller_registration=dict(entry_points=[dict(kind='behavior_callback',name='_cutscene_delivery',file='sample.xml',tree='delivery'),dict(kind='behavior_callback',name='offer',file='sample.xml',tree='offer')]))
    files={'Quests/q.xml':b'<Database><Skald><Quest Name="sample"><Ports/><Nodes><State Name="objective_71"/></Nodes></Quest></Skald></Database>',
      'Quests/level.xml':b'<Database><Skald><Level Name="region"><Assets/><Nodes><sample Name="quest"/><delivery Name="delivery"/></Nodes><Definitions><Definition File="dialog.xml"/></Definitions></Level></Skald></Database>',
      'Quests/dialog.xml':b'<Database><Skald><FaderDialog Name="delivery"><Ports/><Dialogue Initiator="Player" Priority="2"><Decision Alias="offer_delivery"/></Dialogue></FaderDialog></Skald></Database>'}
    bindings=dict(references={"t_actors['vendor']":['seller']},bindings=[dict(name='seller',asset_type='SoulAsset',attributes=dict(SharedSoulGuids='actor-soul'))])
    return files,model,bindings


class RequestTests(unittest.TestCase):
    def test_source_event_and_participant_preserved(self):
        f,m,b=fixture(); original=copy.deepcopy(f)
        changes,report=lower(f,m,b)
        self.assertEqual(f,original)
        self.assertEqual(report[0]['schedule_priority'],42)
        self.assertIn(b'objective_71.OnStarted',changes['Quests/q.xml'])
        level=E.fromstring(changes['Quests/level.xml'])
        self.assertIsNotNone(level.find(".//SceneFinishedWaiter/Edge[@From='quest.source_request_deliver']"))
        self.assertIsNotNone(level.find(".//SoulAsset[@SharedSoulGuids='actor-soul']"))
        self.assertIn(b'<ForcedDialog',changes['Quests/dialog.xml'])
        f.update(changes)
        self.assertEqual(lower(f,m,b)[0],{})

    def test_missing_actor_dependency_fails(self):
        f,m,b=fixture();b['references']={}
        with self.assertRaisesRegex(ValueError,'actor dependency'): lower(f,m,b)

    def test_additional_behavior_is_not_silently_flattened(self):
        f,m,b=fixture()
        t=m['behavior_documents']['libs/ai/sample.xml']['trees']['delivery']['root']['children'][0]
        t['children'].append(node('ExecuteLua',code='ExtraAction()'))
        self.assertEqual(plans(m),[])

    def test_unselected_conversation_remains_untouched(self):
        f,m,b=fixture();del f['Quests/dialog.xml']
        self.assertEqual(lower(f,m,b),({},[]))
