import copy
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch, MagicMock, Mock
import xml.etree.ElementTree as E
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'tools'))
import character_home_rest as rest
import test_character_city_benches as fixtures
import test_character_work_capabilities as capabilities
from character_city_benches import signature
from character_person_activity import validate_scheduler_targets


class HomeRestTests(unittest.TestCase):
    def contract(self):
        program = E.fromstring('''<BehaviorTrees><BehaviorTree name="housework"><Root/></BehaviorTree>
          <BehaviorTree name="hangingOut"><Root><OnInit><Sequence><VariableExistsGate><Else>
          <Expression expressions="$t_graphDepth = 1"/></Else></VariableExistsGate></Sequence></OnInit>
          <ReserveBehavior reserveFrom="bench" behaviorName="use"><Search><ReserveBehaviorSearch>
          <Selector><IfCondition condition="$t_weatherState.type == $enum:WeatherType.Normal" failOnCondition="true"/></Selector>
          </ReserveBehaviorSearch></Search><CallBehavior Target="bench" BehaviorName="use"/>
          </ReserveBehavior></Root></BehaviorTree></BehaviorTrees>''')
        selector = program.find('.//Selector')
        for index in range(2):
            search = E.SubElement(selector[0] if index == 0 else selector, 'GraphSearch',
                Origin='__area.id', depth='$t_graphDepth', EdgePruning='parent,inventory', includeOrigin='false',
                AllowedEdges='', SubGraph='', SetOperationChoice='Intersection|And')
            negate = E.SubElement(search,'NegationOp',Results='true',Advance='false',EndOp='true')
            E.SubElement(E.SubElement(negate,'Child0'),'CategoryFilter',categories='diceTable')
            parent = search
            if index:
                parent = E.SubElement(E.SubElement(search,'NegationOp',Results='true',Advance='true',EndOp='true'),'Child0')
            E.SubElement(parent,'LinkTagFilter',tag='outside')
            E.SubElement(search,'CategoryFilter',categories='Seat')
            E.SubElement(search,'HasBehaviorFilter',FilterChoice='Requestable',BehaviorList='use')
            E.SubElement(search,'Nodalyzer')
        rows = {'ai/sa_behaviour_tag': {'rows': [dict(sa_behaviour_tag_id='rest',sa_behaviour_tag_name='hangingOut',tree_file='final/sa_home.xml',tree_name='hangingOut')]},
                'ai/sa_smart_area2sa_behaviour_tag': {'rows': [dict(sa_smart_area_id='home',sa_behaviour_tag_id='rest')]}}
        return dict(area_template={'sa_smart_area_id':'home'}), rows, program

    def test_source_contract_accepts_supported_binding(self):
        rest.source_contract(*self.contract())

    def test_source_contract_rejects_changed_selection(self):
        for change in ('dice', 'weather', 'negation', 'depth', 'binding', 'inherited_depth'):
            with self.subTest(change=change):
                entry, tables, program = self.contract()
                if change == 'dice': program.find('.//NegationOp/Child0').clear()
                elif change == 'weather': program.find('.//IfCondition').set('failOnCondition','false')
                elif change == 'negation': program.find('.//NegationOp').set('Results','false')
                elif change == 'depth': program.find('.//GraphSearch').set('depth','2')
                elif change == 'binding': tables['ai/sa_behaviour_tag']['rows'][0]['tree_name']='hangingOut_work'
                else: E.SubElement(program.find("BehaviorTree[@name='housework']/Root"),'Expression',expressions='$t_graphDepthParent = 2')
                with self.assertRaises(ValueError): rest.source_contract(entry,tables,program)

    def source(self, root):
        entities = E.fromstring('''<Objects>
            <Entity EntityId="1" EntityClass="SmartObjectHolder" EntityGuid="1" Pos="1,2,3">
                <Properties sWH_AI_EntityCategory="Seat" soclasses_SmartObjectHelpers="Bench_Low"/></Entity>
            <Entity EntityId="2" EntityClass="SmartObjectHolder" EntityGuid="2" Pos="4,5,6">
                <Properties sWH_AI_EntityCategory="Seat,diceTable" soclasses_SmartObjectHelpers="Bench_Low"/></Entity>
            <Entity EntityId="3" EntityClass="TagPoint"/>
            <Entity EntityId="4" EntityClass="SmartObjectHolder" EntityGuid="4" Pos="7,8,9">
                <Properties sWH_AI_EntityCategory="Seat" soclasses_SmartObjectHelpers="Bench_Low"/></Entity>
            </Objects>''')
        path = root/'source.pak'
        with zipfile.ZipFile(path, 'w') as z:z.writestr('objects_mission0.xml', E.tostring(entities))
        return path, dict(area={}, target_links=[dict(Name='',TargetId='1'),dict(Name='',TargetId='2'),
                         dict(Name='',TargetId='3'),dict(Name='parent',TargetId='missing')])

    def prepared(self, root):
        files, schedules = fixtures.CityBenchTests().fixture(root)
        entry = schedules['person'][0]
        entry['behavior'] = dict(tree_file='final/sa_home.xml',tree_name='housework')
        mission = E.fromstring(files['objects_mission0.xml']); mission.find("Entity[@Name='person']").set('EntityClass','NPC')
        files['objects_mission0.xml'] = E.tostring(mission)
        return files, schedules

    def test_only_linked_non_dice_seats_are_selected(self):
        with tempfile.TemporaryDirectory() as tmp:
            path, entry = self.source(Path(tmp))
            with zipfile.ZipFile(path) as z: seats = rest.resolve(entry,z)
        self.assertEqual([s['EntityId'] for s in seats],['1'])

    def test_outdoor_seat_defers_whole_weather_dependent_area(self):
        with tempfile.TemporaryDirectory() as tmp:
            path, entry = self.source(Path(tmp))
            entry['target_links'].append(dict(Name='outside',TargetId='4'))
            with zipfile.ZipFile(path) as z:self.assertEqual(rest.resolve(entry,z),[])

    def test_binder_reuses_seat_and_keeps_work_clock(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);files,schedules=self.prepared(root)
            mission=E.fromstring(files['objects_mission0.xml']);scheduler=E.fromstring(files['tables/ai/scheduler.xml'])
            count=len(mission);entry=schedules['person'][0]
            job,links,seats=rest.bind(mission,scheduler,'person',entry,entry['city_work']['benches'],root)
            self.assertEqual(len(mission),count)
            self.assertEqual(seats[0].get('Name'),'gm_bench_20_0_StanceSmartObject')
            from campaign_entity_links import guid_value
            hub=scheduler.find("Schedulers/C_SmartHub[@EntityGuid='"+str(guid_value(job.get('EntityGuid')))+"']")
            params=hub.find('Links/S_ActivityLink/Parameters')
            self.assertEqual((params.get('TimeOfDayStart'),params.get('TimeOfDayEnd')),('300','720'))
            self.assertEqual(params.get('BehaviorName'),'use')
            validate_scheduler_targets(scheduler)
            before=signature(mission)
            with self.assertRaisesRegex(ValueError,'non-owned'):
                rest.bind(mission,scheduler,'person',entry,entry['city_work']['benches'],root)
            self.assertEqual(signature(mission),before)

    def test_modified_owner_is_rejected_before_mutation(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);files,schedules=self.prepared(root)
            mission=E.fromstring(files['objects_mission0.xml']);scheduler=E.fromstring(files['tables/ai/scheduler.xml'])
            scheduler.find('Schedulers')[0].set('EntityGuid','999');before=signature(mission)
            entry=schedules['person'][0]
            with self.assertRaisesRegex(ValueError,'non-owned'):
                rest.bind(mission,scheduler,'person',entry,entry['city_work']['benches'],root)
            self.assertEqual(signature(mission),before)

    def test_upgrade_repeats_without_replacing_live_jobs_or_claiming_all_phases(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);files,schedules=self.prepared(root);entry=schedules['person'][0]
            program=E.Element('BehaviorTrees');tree=capabilities.source();tree.set('name','housework');program.append(tree)
            reader=lambda *_:{'home':{'data':E.tostring(program)}}
            context=MagicMock();context.__enter__.return_value=reader
            archive=Mock(filename='C:/game/Data/Levels/map/level.pak')
            with patch.object(rest,'RetailSourceReader',return_value=context),patch.object(rest,'source_contract'),patch.object(rest,'resolve',return_value=entry['city_work']['benches']):
                result,report=rest.upgrade(files,schedules,archive,root)
                again,second=rest.upgrade(result,schedules,archive,root)
            self.assertEqual(result,again);self.assertEqual(second,[])
            self.assertIn('repair_home_fence',report[0]['pending'])
            self.assertFalse(report[0]['runtime_verified'])

    def test_source_without_hanging_out_phase_keeps_its_arrival(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);files,schedules=self.prepared(root)
            program=E.Element('BehaviorTrees');tree=capabilities.source();tree.set('name','housework');program.append(tree)
            reader=lambda *_:{'home':{'data':E.tostring(program)}}
            context=MagicMock();context.__enter__.return_value=reader
            with patch.object(rest,'RetailSourceReader',return_value=context),patch.object(rest,'housework_phases',return_value=['Cooking']),patch.object(rest,'resolve') as resolve:
                result,report=rest.upgrade(files,schedules,Mock(filename='C:/game/Data/Levels/map/level.pak'),root)
            self.assertEqual(report,[]);resolve.assert_not_called()
            self.assertEqual(signature(E.fromstring(result['tables/ai/scheduler.xml'])),signature(E.fromstring(files['tables/ai/scheduler.xml'])))


if __name__=='__main__':unittest.main()
