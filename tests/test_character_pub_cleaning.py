import copy
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
import xml.etree.ElementTree as E

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'tools'))
import character_pub_cleaning as work
from campaign_entity_links import native_guid
from character_work_pool import identity
from upgrade_map import xml


class PubCleaningTests(unittest.TestCase):
    def source(self):
        pub = E.fromstring('''<BehaviorTrees><BehaviorTree name="wiping"><Root>
          <GraphSearch Origin="__area.id" depth="1" EdgePruning="parent" includeOrigin="false">
            <CategoryFilter categories="pubTable"/><Nodalyzer Quantifiers="ForAll"/>
          </GraphSearch><CallBehavior BehaviorName="wiping"/>
        </Root></BehaviorTree></BehaviorTrees>''')
        leaf = E.fromstring('''<BehaviorTrees><BehaviorTree name="wiping"><Root>
          <Semaphore SemaphoreName="usePubTable" SemaphoreCount="1"/>
          <GetHelper helperName="Place1"/><GetAnimationHelperData fragment="Bartender_CleaningTable"/>
          <PlayAnimation animation="Bartender_CleaningTable"/>
        </Root></BehaviorTree></BehaviorTrees>''')
        return pub, leaf

    def test_changed_source_selection_or_alignment_is_rejected(self):
        work.source_contract(*self.source())
        for index, tag, key, value in ((0, 'GraphSearch', 'depth', '2'),
                (0, 'CategoryFilter', 'categories', 'Seat'),
                (1, 'GetHelper', 'helperName', 'Place2'),
                (1, 'Semaphore', 'SemaphoreCount', '2'),
                (1, 'PlayAnimation', 'animation', 'idle')):
            with self.subTest(tag=tag):
                source = self.source(); source[index].find('.//'+tag).set(key,value)
                with self.assertRaises(ValueError): work.source_contract(*source)

    def fixture(self):
        m = E.Element('Objects')
        actor = E.SubElement(m,'Entity',Name='worker',EntityId='1',EntityGuid=native_guid(1),EntityClass='NPC_Female')
        entry = dict(behavior=dict(tree_file=work.SOURCE[0],tree_name=work.SOURCE[1]),
            arrival=dict(EntityId='2',EntityGuid='0000000000000002',Pos='1,2,3'))
        job = E.SubElement(m,'Entity',Name='gm_schedule_worker_2',EntityId='2',EntityClass='SmartObjectHolder',
            EntityGuid=identity('schedule-arrival/'+actor.get('EntityGuid')+'/'+entry['arrival']['EntityGuid']))
        E.SubElement(job,'Properties',guidSmartObjectType='existing-sweeping')
        s = E.Element('database');rows=E.SubElement(s,'Schedulers')
        owner=E.SubElement(rows,'C_SmartHub',EntityGuid='1'); links=E.SubElement(owner,'Links')
        edge=E.SubElement(links,'S_ActivityLink',TargetGuid=str(work.guid_value(job.get('EntityGuid'))),PositioningDelegate='0')
        E.SubElement(edge,'Parameters',Priority='0',Privileged='false',BehaviorName='use',TimeOfDayStart='480',TimeOfDayEnd='1200')
        activity=copy.deepcopy(edge); activity.find('Parameters').set('TimeOfDayStart','0');activity.find('Parameters').set('TimeOfDayEnd','1440')
        contact=dict(EntityGuid='0000000000000003',Pos='4,5,6',Rotate='1,0,0,0')
        files={'objects_mission0.xml':xml(m),'tables/ai/scheduler.xml':xml(s),'waitinglinks.xml':b'<StaticLinksInfo version="1"><WaitingLinks/></StaticLinksInfo>'}
        return files,entry,activity,contact

    def test_existing_clock_sweeping_and_shared_identity_survive_repeat(self):
        files,entry,activity,contact=self.fixture()
        with patch.object(work,'native_action',return_value=(None,{'female'})), \
             patch('character_city_work.native_contract',return_value=(None,activity,None)), \
             patch.object(work,'resolve',return_value=[contact]):
            updated,report=work.upgrade_files(files,{'worker':[entry]},None,None,None,None)
            repeated,_=work.upgrade_files(updated,{'worker':[entry]},None,None,None,None)
        self.assertEqual(updated,repeated)
        self.assertEqual(report[0]['intervals'],[(480,1200)])
        mission=E.fromstring(updated['objects_mission0.xml'])
        self.assertEqual(mission.find("Entity[@Name='gm_schedule_worker_2']/Properties").get('guidSmartObjectType'),'existing-sweeping')
        self.assertEqual(len([e for e in mission if e.get('Name','').startswith('gm_pub_cleaning_')]),1)
        self.assertFalse(report[0]['runtime_verified'])

    def test_unavailable_gender_gets_pending_not_a_fake_animation(self):
        files,entry,activity,contact=self.fixture()
        mission=E.fromstring(files['objects_mission0.xml']);mission[0].set('EntityClass','NPC')
        files['objects_mission0.xml']=xml(mission)
        with patch.object(work,'native_action',return_value=(None,{'female'})), \
             patch('character_city_work.native_contract',return_value=(None,activity,None)), \
             patch.object(work,'resolve') as resolve:
            updated,report=work.upgrade_files(files,{'worker':[entry]},None,None,None,None)
        resolve.assert_not_called()
        self.assertEqual(report[0]['job'],'pub_cleaning_pending')
        self.assertFalse(any(e.get('Name','').startswith('gm_pub_cleaning_') for e in E.fromstring(updated['objects_mission0.xml'])))

    def test_modified_shared_resource_is_rejected(self):
        _,_,_,contact=self.fixture(); mission=E.fromstring('<Objects><Entity EntityId="1"/></Objects>')
        resource,_=work.register(mission,contact)
        self.assertIs(resource,work.register(mission,contact)[0])
        resource.set('Pos','9,9,9')
        with self.assertRaises(ValueError):work.register(mission,contact)


if __name__=='__main__': unittest.main()
