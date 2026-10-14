import sys
import unittest
from unittest.mock import patch
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from character_schedule import day_intervals, plan


class ScheduleTests(unittest.TestCase):
    def test_single_entry_is_all_day_and_midnight_wrap_is_preserved(self):
        self.assertEqual(day_intervals([dict(activity='anything', start_minute=430)]),
                         [dict(activity='anything', start_minute=0, end_minute=1440)])
        rows = day_intervals([dict(activity='rest', start_minute=1200), dict(activity='work', start_minute=400)])
        self.assertEqual([(r['activity'],r['start_minute'],r['end_minute']) for r in rows],
                         [('rest',0,400),('work',400,1200),('rest',1200,1440)])
        with self.assertRaises(ValueError): day_intervals([dict(activity='a',start_minute=1)]*2)

    def test_arbitrary_person_area_behavior_and_clock_are_source_data(self):
        class Tables:
            def get(self, name):
                return dict(rows={
                    'ai/sa_smart_area':[dict(sa_smart_area_id='area',sa_smart_area_name='any_area')],
                    'ai/sa_smart_area2sa_behaviour_tag':[dict(sa_smart_area_id='area',sa_behaviour_tag_id='routine',priority='7')],
                    'ai/sa_behaviour_tag':[dict(sa_behaviour_tag_id='routine',sa_behaviour_tag_name='SomeJob',tree_file='custom/job.xml',tree_name='RunJob')]
                }[name])
        person = dict(name='unrelated_person',ai=dict(schedule=[dict(activity='work',start_minute=530)],links=[
            dict(label="Work[('SomeJob')]",source_xml='<Entity Name="source_area" Pos="1,2,3"><Properties guidSmartAreaTemplate="area"/><EntityLinks><Link TargetId="999" Name="station"/></EntityLinks></Entity>')]))
        result=plan(person,Tables())
        self.assertFalse(result['pending'])
        row=result['resolved'][0]
        self.assertEqual(row['behavior']['tree_name'],'RunJob')
        self.assertEqual(row['target_links'],[dict(TargetId='999',Name='station')])
        for label in ("Work[SomeJob]", "Work['SomeJob']", 'Work["SomeJob"],OtherTag'):
            person['ai']['links'][0]['label'] = label
            self.assertEqual(plan(person, Tables())['resolved'][0]['behavior']['tree_name'], 'RunJob')
        person['ai']['links'][0]['label']="Work[('Unknown')]"
        with self.assertRaises(ValueError):plan(person,Tables())

    def test_controller_work_keeps_callbacks_and_source_conditions(self):
        class Tables:
            def get(self, name): return dict(rows=[])
        person = dict(name='arbitrary', ai=dict(schedule=[dict(activity='work',start_minute=0)],links=[
            dict(label="Work['sell']",source_xml='<Entity Name="source_quest" EntityClass="QuestObject"><Properties/></Entity>')]))
        definition = dict(smart_object={'so_smart_object_id':'controller'},
                          entry_points=[dict(tree='onUpdate')], behaviors=[dict(
                              row=dict(so_behaviour_tag_name='sell',tree_name='sellTree',condition_id='source-condition'),
                              link=dict(priority='7'))])
        with patch('character_schedule.controller_definition', return_value=definition) as resolve:
            row = plan(person, Tables())['resolved'][0]
        resolve.assert_called_once_with(unittest.mock.ANY, {'smart_object':'source_quest'})
        self.assertEqual(row['target_kind'], 'quest_controller')
        self.assertEqual(row['controller']['entry_points'], [{'tree':'onUpdate'}])
        self.assertEqual(row['behavior']['condition_id'], 'source-condition')
        self.assertEqual(row['binding']['priority'], '7')

    def test_contextual_request_is_not_flattened_to_an_unconditional_job(self):
        class Tables:
            def get(self, name): return dict(rows=[])
        person = dict(name='arbitrary', ai=dict(schedule=[dict(activity='work',start_minute=0)],links=[
            dict(label="Work[event('questChanged'),work('sell')]",source_xml='<Entity/>')]))
        report = plan(person, Tables())
        self.assertFalse(report['resolved'])
        self.assertEqual(report['pending'][0]['parsed_link']['named'], {'event':'questChanged','work':'sell'})
