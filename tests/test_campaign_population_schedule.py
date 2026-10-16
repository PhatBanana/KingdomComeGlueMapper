import copy
import hashlib
import sys
import unittest
from pathlib import Path
import xml.etree.ElementTree as E

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from campaign_population_schedule import assemble, behavior_catalog, PREFIX
from campaign_entity_links import native_guid, guid_value, append_links


class PopulationScheduleTests(unittest.TestCase):
    def fixture(self):
        objects = b'''<Objects>
          <Entity EntityGuid="00000001-0000-0000" EntityId="1" Name="arbitrary_resident"/>
          <Entity EntityGuid="00000002-0000-0000" EntityId="2" Name="work">
            <Properties guidSmartAreaTemplate="work-template"/></Entity>
          <Entity EntityGuid="00000003-0000-0000" EntityId="3" Name="home">
            <Properties guidSmartAreaTemplate="home-template"/></Entity>
        </Objects>'''
        resources = {}
        for key, behavior in [('work', 'makeSomething'), ('home', 'sleep')]:
            resources['Libs/Tables/ai/smartEntity/' + key + '.xml'] = (
                '<database><SmartEntitys><SmartEntityTemplate DatabaseId="' + key + '-template">'
                '<BehaviorTemplates><SmartBehaviorTemplate Name="' + behavior + '" InitialState="Enabled">'
                '<TreeLocation FileName="compiled.xml" TreeName="' + behavior + '"/>'
                '</SmartBehaviorTemplate></BehaviorTemplates></SmartEntityTemplate></SmartEntitys></database>').encode()
        activities = [dict(area={'EntityGuid': guid}, target_kind='smart_area',
            behavior={'sa_behaviour_tag_name': name}, start_minute=start, end_minute=end)
            for guid, name, start, end in [('3', 'sleep', 0, 420), ('2', 'makeSomething', 420, 1140),
                                         ('3', 'sleep', 1140, 1440)]]
        record = dict(actor=dict(entity_guid='1', name='arbitrary_resident', profiles=['normal']),
                      schedule=dict(resolved=activities, pending=[]))
        models = [dict(profile_work_dependencies=[dict(actors=[record])])]
        registry = {'entities': {f'0000000{n}-0000-0000': f'0000000{n}-0000-0000' for n in [1, 2, 3]}}
        template = E.fromstring('<S_ActivityLink TargetGuid="99" PositioningDelegate="0">'
            '<Parameters BehaviorName="schedulerWait" Priority="0" TimeOfDayStart="0" '
            'TimeOfDayEnd="1440" TimeVariation="30"/></S_ActivityLink>')
        return models, {PREFIX + 'objects_mission0.xml': objects}, registry, resources, template

    def test_complete_daycycle_emits_executable_clocked_jobs(self):
        args = self.fixture()
        result, report = assemble(*args)
        self.assertEqual(len(report['converted']), 1)
        self.assertEqual(report['unresolved'], [])
        scheduler = E.fromstring(result[PREFIX + 'tables/ai/scheduler.xml'])
        activities = scheduler.findall("Schedulers/C_SmartHub[@EntityGuid='1']/Links/S_ActivityLink")
        self.assertEqual([(a.get('TargetGuid'), a.find('Parameters').get('BehaviorName'),
            a.find('Parameters').get('TimeOfDayStart'), a.find('Parameters').get('TimeOfDayEnd')) for a in activities],
            [('3','sleep','0','420'), ('2','makeSomething','420','1140'), ('3','sleep','1140','1440')])
        self.assertTrue(all(a.find('Parameters').get('TimeVariation') == '0' for a in activities))
        self.assertEqual(len(scheduler.findall('Schedulers/C_SmartHub')), 3)
        # Idempotent when another quest closure references the same residents.
        again, _ = assemble(args[0], result, *args[2:])
        self.assertEqual(result, again)

    def test_missing_evening_program_does_not_publish_partial_workday(self):
        args = self.fixture()
        del args[3]['Libs/Tables/ai/smartEntity/home.xml']
        original = copy.deepcopy(args[1])
        result, report = assemble(*args)
        self.assertEqual(report['converted'], [])
        self.assertIn('has not been emitted', report['unresolved'][0]['reason'])
        self.assertEqual(E.tostring(E.fromstring(original[PREFIX + 'objects_mission0.xml'])),
                         E.tostring(E.fromstring(result[PREFIX + 'objects_mission0.xml'])))
        self.assertFalse(E.fromstring(result[PREFIX + 'tables/ai/scheduler.xml']).findall('.//S_ActivityLink'))

    def test_quest_override_survives_ordinary_schedule_binding(self):
        args = self.fixture()
        args[1][PREFIX + 'tables/ai/scheduler.xml'] = b'''<database><Schedulers version="1">
          <C_SmartHub EntityGuid="1"><Links><S_ActivityLink TargetGuid="2" PositioningDelegate="42">
          <Parameters BehaviorName="questFight" Priority="159"/></S_ActivityLink></Links></C_SmartHub>
          <C_SmartHub EntityGuid="2"/></Schedulers></database>'''
        result, report = assemble(*args)
        scheduler = E.fromstring(result[PREFIX + 'tables/ai/scheduler.xml'])
        self.assertEqual(len(report['converted']), 1)
        self.assertEqual(len(scheduler.findall('.//S_ActivityLink')), 4)
        fight = scheduler.find(".//S_ActivityLink[@PositioningDelegate='42']")
        self.assertEqual(fight.find('Parameters').get('Priority'), '159')

    def test_importer_idle_is_replaced_in_both_networks(self):
        args = self.fixture()
        idle = native_guid(int.from_bytes(hashlib.sha256(b'person-idle/1').digest()[:8], 'little'))
        objects = E.fromstring(args[1][PREFIX + 'objects_mission0.xml'])
        anchor = E.SubElement(objects, 'Entity', EntityGuid=idle, EntityId='4', EntityClass='TagPoint')
        E.SubElement(E.SubElement(anchor, 'EntityLinks'), 'Link', Name='^delegate', TargetGuid='00000002-0000-0000')
        E.SubElement(E.SubElement(objects[0], 'EntityLinks'), 'Link', Name='_,schedulerWait', TargetGuid=idle)
        args[1][PREFIX + 'objects_mission0.xml'] = E.tostring(objects)
        args[1][PREFIX + 'tables/ai/scheduler.xml'] = (f'''<database><Schedulers>
          <C_SmartHub EntityGuid="1"><Links><S_ActivityLink TargetGuid="2" PositioningDelegate="{guid_value(idle)}">
          <Parameters BehaviorName="schedulerWait" Priority="0"/></S_ActivityLink></Links></C_SmartHub>
          <C_SmartHub EntityGuid="2"/></Schedulers></database>''').encode()
        args[1][PREFIX + 'waitinglinks.xml'] = append_links(None, [
            ('00000001-0000-0000', idle, '_,schedulerWait'), ('00000001-0000-0000', idle, 'keepOtherTag')])
        result, report = assemble(*args)
        self.assertEqual(len(report['converted']), 1)
        self.assertNotIn(b'schedulerWait', result[PREFIX + 'tables/ai/scheduler.xml'])
        self.assertNotIn(b'schedulerWait', result[PREFIX + 'waitinglinks.xml'])
        self.assertIn(b'keepOtherTag', result[PREFIX + 'waitinglinks.xml'])

    def test_pending_source_assignment_is_not_replaced_with_idle(self):
        args = self.fixture()
        args[0][0]['profile_work_dependencies'][0]['actors'][0]['schedule']['pending'] = [{'activity': 'work'}]
        _, report = assemble(*args)
        self.assertEqual(report['converted'], [])
        self.assertIn('unresolved activities', report['unresolved'][0]['reason'])


if __name__ == '__main__':
    unittest.main()
