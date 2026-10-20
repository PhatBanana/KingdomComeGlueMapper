import copy
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
import xml.etree.ElementTree as E
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'tools'))
from character_city_work import resolve, native_contract, bind, TABLE
from character_schedule_world import bind_arrivals, baseline_schedule_names
from character_schedule_jobs import bind_jobs, population_work_supports
from character_person_activity import validate_scheduler_targets
from campaign_entity_links import native_guid, append_links, guid_value
import test_character_schedule_world as schedule_fixture


class CityWorkTests(unittest.TestCase):
    def source(self, directory):
        path = Path(directory)/'source.pak'
        # A look point must be excluded even though it has the same entity
        # class as destinations. Missing pruned edges need no imported target.
        root = E.fromstring('''<Objects>
          <Entity EntityId="1" EntityGuid="1" EntityClass="TagPoint" Pos="10,20,30">
            <EntityLinks><Link Name="" TargetId="2"/><Link Name="" TargetId="2"/>
              <Link Name="look" TargetId="missing"/><Link Name="" TargetId="4"/></EntityLinks>
          </Entity>
          <Entity EntityId="3" EntityGuid="3" Pos="20,30,40" Rotate="1,0,0,0"/>
          <Entity EntityId="4" EntityGuid="4" EntityClass="SmartAreaShape" Pos="0,0,0"/>
        </Objects>''')
        child = b'<Objects><Entity EntityId="2" EntityGuid="2" EntityClass="TagPoint" ParentId="3" Pos="1,2,3"/></Objects>'
        with zipfile.ZipFile(path, 'w') as z:
            z.writestr('objects_mission0.xml', E.tostring(root))
            z.writestr('layers/points.xml', child)
        return path, dict(area=dict(EntityId='9'), target_links=[dict(Name='cityWalk', TargetId='1')])

    def contract_fixture(self, root):
        (root/'Data/Levels/trosecko').mkdir(parents=True)
        template = '''<database><SmartEntityTemplate DatabaseId="native">
          <Resources><Resource Name="use" MaxInstances="1"/></Resources><BehaviorTemplates>
          <SmartBehaviorTemplate Name="use" InitialState="Enabled" Resource="use">
            <TreeLocation FileName="world/point.xml" TreeName="use"/>
          </SmartBehaviorTemplate></BehaviorTemplates></SmartEntityTemplate></database>'''
        with zipfile.ZipFile(root/'Data/Tables.pak', 'w') as z: z.writestr(TABLE, template)
        with zipfile.ZipFile(root/'Data/Scripts.pak', 'w') as z:
            z.writestr('AI/world/point.xml', '''<BehaviorTrees><BehaviorTree name="use"><Root>
              <EntityContextElement context="activity_cityWalk_standing">
                <ExactMove destinationSpecification="$__object.id"/><Wait duration="'15s'"/>
              </EntityContextElement></Root></BehaviorTree></BehaviorTrees>''')
        with zipfile.ZipFile(root/'Data/Levels/trosecko/level.pak', 'w') as z:
            z.writestr('objects_mission0.xml', '''<Objects>
              <Entity EntityClass="DetailMovementSmartObject" EntityGuid="00000005-0000-0000">
                <Properties guidSmartObjectType="native" bSaved_by_game="0"/></Entity></Objects>''')
            z.writestr('tables/ai/scheduler.xml', '''<database><Schedulers>
              <C_SmartHub EntityGuid="6"><Links><S_ActivityLink TargetGuid="5" PositioningDelegate="0">
                <Parameters BehaviorName="use" BehaviorOverride="false" TimeOfDayStart="0" TimeOfDayEnd="1440"/>
              </S_ActivityLink></Links></C_SmartHub><C_SmartHub EntityGuid="5"/></Schedulers></database>''')

    def prepared(self):
        files, schedules, activity = schedule_fixture.ScheduleWorldTests().fixture()
        entry = schedules['person'][0]
        entry['arrival']['Rotate'] = '1,0,0,0'
        entry['behavior'] = dict(tree_file='final/sa_city.xml', tree_name='CityWalk')
        entry['area'] = dict(EntityGuid='20')
        entry['city_work'] = dict(points=[entry['arrival'],
            dict(EntityId='10',EntityGuid='1A',Pos='80,90,100',Rotate='1,0,0,0')], excluded_links=[])
        with patch('character_schedule_world.native_wait_activity', return_value=(activity,None)):
            files, _ = bind_arrivals(files,schedules,None)
        return files, schedules

    def test_source_pool_prunes_look_targets_resolves_layers_and_parent_transform(self):
        with tempfile.TemporaryDirectory() as tmp:
            path, entry = self.source(tmp)
            with zipfile.ZipFile(path) as z: result = resolve(entry,z)
        self.assertEqual([p['EntityId'] for p in result['city_work']['points']], ['1','2'])
        self.assertEqual(result['city_work']['points'][1]['Pos'], '21,32,43')
        self.assertNotIn('ParentId',result['city_work']['points'][1])
        self.assertEqual(len(result['city_work']['excluded_links']),2)
        self.assertNotIn('city_work',entry)

    def test_source_pool_rejects_missing_required_target_and_ambiguous_start(self):
        with tempfile.TemporaryDirectory() as tmp:
            path, entry = self.source(tmp)
            entry['target_links'] *= 2
            with zipfile.ZipFile(path) as z:
                with self.assertRaises(ValueError): resolve(entry,z)
            entry['target_links'] = [dict(Name='cityWalk',TargetId='absent')]
            with zipfile.ZipFile(path) as z:
                with self.assertRaisesRegex(ValueError,'Unresolved'): resolve(entry,z)

    def test_native_contract_rejects_changed_movement_and_occupancy(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);self.contract_fixture(root)
            props, activity, terminal = native_contract(root)
            self.assertEqual(props.get('guidSmartObjectType'),'native')
            self.assertEqual(activity.find('Parameters').get('BehaviorName'),'use')
            self.assertEqual(len(terminal),0)
            with zipfile.ZipFile(root/'Data/Scripts.pak','w') as z:
                z.writestr('AI/world/point.xml','<BehaviorTrees><BehaviorTree name="use"><Root/></BehaviorTree></BehaviorTrees>')
            with self.assertRaisesRegex(ValueError,'lifecycle contract'):native_contract(root)
            with zipfile.ZipFile(root/'Data/Tables.pak') as z: table=z.read(TABLE)
            with zipfile.ZipFile(root/'Data/Tables.pak','w') as z:
                z.writestr(TABLE,table.replace(b'MaxInstances="1"',b'MaxInstances="-1"'))
            with self.assertRaisesRegex(ValueError,'exclusive occupancy'):native_contract(root)

    def test_pool_uses_native_leaves_preserves_clock_and_static_link_definitions(self):
        files,schedules=self.prepared()
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);self.contract_fixture(root)
            with zipfile.ZipFile(root/'Data/Levels/trosecko/level.pak') as source:
                result,report=bind_jobs(files,schedules,source,root,{})
        scheduler=E.fromstring(result['tables/ai/scheduler.xml'])
        validate_scheduler_targets(scheduler)
        incoming=scheduler.find("Schedulers/C_SmartHub[@EntityGuid='1']/Links/S_ActivityLink")
        self.assertIsNone(incoming.find('Parameters').get('BehaviorName'))
        hub=scheduler.find("Schedulers/C_SmartHub[@EntityGuid='"+incoming.get('TargetGuid')+"']")
        self.assertEqual(len(hub.find('Links')),2)
        for link in hub.findall('Links/S_ActivityLink'):
            p=link.find('Parameters')
            self.assertEqual((p.get('BehaviorName'),p.get('TimeOfDayStart'),p.get('TimeOfDayEnd')),
                             ('use','300','720'))
        waiting=E.fromstring(result['waitinglinks.xml'])
        actor_edges=[x.text for r in waiting.findall('WaitingLinks/WaitingLink')
                     if r.get('SourceId')==native_guid(1) for x in r]
        self.assertIn('_',actor_edges)
        self.assertIn('home',actor_edges)
        self.assertNotIn('_,use',actor_edges)
        self.assertEqual(len(report[0]['destinations']),2)
        self.assertTrue(report[0]['pending'])
        self.assertFalse(report[0]['runtime_verified'])

    def test_midnight_split_keeps_both_intervals_without_duplicate_destinations(self):
        files,schedules=self.prepared()
        # The arrival compiler coalesces equal targets but retains both clock
        # spans. Exercise the work binder with that actual compiled shape.
        scheduler=E.fromstring(files['tables/ai/scheduler.xml'])
        links=scheduler.find("Schedulers/C_SmartHub[@EntityGuid='1']/Links")
        link=links[0]
        link.find('Parameters').set('TimeOfDayStart','0')
        link.find('Parameters').set('TimeOfDayEnd','200')
        second=copy.deepcopy(link)
        second.find('Parameters').set('TimeOfDayStart','1200')
        second.find('Parameters').set('TimeOfDayEnd','1440')
        links.append(second);files['tables/ai/scheduler.xml']=E.tostring(scheduler)
        first=schedules['person'][0];first.update(start_minute=0,end_minute=200)
        schedules['person'].append(dict(first,start_minute=1200,end_minute=1440))
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);self.contract_fixture(root)
            with zipfile.ZipFile(root/'Data/Levels/trosecko/level.pak') as source:
                result,report=bind_jobs(files,schedules,source,root,{})
        mission=E.fromstring(result['objects_mission0.xml'])
        self.assertEqual(len([e for e in mission if e.get('Name','').startswith('gm_citywalk_')]),2)
        self.assertEqual(report[0]['intervals'],[[0,200],[1200,1440]])
        scheduler=E.fromstring(result['tables/ai/scheduler.xml'])
        hub=scheduler.find("Schedulers/C_SmartHub[@EntityGuid='"+link.get('TargetGuid')+"']")
        self.assertEqual(len(hub.find('Links')),4)
        self.assertEqual({(l.find('Parameters').get('TimeOfDayStart'),l.find('Parameters').get('TimeOfDayEnd'))
                          for l in hub.findall('Links/S_ActivityLink')},{('0','200'),('1200','1440')})
        validate_scheduler_targets(scheduler)

    def test_shared_destinations_have_one_identity_and_terminal_and_conflicts_fail(self):
        files,schedules=self.prepared();entry=schedules['person'][0]
        mission=E.fromstring(files['objects_mission0.xml'])
        scheduler=E.fromstring(files['tables/ai/scheduler.xml'])
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);self.contract_fixture(root)
            _,_,report=bind(mission,scheduler,'person',entry,root)
            anchor=next(e for e in mission if e.get('Name','').startswith('gm_schedule_'))
            second=copy.deepcopy(anchor)
            second.set('Name','gm_schedule_other_9');second.set('EntityGuid',native_guid(100));second.set('EntityId','100')
            second.remove(second.find('EntityLinks'));mission.append(second)
            rows=scheduler.find('Schedulers')
            E.SubElement(rows,'C_SmartHub',EntityGuid='100')
            owner=E.SubElement(rows,'C_SmartHub',EntityGuid='101')
            link=E.SubElement(E.SubElement(owner,'Links'),'S_ActivityLink',TargetGuid='100')
            E.SubElement(link,'Parameters',BehaviorName='use',TimeOfDayStart='800',TimeOfDayEnd='1000')
            _,_,again=bind(mission,scheduler,'other',entry,root)
            self.assertEqual([x['target_guid'] for x in report['destinations']],
                             [x['target_guid'] for x in again['destinations']])
            self.assertEqual(len([e for e in mission if e.get('Name','').startswith('gm_citywalk_')]),2)
            validate_scheduler_targets(scheduler)
            # A separately prepared actor may reuse the pool, but never with
            # changed source geometry under the same persistent identity.
            conflicting=copy.deepcopy(entry)
            conflicting['city_work']['points'][0]['Pos']='0,0,0'
            with self.assertRaisesRegex(ValueError,'already has scheduler dependencies'):
                bind(mission,scheduler,'other',conflicting,root)

    def test_adapter_selection_does_not_use_person_names(self):
        self.assertTrue(population_work_supports(dict(behavior=dict(tree_file='FINAL\\sa_city.xml',tree_name='CityWalk'))))
        self.assertFalse(population_work_supports(dict(behavior=dict(tree_file='final/sa_city.xml',tree_name='WaterCarrier_work'))))

    def test_pending_existing_idle_people_are_eligible_but_quest_and_partial_schedules_are_not(self):
        files,_,_=schedule_fixture.ScheduleWorldTests().fixture()
        self.assertEqual(baseline_schedule_names(files,['person','missing']),{'person'})
        original=files['tables/ai/scheduler.xml']
        for changed in [original.replace(b'schedulerWait',b'questBehavior'),
                        original.replace(b'PositioningDelegate="2"',b'PositioningDelegate="3"'),
                        original.replace(b'</Links>',b'<S_ActivityLink TargetGuid="3"><Parameters BehaviorName="quest"/></S_ActivityLink></Links>')]:
            files['tables/ai/scheduler.xml']=changed
            self.assertFalse(baseline_schedule_names(files,['person']))
        files['tables/ai/scheduler.xml']=original
        self.assertEqual(baseline_schedule_names(files,['person']),{'person'})


if __name__=='__main__':unittest.main()
