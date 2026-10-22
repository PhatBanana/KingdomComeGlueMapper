import copy
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
import xml.etree.ElementTree as E

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'tools'))
from campaign_entity_links import native_guid, guid_value
from character_sleep_clock import plan_clocks, statistics, summarize, source_entries
from character_sleep_beds import candidates, inside
from character_sleep_work import bind, identity
from character_city_benches import signature
from campaign_trigger_areas import TriggerArea
from character_person_activity import validate_scheduler_targets
from character_schedule_world import baseline_schedule_names, bind_arrivals


def person(index=1, job='villager', schedule=None, home=None):
    actor = E.Element('Entity', EntityId=str(index), EntityGuid=str(index), Pos='0,0,0')
    return dict(actor=actor, soul=dict(soul_id=str(index), social_class_id=job), ai=dict(
        schedule=schedule or [dict(activity='work', start_minute=0)],
        source_social_class=dict(social_class_name=job), links=[] if home is None else
        [dict(label='Home,owner', source_xml=E.tostring(home, encoding='unicode'), target=home.attrib)]))


def fixture():
    mission = E.Element('Entities'); rows = E.Element('Schedulers'); scheduler = E.Element('Root'); scheduler.append(rows)
    for i, name, cls in [(1,'worker','NPC'),(2,'work','TagPoint'),(3,'gm_world_bed_10_bed','StanceSmartObject')]:
        e = E.SubElement(mission,'Entity',Name=name,EntityClass=cls,EntityId=str(i),EntityGuid=native_guid(i),Pos='0,0,0')
        E.SubElement(e,'Properties',guidSmartObjectType='bed' if i==3 else 'other')
        r = E.SubElement(rows,'C_SmartHub',EntityGuid=str(i),IgnoreDeadEnds='false',StupidHub='false')
        if i==3:E.SubElement(E.SubElement(r,'Effects'),'EffectHeal',Role='sleeper',HealRate='25')
    work=E.SubElement(E.SubElement(rows[0],'Links'),'S_ActivityLink',TargetGuid='2',PositioningDelegate='0')
    E.SubElement(work,'Parameters',BehaviorName='work',Priority='0',TimeOfDayStart='0',TimeOfDayEnd='1440')
    activity=E.Element('S_ActivityLink',TargetGuid='3',PositioningDelegate='0')
    E.SubElement(activity,'Parameters',BehaviorName='use',ProvidedRole='sleeper',Priority='0',
                 TimeOfDayStart='0',TimeOfDayEnd='1440',OneTimeUse='false',HaltOnInvalid='false')
    choices=[dict(source_id='10',kind='home',rank=11)]
    clock=dict(intervals=[(0,420),(1320,1440)])
    return mission,scheduler,activity,choices,clock


class SleepClockTests(unittest.TestCase):
    def test_generated_sleep_ending_at_midnight_has_no_empty_interval(self):
        class Seed:
            def digest(self): return bytes(8)
        with patch('character_sleep_clock.hashlib.sha256', return_value=Seed()):
            # The fixed offset is -10 minutes: 16:10 becomes 16:00.
            with patch('character_sleep_clock.summarize', return_value=dict(
                    start_minute=970, duration_minutes=480, variation_minutes=10, samples=1)):
                clock = plan_clocks({'worker': person()}, {'villager': [(1320, 480)]})
        self.assertEqual(clock['worker']['intervals'], [(960, 1440)])

    def test_midnight_mean_is_not_noon(self):
        stats=summarize([(1430,480),(10,480)])
        self.assertEqual(stats['start_minute'],0)
        self.assertEqual(stats['duration_minutes'],480)

    def test_source_clock_wins_and_nontrivial_schedule_is_not_invented(self):
        source=[dict(activity='work',start_minute=420),dict(activity='sleep',start_minute=1320)]
        people={'authored':person(schedule=source),'complex':person(schedule=[dict(activity='work',start_minute=0),dict(activity='eat',start_minute=720)])}
        result=plan_clocks(people,{'villager':[(1200,600)]})
        self.assertEqual(result,{'authored':dict(mode='source',intervals=[(0,420),(1320,1440)])})

    def test_job_average_stable_variation_for_both_genders(self):
        people={str(i):person(i) for i in range(1,15)}
        result=plan_clocks(people,{'villager':[(1320,480),(1380,480)]})
        self.assertEqual(result,plan_clocks(dict(reversed(list(people.items()))),{'villager':[(1320,480),(1380,480)]}))
        self.assertGreater(len({r['offset_minutes'] for r in result.values()}),1)
        for r in result.values():
            self.assertEqual(sum(b-a for a,b in r['intervals']),480)
            self.assertLessEqual(abs(r['offset_minutes']),30)

    def test_guards_rotate_and_do_not_all_sleep_together(self):
        people={str(i):person(i,'guard') for i in range(1,5)}
        result=plan_clocks(people,{'guard':[(1320,480),(480,480)]})
        self.assertEqual(sum(r['shift']=='night_duty' for r in result.values()),2)
        for minute in range(1440):
            asleep=sum(any(a<=minute<b for a,b in r['intervals']) for r in result.values())
            self.assertLess(asleep,4)

    def test_invalid_samples_and_animals_do_not_enter_average(self):
        good=dict(brain_id='human',social_class_id='villager',activity_0='work',time_0='06:00',activity_1='sleep',time_1='22:00')
        bad=dict(good,time_1='25:20'); animal=dict(good,brain_id='animal')
        duplicate=dict(good,time_1='06:00')
        self.assertEqual(statistics([good,bad,animal,duplicate],{'human'}),{'villager':[(1320,480)]})
        self.assertEqual(source_entries(bad),[])


class SleepBedTests(unittest.TestCase):
    def test_preferred_home_shared_and_public_fallback_are_ordered(self):
        home=E.Element('Entity',EntityGuid='10');links=E.SubElement(home,'EntityLinks')
        for sid in ('1','2','3'):E.SubElement(links,'Link',TargetId=sid,Name='')
        records={sid:dict(preferred=set(),position=(10,0,0),public=False,quality=1,public_evidence='test') for sid in ('1','2','3','4','5')}
        records['1']['preferred']={'1'}; records['2']['preferred']={'99'}
        records['4']['public']=True;records['5'].update(public=True,position=(1000,0,0))
        result=candidates(person(home=home),records)
        self.assertEqual([r['source_id'] for r in result],['1','3','4'])
        self.assertEqual([r['kind'] for r in result],['preferred_home','home','public_fallback'])

    def test_no_home_uses_only_bounded_public_places_and_current_placement(self):
        records={'1':dict(preferred=set(),position=(1000,0,0),public=True,quality=0,public_evidence='test')}
        self.assertEqual(candidates(person(),records),[])
        self.assertEqual(len(candidates(person(),records,position=(1000,0,0))),1)
        records['1']['public']=False
        self.assertEqual(candidates(person(),records,position=(1000,0,0)),[])

    def test_private_home_polygon_has_height(self):
        area=TriggerArea(1,3,((0,0,0),(10,0,0),(10,10,0),(0,10,0)))
        self.assertTrue(inside((5,5,1),area));self.assertFalse(inside((11,5,1),area))
        self.assertFalse(inside((5,5,10),area))


class SleepBindingTests(unittest.TestCase):
    def test_later_work_upgrade_preserves_additive_sleep(self):
        m,s,a,c,clock=fixture()
        m[1].set('Name','gm_person_idle_worker')
        idle=s.find('Schedulers')[0].find('Links')[0]
        idle.set('PositioningDelegate','2');idle.find('Parameters').set('BehaviorName','schedulerWait')
        bind(m,s,'worker',clock,c,'bed',a)
        before=[signature(l) for l in s.find('Schedulers')[0].find('Links') if l is not idle]
        files={'objects_mission0.xml':E.tostring(m),'tables/ai/scheduler.xml':E.tostring(s),
               'waitinglinks.xml':b'<StaticLinksInfo version="1"><WaitingLinks/></StaticLinksInfo>'}
        self.assertEqual(baseline_schedule_names(files,{'worker'}),{'worker'})
        entry=dict(arrival=dict(EntityGuid=native_guid(8),EntityId='8',Pos='10,0,0'),
                   start_minute=0,end_minute=1440,activity='work',behavior=dict(tree_name='work'))
        with patch('character_schedule_world.native_wait_activity',return_value=(a,None)):
            result,_=bind_arrivals(files,{'worker':[entry]},None)
        row=E.fromstring(result['tables/ai/scheduler.xml']).find('Schedulers')[0]
        after=[signature(l) for l in row.find('Links')]
        self.assertTrue(all(link in after for link in before))
        self.assertFalse(any(l.find('Parameters').get('BehaviorName')=='schedulerWait' for l in row.find('Links')))
        self.assertEqual(baseline_schedule_names(result,{'worker'}),set())

    def test_clock_shared_resource_and_work_quest_preservation(self):
        m,s,a,choices,clock=fixture(); row=s.find('Schedulers')[0]
        quest=copy.deepcopy(row.find('Links')[0]);quest.find('Parameters').set('Priority','159');row.find('Links').append(quest)
        before=[signature(l) for l in row.find('Links')]
        beds,links,changed=bind(m,s,'worker',clock,choices,'bed',a)
        self.assertTrue(changed);validate_scheduler_targets(s)
        self.assertEqual(before,[signature(l) for l in list(row.find('Links'))[:2]])
        for minute in range(1440):
            sleep=[l for l in row.find('Links') if l.get('TargetGuid')==str(guid_value(identity(m[0])))]
            self.assertEqual(any(int(l.find('Parameters').get('TimeOfDayStart'))<=minute<int(l.find('Parameters').get('TimeOfDayEnd')) for l in sleep),minute<420 or minute>=1320)
        self.assertEqual(len([e for e in m if e.get('EntityClass')=='StanceSmartObject']),1)

    def test_second_person_shares_bed_and_repeat_is_identical(self):
        m,s,a,c,clock=fixture();bind(m,s,'worker',clock,c,'bed',a)
        other=copy.deepcopy(m[0]);other.set('Name','another');other.set('EntityGuid',native_guid(99));other.set('EntityId','99');other.remove(other.find('EntityLinks'));m.append(other)
        row=copy.deepcopy(s.find('Schedulers')[0]);row.set('EntityGuid','99');row.find('Links').remove(row.find('Links')[1]);row.find('Links').remove(row.find('Links')[1]);s.find('Schedulers').append(row)
        bind(m,s,'another',clock,c,'bed',a)
        before=(E.tostring(m),E.tostring(s));self.assertFalse(bind(m,s,'worker',clock,c,'bed',a)[2])
        self.assertEqual(before,(E.tostring(m),E.tostring(s)))
        self.assertEqual(len([e for e in m if e.get('EntityClass')=='StanceSmartObject']),1)
        validate_scheduler_targets(s)

    def test_foreign_bed_dependencies_rejected_without_mutation(self):
        m,s,a,c,clock=fixture();E.SubElement(E.SubElement(s.find('Schedulers')[2],'Links'),'S_ActivityLink',TargetGuid='2')
        before=(E.tostring(m),E.tostring(s))
        with self.assertRaisesRegex(ValueError,'foreign dependencies'):bind(m,s,'worker',clock,c,'bed',a)
        self.assertEqual(before,(E.tostring(m),E.tostring(s)))

    def test_missing_bed_does_not_disable_work(self):
        m,s,a,c,clock=fixture();c[0]['source_id']='missing';before=(E.tostring(m),E.tostring(s))
        self.assertEqual(bind(m,s,'worker',clock,c,'bed',a),(None,[],False))
        self.assertEqual(before,(E.tostring(m),E.tostring(s)))

    def test_changed_repeat_policy_rejected(self):
        m,s,a,c,clock=fixture();bind(m,s,'worker',clock,c,'bed',a);clock['intervals']=[(0,600)]
        with self.assertRaisesRegex(ValueError,'differs'):bind(m,s,'worker',clock,c,'bed',a)

    def test_missing_actor_graph_link_is_rejected_on_repeat(self):
        m,s,a,c,clock=fixture();bind(m,s,'worker',clock,c,'bed',a)
        m[0].remove(m[0].find('EntityLinks'))
        with self.assertRaisesRegex(ValueError,'differs'):bind(m,s,'worker',clock,c,'bed',a)

    def test_wrong_bed_graph_link_tag_is_rejected_on_repeat(self):
        m,s,a,c,clock=fixture();bind(m,s,'worker',clock,c,'bed',a)
        m[-1].find('EntityLinks/Link').set('Name','wrong')
        with self.assertRaisesRegex(ValueError,'differs'):bind(m,s,'worker',clock,c,'bed',a)

    def test_authored_bed_schedule_preserved(self):
        m,s,a,c,clock=fixture();s.find('Schedulers')[0].find('Links').append(a)
        before=(E.tostring(m),E.tostring(s));self.assertEqual(bind(m,s,'worker',clock,c,'bed',a),(None,[],False))
        self.assertEqual(before,(E.tostring(m),E.tostring(s)))


if __name__=='__main__':unittest.main()
