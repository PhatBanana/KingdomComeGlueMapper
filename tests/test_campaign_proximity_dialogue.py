import sys
from pathlib import Path
import unittest
import xml.etree.ElementTree as E
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from campaign_proximity_dialogue import parse, install


def source():
    tree=E.Element('BehaviorTree',name='arbitrary')
    variables=E.SubElement(tree,'Variables');E.SubElement(variables,'Variable',name='range',values='7.5')
    root=E.SubElement(tree,'Root')
    gate=E.SubElement(root,'QuestObjectiveGate',questName='someQuest',objectiveName='someObjective',objectiveState='Started',NegateTo='false',RunLogic='KeepRunning')
    seq=E.SubElement(gate,'Sequence')
    def wait(parent,value):E.SubElement(parent,'Wait',duration=value,timeType='GameTime',doFail='false',variation='',skipInLOD='false')
    def distance(parent,value,negation='false'):
        return E.SubElement(parent,'DistanceGate',Origin='',ReferencePt='__player',Low=value,High=value,Negation=negation,OpenInMiddle='false',RunLogic='KeepRunning')
    wait(seq,'3s');p=E.SubElement(seq,'Parallel',successMode='Any',failureMode='Any')
    lanes=E.SubElement(distance(p,'12'),'Parallel',successMode='All',failureMode='Any')
    loop=E.SubElement(lanes,'Loop',count='-1');ls=E.SubElement(loop,'Sequence')
    d=distance(ls,'$range')
    E.SubElement(d,'SendMessageToNPC',target='this.id',type='dialog:monologRequest',values='alias(otherGreeting),lookAtId($__player)',timeType='GameTime',timeoutType='OnProcessed',timeout='-1',answer='')
    wait(ls,'8s');E.SubElement(distance(p,'60','true'),'Success');wait(seq,'-1')
    return tree


class ProximityTests(unittest.TestCase):
    def test_source_parameters_and_native_runtime_connections(self):
        plan=parse(source(),'someObjective')
        self.assertEqual(plan['lanes'][0]['distance']['radius'],7.5)
        blob=b'<Database><Skald><Quest Name="someQuest"><Nodes><State Name="objective_91"/><Output Name="Output"><Edge From="objective_91.Started" To="someObjective_Started"/></Output></Nodes></Quest></Skald></Database>'
        guid='11111111-2222-3333-4444-555555555555'
        converted=install(blob,plan,guid,guid)
        r=E.fromstring(converted)
        self.assertIsNotNone(r.find(".//Timer/Constant[@Value='3s']"))
        self.assertIsNotNone(r.find(".//Timer/Constant[@Value='8s']"))
        self.assertIsNotNone(r.find(".//Function/Constant[@Value='otherGreeting']"))
        self.assertIsNotNone(r.find(".//State/Edge[@From='gm_proximity_lane_0_retry.OnFinished'][@To='SetTrue']"))
        self.assertEqual(len(r.findall('.//DistanceTrigger')),3)
        with self.assertRaisesRegex(ValueError,'already installed'):install(converted,plan,guid,guid)

    def test_unknown_effects_and_hysteresis_are_not_dropped(self):
        t=source();E.SubElement(t.find('.//Loop/Sequence'),'SetQuest')
        with self.assertRaises(ValueError):parse(t,'someObjective')
        t=source();t.find('.//Loop//DistanceGate').set('High','9')
        with self.assertRaisesRegex(ValueError,'hysteresis'):parse(t,'someObjective')
        t=source();t.find('.//SendMessageToNPC').set('values','alias(otherGreeting),priority(99)')
        with self.assertRaises(ValueError):parse(t,'someObjective')


if __name__=='__main__':unittest.main()
