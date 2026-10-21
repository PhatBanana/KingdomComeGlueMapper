import copy
from pathlib import Path
import sys
import tempfile
import unittest
import xml.etree.ElementTree as E
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'tools'))
import character_city_benches as benches
import character_city_work as city
from campaign_entity_links import guid_value, native_guid, append_links
from character_person_activity import validate_scheduler_targets
import test_character_city_work as fixtures


class CityBenchTests(unittest.TestCase):
    def fixture(self, root):
        fixtures.CityWorkTests().contract_fixture(root)
        with zipfile.ZipFile(root/'Data/Tables.pak', 'a') as z:
            z.writestr(benches.TABLE, '''<database><SmartEntityTemplate DatabaseId="seat">
              <Resources><Resource Name="use" MaxInstances="1"/></Resources>
              <BehaviorTemplates><SmartBehaviorTemplate Name="use" InitialState="Enabled" Resource="use">
                <TreeLocation FileName="seat.xml" TreeName="use"/>
              </SmartBehaviorTemplate></BehaviorTemplates></SmartEntityTemplate></database>''')
        with zipfile.ZipFile(root/'Data/Scripts.pak', 'a') as z:
            z.writestr('AI/seat.xml', '''<BehaviorTrees><BehaviorTree name="use"><Root>
              <StanceElement smartObject="$__object.id" stance="sitting">
                <EntityContextElement context="speech_readyForSwitchDialog"/>
                <Wait duration="'15s'"/><InstantSynchronize/>
              </StanceElement></Root></BehaviorTree></BehaviorTrees>''')
        path = root/'Data/Levels/trosecko/level.pak'
        with zipfile.ZipFile(path) as z:
            mission=E.fromstring(z.read('objects_mission0.xml'))
            scheduler=E.fromstring(z.read('tables/ai/scheduler.xml'))
        seat=E.SubElement(mission,'Entity',EntityClass='StanceSmartObject',EntityGuid=native_guid(7))
        E.SubElement(seat,'Properties',guidSmartObjectType='seat')
        rows=scheduler.find('Schedulers'); E.SubElement(rows,'C_SmartHub',EntityGuid='7')
        link=copy.deepcopy(rows[0].find('Links/S_ActivityLink'));link.set('TargetGuid','7')
        link.find('Parameters').set('AllowedGenders','0');rows[0].find('Links').append(link)
        with zipfile.ZipFile(path,'w') as z:
            z.writestr('objects_mission0.xml',E.tostring(mission))
            z.writestr('tables/ai/scheduler.xml',E.tostring(scheduler))
        files,schedules=fixtures.CityWorkTests().prepared()
        mission=E.fromstring(files['objects_mission0.xml'])
        seat=E.SubElement(mission,'Entity',Name='gm_bench_20_0_StanceSmartObject',
            EntityClass='StanceSmartObject',EntityId='20',EntityGuid=native_guid(200),Pos='1,2,3')
        E.SubElement(seat,'Properties',guidSmartObjectType='seat',soclass_SmartObjectHelpers='Sit_1Place_Bench_Low')
        files['objects_mission0.xml']=E.tostring(mission)
        work=schedules['person'][0]['city_work']
        work.update(benches=[dict(EntityId='20',EntityGuid='20',Pos='1,2,3')],benches_resolved=True)
        return files,schedules

    def test_source_uses_only_linked_seats_and_seat_specific_pruning(self):
        root=E.fromstring('''<Objects>
          <Entity EntityId="1"><EntityLinks><Link Name="look" TargetId="2"/>
            <Link Name="parent" TargetId="missing"/><Link Name="" TargetId="3"/>
            <Link Name="" TargetId="2"/></EntityLinks></Entity>
          <Entity EntityId="2" EntityGuid="2" EntityClass="SmartObjectHolder" Pos="1,2,3">
            <Properties sWH_AI_EntityCategory="Seat" soclasses_SmartObjectHelpers="Bench_Low"/>
          </Entity><Entity EntityId="3" EntityClass="TagPoint"/>
          <Entity EntityId="4" EntityGuid="4" EntityClass="SmartObjectHolder">
            <Properties sWH_AI_EntityCategory="Seat" soclasses_SmartObjectHelpers="Bench_Low"/>
          </Entity></Objects>''')
        program=b'''<BehaviorTrees><BehaviorTree name="CityWalk"><Root>
          <GraphSearch Origin="startPoint" depth="1" EdgePruning="parent,inventory" includeOrigin="false" AllowedEdges="">
            <CategoryFilter categories="Seat"/><HasBehaviorFilter BehaviorList="use" FilterChoice="Requestable"/>
            <Nodalyzer/></GraphSearch></Root></BehaviorTree></BehaviorTrees>'''
        reader=lambda *_: {'city':{'data':program}}
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'source.pak'
            with zipfile.ZipFile(path,'w') as z:z.writestr('objects_mission0.xml',E.tostring(root))
            with zipfile.ZipFile(path) as z:
                selected=benches.resolve(root[0],list(root),z,Path(tmp),reader)
                self.assertEqual([s['EntityId'] for s in selected],['2'])
                program=program.replace(b'depth="1"',b'depth="2"')
                with self.assertRaisesRegex(ValueError,'selection contract'):
                    benches.resolve(root[0],list(root),z,Path(tmp),reader)

    def test_fresh_build_shares_seat_and_keeps_walks_and_source_hours(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);files,schedules=self.fixture(root)
            mission=E.fromstring(files['objects_mission0.xml']);scheduler=E.fromstring(files['tables/ai/scheduler.xml'])
            job,waiting,report=city.bind(mission,scheduler,'person',schedules['person'][0],root)
            row=scheduler.find("Schedulers/C_SmartHub[@EntityGuid='"+str(guid_value(job.get('EntityGuid')))+"']")
            self.assertEqual(len(row.find('Links')),3)
            for l in row.find('Links'):
                self.assertEqual((l.find('Parameters').get('TimeOfDayStart'),l.find('Parameters').get('TimeOfDayEnd')),('300','720'))
            self.assertEqual(len(report['benches']),1);self.assertNotIn('bench visits',report['pending'])
            self.assertFalse(report['runtime_verified'])
            self.assertEqual(len(scheduler.findall("Schedulers/C_SmartHub[@EntityGuid='200']")),1)
            self.assertIn((job.get('EntityGuid'),native_guid(200),'_,use'),waiting)
            validate_scheduler_targets(scheduler)
            # Another generic actor uses exactly the same seat resource.
            other=copy.deepcopy(job);other.set('Name','gm_schedule_other_9');other.set('EntityGuid',native_guid(100))
            other.set('EntityId','100');other.remove(other.find('EntityLinks'));mission.append(other)
            rows=scheduler.find('Schedulers');E.SubElement(rows,'C_SmartHub',EntityGuid='100')
            owner=E.SubElement(rows,'C_SmartHub',EntityGuid='101')
            l=E.SubElement(E.SubElement(owner,'Links'),'S_ActivityLink',TargetGuid='100')
            E.SubElement(l,'Parameters',BehaviorName='use',TimeOfDayStart='800',TimeOfDayEnd='1000')
            city.bind(mission,scheduler,'other',schedules['person'][0],root)
            self.assertEqual(len(scheduler.findall("Schedulers/C_SmartHub[@EntityGuid='200']")),1)
            self.assertEqual(len([e for e in mission if e.get('Name','').startswith('gm_bench_')]),1)

    def test_existing_pool_extension_is_idempotent_and_refuses_quest_changes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);files,schedules=self.fixture(root)
            entry=copy.deepcopy(schedules['person'][0]);entry['city_work']['benches']=[]
            mission=E.fromstring(files['objects_mission0.xml']);scheduler=E.fromstring(files['tables/ai/scheduler.xml'])
            job,waiting,_=city.bind(mission,scheduler,'person',entry,root)
            files.update({'objects_mission0.xml':E.tostring(mission),'tables/ai/scheduler.xml':E.tostring(scheduler),
                'waitinglinks.xml':append_links(files['waitinglinks.xml'],waiting)})
            result,reports=city.extend_existing(files,schedules,root)
            again,_=city.extend_existing(result,schedules,root)
            self.assertEqual(result,again)
            old=E.fromstring(files['tables/ai/scheduler.xml']);new=E.fromstring(result['tables/ai/scheduler.xml'])
            self.assertEqual(benches.signature(old.find("Schedulers/C_SmartHub[@EntityGuid='1']")),
                             benches.signature(new.find("Schedulers/C_SmartHub[@EntityGuid='1']")))
            self.assertEqual(len(reports[0]['benches']),1)
            row=new.find("Schedulers/C_SmartHub[@EntityGuid='"+str(guid_value(job.get('EntityGuid')))+"']")
            row.find('Links/S_ActivityLink/Parameters').set('BehaviorName','questActivity')
            changed=dict(result,**{'tables/ai/scheduler.xml':E.tostring(new)})
            with self.assertRaisesRegex(ValueError,'modified or non-owned'):
                city.extend_existing(changed,schedules,root)
            changed_clock=copy.deepcopy(schedules)
            changed_clock['person'][0]['start_minute']=301
            with self.assertRaisesRegex(ValueError,'clock differs'):
                city.extend_existing(result,changed_clock,root)
            changed_mission=E.fromstring(result['objects_mission0.xml'])
            hub=next(e for e in changed_mission if e.get('Name')==job.get('Name'))
            E.SubElement(hub.find('EntityLinks'),'Link',Name='questActivity',TargetGuid=native_guid(200))
            with self.assertRaisesRegex(ValueError,'modified or non-owned'):
                city.extend_existing(dict(result,**{'objects_mission0.xml':E.tostring(changed_mission)}),schedules,root)

    def test_missing_or_nonterminal_seats_and_changed_native_lifecycle_fail(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);files,schedules=self.fixture(root)
            mission=E.fromstring(files['objects_mission0.xml']);scheduler=E.fromstring(files['tables/ai/scheduler.xml'])
            E.SubElement(E.SubElement(scheduler.find('Schedulers'),'C_SmartHub',EntityGuid='200'),'Links')
            with self.assertRaisesRegex(ValueError,'conflicting scheduler'):
                city.bind(mission,scheduler,'person',schedules['person'][0],root)
            mission.remove(next(e for e in mission if e.get('EntityId')=='20'))
            with self.assertRaisesRegex(ValueError,'Missing converted'):
                benches.prepare(mission,schedules['person'][0],root)
            with zipfile.ZipFile(root/'Data/Scripts.pak','w') as z:
                z.writestr('AI/seat.xml','<BehaviorTrees><BehaviorTree name="use"><Root/></BehaviorTree></BehaviorTrees>')
            with self.assertRaisesRegex(ValueError,'completion/interruption'):
                benches.native_contract(root)

    def test_partial_extension_keeps_other_job_reports_and_pending_work(self):
        from profile_population_upgrade import retain_work
        old_city=dict(person='anyone',job='native_city_walk',pending=['bench visits'])
        home=dict(person='anyone',job='home',pending=['cooking'])
        pending=dict(person='anyone',reason='other source work unresolved')
        updated=dict(person='anyone',job='native_city_walk',extension_only=True,pending=['shop browsing'])
        result=retain_work(dict(converted=[old_city,home],pending=[pending]),
                           dict(converted=[updated],pending=[]),['anyone'])
        self.assertEqual(result['converted'],[home,updated])
        self.assertEqual(result['pending'],[pending]);self.assertFalse(result['complete'])


if __name__ == '__main__': unittest.main()
