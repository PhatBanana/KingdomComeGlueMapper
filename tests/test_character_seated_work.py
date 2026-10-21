import copy
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
import xml.etree.ElementTree as E
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'tools'))
import character_seated_work as work
from campaign_entity_links import native_guid
from character_schedule_jobs import bind_jobs, population_work_supports
from character_schedule_world import bind_arrivals, baseline_schedule_names
from character_person_activity import validate_scheduler_targets
import test_character_schedule_world as fixtures


class SeatedWorkTests(unittest.TestCase):
    def test_native_contract_requires_reserved_seat_and_interruptible_stance(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp)
            (target/'Data/Levels/trosecko').mkdir(parents=True)
            work_table = '''<database><SmartEntityTemplate DatabaseId="work"><BehaviorTemplates>
              <SmartBehaviorTemplate Name="embroidery" InitialState="Enabled"><TreeLocation
              FileName="world/bench.xml" TreeName="embroidery"/></SmartBehaviorTemplate>
              </BehaviorTemplates></SmartEntityTemplate></database>'''
            seat_table = '''<database><SmartEntityTemplate DatabaseId="seat"><Resources>
              <Resource Name="use" MaxInstances="1"/></Resources><BehaviorTemplates>
              <SmartBehaviorTemplate Name="use" Resource="use"/></BehaviorTemplates></SmartEntityTemplate></database>'''
            def tables(seats):
                with zipfile.ZipFile(target/'Data/Tables.pak', 'w') as z:
                    for name, blob in [('so_benchActivity', work_table), ('so_sitPlace', seats)]:
                        z.writestr('Libs/Tables/ai/smartEntity/SmartEntity__'+name+'.xml', blob)
            program = '''<BehaviorTrees><BehaviorTree name="embroidery"><Root>
              <StanceElement smartObject="$__resource.id" stance="sitting">
              <EntityContextElement context="speech_readyForSwitchDialog">
              <UnstanceAction unstance="tailor_embroidery"/></EntityContextElement>
              </StanceElement></Root></BehaviorTree></BehaviorTrees>'''
            def scripts(blob):
                with zipfile.ZipFile(target/'Data/Scripts.pak', 'w') as z: z.writestr('AI/world/bench.xml', blob)
            with zipfile.ZipFile(target/'Data/Levels/trosecko/level.pak', 'w') as z:
                z.writestr('tables/ai/scheduler.xml', '''<database><Schedulers><C_SmartHub><Links>
                  <S_ActivityLink><Parameters BehaviorName="embroidery" BehaviorOverride="true" AllowedGenders="2"/>
                  </S_ActivityLink></Links></C_SmartHub></Schedulers></database>''')
            tables(seat_table); scripts(program)
            self.assertEqual(work.native_contract(target), ('work', 'seat'))
            tables(seat_table.replace('MaxInstances="1"', 'MaxInstances="-1"'))
            with self.assertRaisesRegex(ValueError, 'reservation contract'): work.native_contract(target)
            tables(seat_table); scripts(program.replace('$__resource.id', '$__object.id'))
            with self.assertRaisesRegex(ValueError, 'stance/lifecycle contract'): work.native_contract(target)

    def prepared(self, repeated=False):
        files, schedules, activity = fixtures.ScheduleWorldTests().fixture()
        mission = E.fromstring(files['objects_mission0.xml'])
        mission[0].set('EntityClass', 'NPC_Female')
        for index in (0, 1):
            seat = E.SubElement(mission, 'Entity', Name=f'gm_bench_9_{index}_StanceSmartObject',
                EntityId=str(10+index), EntityGuid=native_guid(10+index), EntityClass='StanceSmartObject', Pos='1,2,3')
            E.SubElement(seat, 'Properties', guidSmartObjectType='seat', soclass_SmartObjectHelpers='Sit_1Place_Bench_Low')
        files['objects_mission0.xml'] = E.tostring(mission)
        entry = schedules['person'][0]
        entry['behavior'] = dict(tree_file=work.SOURCE[0], tree_name=work.SOURCE[1])
        entry['area'] = dict(EntityGuid='20')
        entry['seated_work'] = dict(seats=[entry['arrival']])
        if repeated:
            schedules['person'].append(dict(entry, start_minute=1200, end_minute=1440))
        with patch('character_schedule_world.native_wait_activity', return_value=(activity, None)):
            files, _ = bind_arrivals(files, schedules, None)
        return files, schedules

    def bind(self, files, schedules):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp)/'source.pak'
            with zipfile.ZipFile(p, 'w') as z: z.writestr('objects_mission0.xml', '<Objects/>')
            with zipfile.ZipFile(p) as z, patch('character_seated_work.native_contract', return_value=('work', 'seat')):
                return bind_jobs(files, schedules, z, None, {})

    def test_generic_adapter_and_source_clock_shared_seats_and_override(self):
        files, schedules = self.prepared(repeated=True)
        before = E.fromstring(files['objects_mission0.xml'])
        result, report = self.bind(files, schedules)
        mission = E.fromstring(result['objects_mission0.xml'])
        rows = E.fromstring(result['tables/ai/scheduler.xml'])
        validate_scheduler_targets(rows)
        incoming = rows.find("Schedulers/C_SmartHub[@EntityGuid='1']/Links")
        self.assertEqual([(l.find('Parameters').get('TimeOfDayStart'), l.find('Parameters').get('TimeOfDayEnd'))
                         for l in incoming], [('300', '720'), ('1200', '1440')])
        for link in incoming:
            params = link.find('Parameters')
            self.assertEqual(params.get('BehaviorName'), 'embroidery')
            self.assertEqual(params.get('BehaviorOverride'), 'true')
            self.assertEqual(params.get('AllowedGenders'), '2')
        hub = rows.find("Schedulers/C_SmartHub[@EntityGuid='"+incoming[0].get('TargetGuid')+"']")
        self.assertEqual(len(hub.find('Links')), 2)
        for link in hub.findall('Links/S_ActivityLink'):
            self.assertEqual(link.find('Parameters').get('BehaviorName'), 'use')
            self.assertEqual(link.find('Parameters').get('BehaviorOverride'), 'false')
            self.assertEqual(link.find('Parameters').get('TimeOfDayEnd'), '1440')
            self.assertEqual(len(rows.find("Schedulers/C_SmartHub[@EntityGuid='"+link.get('TargetGuid')+"']")), 0)
        for seat in [e for e in before if e.get('EntityClass') == 'StanceSmartObject']:
            self.assertEqual(E.tostring(seat), E.tostring(next(e for e in mission if e.get('Name') == seat.get('Name'))))
        self.assertIn(b'_,embroidery', result['waitinglinks.xml'])
        self.assertIn(b'>home<', result['waitinglinks.xml'])
        self.assertEqual(report[0]['intervals'], [[300, 720], [1200, 1440]])
        self.assertFalse(report[0]['runtime_verified'])
        self.assertTrue(population_work_supports(schedules['person'][0]))
        self.assertFalse(baseline_schedule_names(result, ['person']))
        with self.assertRaisesRegex(ValueError, 'importer-owned arrival'): self.bind(result, schedules)

    def test_missing_table_or_conflicting_resource_fails_without_changing_inputs(self):
        for failure in ('missing', 'table', 'scheduler', 'male'):
            with self.subTest(failure=failure):
                files, schedules = self.prepared()
                mission = E.fromstring(files['objects_mission0.xml'])
                seats = [e for e in mission if e.get('EntityClass') == 'StanceSmartObject']
                if failure == 'missing':
                    for seat in seats: mission.remove(seat)
                if failure == 'table':
                    seats[0].find('Properties').set('soclass_SmartObjectHelpers', 'Sit_1Place_Bench_Low_Table_Right')
                if failure == 'male': mission[0].set('EntityClass', 'NPC')
                files['objects_mission0.xml'] = E.tostring(mission)
                if failure == 'scheduler':
                    rows = E.fromstring(files['tables/ai/scheduler.xml'])
                    row = E.SubElement(rows.find('Schedulers'), 'C_SmartHub', EntityGuid='10')
                    E.SubElement(row, 'Links')
                    files['tables/ai/scheduler.xml'] = E.tostring(rows)
                before = dict(files)
                with self.assertRaises(ValueError): self.bind(files, schedules)
                self.assertEqual(files, before)

    def source(self, tmp):
        path = Path(tmp)/'source.pak'
        with zipfile.ZipFile(path, 'w') as z:
            z.writestr('objects_mission0.xml', '''<Objects>
              <Entity EntityId="9" EntityGuid="19" EntityClass="SmartObjectHolder" Pos="1,2,3">
                <Properties sWH_AI_EntityCategory="Seat" soclasses_SmartObjectHelpers="Bench_1Place_noTable"><Script Misc=""/></Properties>
              </Entity>
              <Entity EntityId="10" EntityGuid="20" EntityClass="SmartObjectHolder" Pos="4,5,6">
                <Properties sWH_AI_EntityCategory="Seat" soclasses_SmartObjectHelpers="Bench_1Place"><Script Misc="hasTable:true"/></Properties>
              </Entity></Objects>''')
        root = E.Element('BehaviorTrees')
        tree = E.SubElement(root, 'BehaviorTree', name='embroider_sit')
        search = E.SubElement(E.SubElement(tree, 'Root'), 'GraphSearch', Origin='__area.id', depth='1',
            selection='true', includeOrigin='false', EdgePruning='parent,inventory', AllowedEdges='', SubGraph='', AllowSubtraph='false')
        E.SubElement(search, 'CategoryFilter', categories='Seat', Source='Child', prune='true')
        for behavior in ('embroider_needlework', 'use'):
            E.SubElement(search, 'HasBehaviorFilter', BehaviorList=behavior, Source='Child', prune='true')
        E.SubElement(search, 'Nodalyzer')
        entry = dict(area=dict(EntityId='1'), target_links=[dict(Name='Seat', TargetId='9'),
            dict(Name='Seat', TargetId='10'), dict(Name='parent', TargetId='absent')])
        return path, root, entry

    def test_source_authored_seats_not_proximity_and_pruned_parent_is_not_loaded(self):
        with tempfile.TemporaryDirectory() as tmp:
            path, program, entry = self.source(tmp)
            reader = lambda *_: {'work': dict(data=E.tostring(program))}
            with zipfile.ZipFile(path) as z:
                result = work.resolve(entry, z, tmp, reader)
                self.assertEqual([s['EntityId'] for s in result['seated_work']['seats']], ['9'])
                self.assertEqual(result['arrival']['Pos'], '1,2,3')
                program.find('.//GraphSearch').set('depth', '2')
                with self.assertRaisesRegex(ValueError, 'selection contract'): work.resolve(entry, z, tmp, reader)

    def test_two_people_share_one_seat_registration(self):
        files, schedules = self.prepared()
        result, _ = self.bind(files, schedules)
        original = E.fromstring(files['objects_mission0.xml'])
        mission = E.fromstring(result['objects_mission0.xml'])
        other = copy.deepcopy(original[0]); other.set('Name', 'other'); other.set('EntityGuid', native_guid(90))
        mission.append(other)
        job = copy.deepcopy(next(e for e in original if e.get('Name', '').startswith('gm_schedule_')))
        job.set('Name', 'gm_schedule_other_9'); job.set('EntityGuid', native_guid(91)); mission.append(job)
        rows = E.fromstring(result['tables/ai/scheduler.xml'])
        E.SubElement(rows.find('Schedulers'), 'C_SmartHub', EntityGuid='91')
        actor = E.SubElement(rows.find('Schedulers'), 'C_SmartHub', EntityGuid='90')
        link = E.SubElement(E.SubElement(actor, 'Links'), 'S_ActivityLink', TargetGuid='91', PositioningDelegate='0')
        E.SubElement(link, 'Parameters', BehaviorName='use', TimeOfDayStart='800', TimeOfDayEnd='1000')
        with patch('character_seated_work.native_contract', return_value=('work', 'seat')):
            work.bind(mission, rows, 'other', schedules['person'][0], None)
        self.assertEqual(len(rows.findall("Schedulers/C_SmartHub[@EntityGuid='10']")), 1)
        self.assertEqual(len(rows.findall("Schedulers/C_SmartHub[@EntityGuid='11']")), 1)
        validate_scheduler_targets(rows)


if __name__ == '__main__': unittest.main()
