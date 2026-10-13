import sys
from pathlib import Path
import unittest
from unittest.mock import patch
import xml.etree.ElementTree as E
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from character_schedule_world import bind_arrivals,arrival_resources
from campaign_entity_links import native_guid,append_links


class ScheduleWorldTests(unittest.TestCase):
    def fixture(self):
        g1,g2,g3=[native_guid(i) for i in (1,2,3)]
        files={'objects_mission0.xml':f'<Objects><Entity Name="person" EntityId="1" EntityGuid="{g1}"/>'
            f'<Entity Name="gm_person_idle_person" EntityId="2" EntityGuid="{g2}"/></Objects>'.encode(),
            'tables/ai/scheduler.xml':b'<database><Schedulers><C_SmartHub EntityGuid="1"><Links>'
            b'<S_ActivityLink TargetGuid="3" PositioningDelegate="2"><Parameters BehaviorName="schedulerWait"/></S_ActivityLink>'
            b'</Links></C_SmartHub><C_SmartHub EntityGuid="3"/></Schedulers></database>',
            'waitinglinks.xml':append_links(None,[(g1,g2,'_,schedulerWait'),(g1,g2,'home')])}
        schedule={'person':[dict(arrival=dict(EntityId='9',EntityGuid='19',Pos='50,60,70'),
            activity='work',start_minute=300,end_minute=720,behavior=dict(tree_name='work'))]}
        native=E.fromstring('<S_ActivityLink PositioningDelegate="0"><Parameters Priority="0" BehaviorOverride="false"/></S_ActivityLink>')
        return files,schedule,native

    def test_source_arrival_clock_and_links_replace_only_idle(self):
        files,schedule,native=self.fixture()
        with patch('character_schedule_world.native_wait_activity',return_value=(native,None)):
            result,report=bind_arrivals(files,schedule,None)
        root=E.fromstring(result['objects_mission0.xml']);job=list(root)[-1]
        self.assertEqual(job.get('Pos'),'50,60,70')
        self.assertEqual(job.get('EntityClass'),'SmartObjectHolder')
        link=E.fromstring(result['tables/ai/scheduler.xml']).find('Schedulers/C_SmartHub/Links/S_ActivityLink')
        self.assertEqual(link.get('PositioningDelegate'),'0')
        self.assertEqual(link.find('Parameters').get('TimeOfDayStart'),'300')
        self.assertEqual(link.find('Parameters').get('TimeOfDayEnd'),'720')
        self.assertIn(b'>home<',result['waitinglinks.xml'])
        self.assertNotIn(b'_,schedulerWait',result['waitinglinks.xml'])
        self.assertTrue(report[0]['activity_pending'])
        self.assertIn(b'_,schedulerWait',files['waitinglinks.xml'])

    def test_never_overwrites_existing_authored_job(self):
        files,schedule,native=self.fixture()
        files['tables/ai/scheduler.xml']=files['tables/ai/scheduler.xml'].replace(b'schedulerWait',b'shopWork')
        with patch('character_schedule_world.native_wait_activity',return_value=(native,None)):
            with self.assertRaisesRegex(ValueError,'non-baseline'):bind_arrivals(files,schedule,None)

    def test_arrival_executes_native_move_without_person_or_coordinates(self):
        resources=arrival_resources()
        tree=E.fromstring(resources['AI/gluemapper/schedule_arrival.xml'])
        move=tree.find('.//Move')
        self.assertEqual(move.get('destinationSpecification'),'$__object.id')
        self.assertEqual(move.get('speed'),'Walk')
        self.assertIsNone(tree.find('.//Teleport'))


if __name__=='__main__':unittest.main()
