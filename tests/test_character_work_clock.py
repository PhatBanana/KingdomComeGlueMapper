"""Schedule interruption must preserve quests and support daytime sleepers."""
import copy
import unittest
from test_character_sleep import fixture
from character_sleep_work import bind, restrict_work_to_waking_hours
from character_city_benches import signature


class WorkClockTests(unittest.TestCase):
    def prepared(self, intervals):
        mission,scheduler,activity,choices,clock=fixture()
        mission[1].set('Name','gm_schedule_worker_field')
        clock['intervals']=intervals
        bind(mission,scheduler,'worker',clock,choices,'bed',activity)
        return mission,scheduler

    def work(self,scheduler):
        return [l.find('Parameters') for l in scheduler.find('Schedulers')[0].find('Links') if l.get('TargetGuid')=='2']

    def test_night_cutoff_interrupts_work_and_is_idempotent(self):
        m,s=self.prepared([(0,420),(1320,1440)])
        self.assertEqual(restrict_work_to_waking_hours(m,s),['worker'])
        self.assertEqual([(p.get('TimeOfDayStart'),p.get('TimeOfDayEnd'),p.get('HaltOnInvalid')) for p in self.work(s)],[('420','1320','true')])
        before=signature(s)
        self.assertEqual(restrict_work_to_waking_hours(m,s),[])
        self.assertEqual(signature(s),before)

    def test_rotating_guard_splits_day_and_preserves_quest_link(self):
        m,s=self.prepared([(480,960)])
        links=s.find('Schedulers')[0].find('Links')
        quest=copy.deepcopy(links[0]);quest.find('Parameters').set('Priority','159');links.append(quest)
        before=signature(quest)
        restrict_work_to_waking_hours(m,s)
        self.assertEqual([(p.get('TimeOfDayStart'),p.get('TimeOfDayEnd')) for p in self.work(s) if p.get('Priority')=='0'],[('0','480'),('960','1440')])
        self.assertEqual(signature(quest),before)

    def test_actor_filter_and_non_owned_work_are_untouched(self):
        m,s=self.prepared([(0,420),(1320,1440)])
        before=signature(s)
        self.assertEqual(restrict_work_to_waking_hours(m,s,actors={'someone_else'}),[])
        self.assertEqual(signature(s),before)
        m[1].set('Name','authored_quest_station')
        self.assertEqual(restrict_work_to_waking_hours(m,s),[])
        self.assertEqual(signature(s),before)

    def test_already_bounded_work_still_gets_interruption(self):
        m,s=self.prepared([(0,420),(1320,1440)])
        p=self.work(s)[0];p.set('TimeOfDayStart','480');p.set('TimeOfDayEnd','1200')
        self.assertEqual(restrict_work_to_waking_hours(m,s),['worker'])
        self.assertEqual(p.get('HaltOnInvalid'),'true')
