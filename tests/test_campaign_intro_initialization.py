import copy
import sys
import unittest
from pathlib import Path
import xml.etree.ElementTree as E

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from campaign_intro_initialization import contract, bind
from campaign_intro_activity import plan, emit
from test_campaign_intro_activity import SOURCE


def source():
    r=E.fromstring(SOURCE)
    t=r.find("BehaviorTree[@name='intro']")
    E.SubElement(E.SubElement(t,'Variables'),'Variable',name='firstPhase',type='_int',isPersistent='1')
    init=t.find('Root/OnInit'); init.clear()
    seq=E.SubElement(init,'Sequence')
    E.SubElement(seq,'LinkDataFilter',tag='QuestPlace',condition="$QuestPlace == 'seat'",Child='spot')
    E.SubElement(seq,'LinkDataFilter',tag='QuestPlace',condition="$QuestPlace == 'arrival'",Child='start')
    first=E.SubElement(E.SubElement(seq,'IfCondition',condition='$firstPhase < 7',failOnCondition='false'),'Sequence')
    for tag,attrs in [
        ('DisablePerception',dict(Perceptor='true',Perceptible='true',ToWhom='')),
        ('SetTemporarySuperfaction',dict(soul='this.id',superfaction='Civilians')),
        ('GetSpatialInfo',dict(In='start',Out='pose',What='Transform')),
        ('SetSpatialInfo',dict(In='this.id',Val='pose',What='Transform')),
        ('EnablePerception',dict(Perceptor='true',Perceptible='true',ToWhom='')),
        ('Expression',dict(expressions='$firstPhase = 7,')),
        ('ExecuteLua',dict(code='validated by faction adapter'))]:E.SubElement(first,tag,**attrs)
    return r


class InitializationTests(unittest.TestCase):
    def test_delayed_start_has_source_arrival_not_spawn_or_seat(self):
        p=plan(E.tostring(source()),'intro')
        self.assertEqual(p['initialization'],dict(version=1,phase='firstPhase',threshold=7,arrival_role='arrival'))
        files=emit('generic_worker',p)
        tree=E.fromstring(files['AI/generic_worker.xml']).find('BehaviorTree')
        first=tree.find('Root/OnInit/Sequence/IfCondition/Sequence')
        self.assertEqual(first.find('GetSpatialInfo').get('In'),'$arrivalPlace')
        self.assertEqual(first.find('SetSpatialInfo').get('In'),'$this.id')
        self.assertEqual(tree.find('.//CallBehavior').get('Target'),'$workPlace')
        self.assertEqual([n.tag for n in first][:4],['GetSpatialInfo','DisablePerception','SetSpatialInfo','EnablePerception'])
        self.assertIsNone(tree.find('.//ExecuteLua'))
        self.assertIsNone(tree.find('.//SetTemporarySuperfaction'))
        signature=E.fromstring(files['Libs/Tables/ai/Signature__generic_worker.xml'])
        self.assertEqual({n.get('name') for n in signature.iter('VariableInfo')},{'arrivalPlace','workPlace'})

    def test_persistent_guard_does_not_relocate_on_second_entry(self):
        tree=E.fromstring(emit('worker',plan(E.tostring(source()),'intro'))['AI/worker.xml']).find('BehaviorTree')
        self.assertEqual(tree.find("Variables/Variable[@name='firstPhase']").get('isPersistent'),'1')
        guard=tree.find('Root/OnInit/Sequence/IfCondition')
        self.assertEqual(guard.get('condition'),'$firstPhase < 7')
        self.assertEqual(guard.get('failOnCondition'),'false')
        # Exercise the emitted subset: displaced actor is placed on first entry;
        # saved phase and a later different position survive re-entry.
        phase=0;pos='displaced'
        def enter():
            nonlocal phase,pos
            if phase < int(guard.get('condition').split('<')[1]):
                for n in guard.find('Sequence'):
                    if n.tag=='SetSpatialInfo':pos='arrival'
                    if n.tag=='Expression':phase=int(n.get('expressions').split('=')[1])
        enter(); self.assertEqual((phase,pos),(7,'arrival'))
        pos='later saved position';enter();self.assertEqual(pos,'later saved position')

    def test_reject_changed_initializer_instead_of_dropping_it(self):
        for tag,key,value in [('Variable','isPersistent','0'),('SetSpatialInfo','In','other'),
                              ('GetSpatialInfo','What','Position'),('Expression','expressions','$firstPhase = 9'),
                              ('EnablePerception','Perceptor','false')]:
            r=source();t=r.find("BehaviorTree[@name='intro']");t.find('.//'+tag).set(key,value)
            with self.subTest(tag=tag),self.assertRaises(ValueError):contract(t)

    def test_binding_is_idempotent_and_preserves_unrelated_objects(self):
        objects=E.fromstring('<Objects><Entity Name="project" EntityGuid="00000001-0000-0000" EntityId="1"><EntityLinks/></Entity><Entity Name="other" EntityId="2"/></Objects>')
        project=E.fromstring('<Project><Assets/></Project>')
        entry=E.fromstring('<Level><Nodes><EnableBehavior Name="sample_enable"/></Nodes></Level>')
        placement=dict(source_place_guid='0000000000000003',placement=dict(Pos='1,2,3',Rotate='1,0,0,0'))
        before=E.tostring(objects[1]);links=[]
        self.assertTrue(bind(objects,project,objects[0],entry,links,'sample',placement))
        self.assertEqual(project.find("Assets/*[@Name='sample_arrival']").tag,'TagPointAsset')
        self.assertFalse(bind(objects,project,objects[0],entry,links,'sample',placement))
        bind(objects,project,objects[0],entry,[],'sample',placement,validate=True)
        self.assertEqual(len(links),1);self.assertEqual(E.tostring(objects[1]),before)
        objects[-1].set('Pos','9,9,9')
        with self.assertRaisesRegex(ValueError,'conflicts'):bind(objects,project,objects[0],entry,[],'sample',placement)

    def test_invalid_generic_asset_is_rejected_and_migrated(self):
        objects=E.fromstring('<Objects><Entity Name="project" EntityGuid="00000001-0000-0000" EntityId="1"><EntityLinks/></Entity></Objects>')
        project=E.fromstring('<Project><Assets/></Project>')
        entry=E.fromstring('<Level><Nodes><EnableBehavior Name="sample_enable"/></Nodes></Level>')
        placement=dict(source_place_guid='0000000000000003',placement=dict(Pos='1,2,3',Rotate='1,0,0,0'))
        bind(objects,project,objects[0],entry,[],'sample',placement)
        asset=project.find("Assets/*[@Name='sample_arrival']")
        asset.tag='EntityAsset'
        with self.assertRaisesRegex(ValueError,'expected TagPointAsset'):
            bind(objects,project,objects[0],entry,[],'sample',placement,validate=True)
        self.assertTrue(bind(objects,project,objects[0],entry,[],'sample',placement))
        self.assertEqual(asset.tag,'TagPointAsset')
        self.assertFalse(bind(objects,project,objects[0],entry,[],'sample',placement))


if __name__=='__main__':unittest.main()
