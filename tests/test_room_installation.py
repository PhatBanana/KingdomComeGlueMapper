import copy
import struct
import sys
from pathlib import Path
import unittest
import xml.etree.ElementTree as E

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from world_brush_edits import edit
from home_bed_assignment import apply
from character_sleep_work import bind, identity
from campaign_entity_links import native_guid, guid_value
from character_city_benches import signature
from test_character_sleep import fixture


class RoomInstallationTests(unittest.TestCase):
    def test_daytime_sleep_splits_night_duty_without_reopening_sleep_hours(self):
        from character_sleep_work import restrict_work_to_waking_hours
        m,s,activity,c,clock=fixture();m[1].set('Name','gm_schedule_guard_work')
        clock['intervals']=[(420,900)]
        bind(m,s,'worker',clock,c,'bed',activity)
        restrict_work_to_waking_hours(m,s)
        links=s.find('Schedulers')[0].find('Links')
        intervals=[(int(l.find('Parameters').get('TimeOfDayStart')),int(l.find('Parameters').get('TimeOfDayEnd')))
                   for l in links if l.get('TargetGuid')=='2']
        self.assertEqual(intervals,[(0,420),(900,1440)])
        self.assertEqual(restrict_work_to_waking_hours(m,s),[])

    def test_sleep_clock_excludes_generated_work_and_preserves_quest_edges(self):
        from character_sleep_work import restrict_work_to_waking_hours
        m,s,activity,c,clock=fixture();m[1].set('Name','gm_schedule_worker_work')
        bind(m,s,'worker',clock,c,'bed',activity)
        links=s.find('Schedulers')[0].find('Links')
        quest=copy.deepcopy(links[0]);quest.find('Parameters').set('Priority','10');links.append(quest)
        original_quest=signature(quest)
        self.assertEqual(restrict_work_to_waking_hours(m,s),['worker'])
        work=[l for l in links if l.get('TargetGuid')=='2' and l.find('Parameters').get('Priority')=='0']
        self.assertEqual(len(work),1)
        self.assertEqual((work[0].find('Parameters').get('TimeOfDayStart'),work[0].find('Parameters').get('TimeOfDayEnd')),('420','1320'))
        self.assertEqual(work[0].find('Parameters').get('HaltOnInvalid'),'true')
        self.assertEqual(signature(quest),original_quest)
        self.assertEqual(restrict_work_to_waking_hours(m,s),[])

    def test_previously_bounded_work_is_migrated_to_stop_at_bedtime(self):
        from character_sleep_work import restrict_work_to_waking_hours
        m,s,activity,c,clock=fixture();m[1].set('Name','gm_schedule_worker_work')
        bind(m,s,'worker',clock,c,'bed',activity)
        work=s.find('Schedulers')[0].find('Links')[0].find('Parameters')
        work.set('TimeOfDayStart','420');work.set('TimeOfDayEnd','1320')
        work.set('HaltOnInvalid','false')
        self.assertEqual(restrict_work_to_waking_hours(m,s),['worker'])
        self.assertEqual(work.get('HaltOnInvalid'),'true')
        self.assertEqual(restrict_work_to_waking_hours(m,s),[])

    def test_brush_move_remove_preserves_unrelated_bytes_and_reindexes_blocks(self):
        record=bytearray(104)
        struct.pack_into('<I6f',record,0,1,0,0,0,1,1,1)
        struct.pack_into('<12f',record,44,1,0,0,0,0,1,0,0,0,0,1,0)
        other=bytearray(record);struct.pack_into('<f',other,56,5)
        block=bytes(record+other)
        data=struct.pack('<II',2,len(block))+block+struct.pack('<I',len(record))+record
        metadata=b'<Root><HLod DataOffset="4" DataSize="212" Pos="0,0,0" Radius="20"/><HLod DataOffset="216" DataSize="108" Pos="0,0,0" Radius="20"/></Root>'
        # Identical source placements must fail rather than move both.
        change=dict(position=(0,0,0),bbox=(0,0,0,1,1,1),delta=(1,0,0))
        with self.assertRaisesRegex(ValueError,'duplicate'):edit(data,metadata,[change])
        unique=struct.pack('<II',2,len(block))+block
        meta=b'<Root><HLod DataOffset="4" DataSize="212" Pos="0,0,0" Radius="20"/></Root>'
        moved,_=edit(unique,meta,[change])
        self.assertEqual(moved[112:],other)
        self.assertEqual(struct.unpack_from('<f',moved,8+56)[0],1)
        removed,newmeta=edit(unique,meta,[dict(change,delta=None)])
        self.assertEqual(removed[8:],other)
        self.assertEqual(E.fromstring(newmeta)[0].get('DataSize'),'108')

    def test_home_bed_assignment_keeps_work_hours_and_repeat_is_identical(self):
        m,s,activity,c,clock=fixture()
        bind(m,s,'worker',clock,c,'bed',activity)
        actor=m[0];assigned=copy.deepcopy(m[2]);assigned.set('Name','assigned_bed')
        assigned.set('EntityId','50');assigned.set('EntityGuid',native_guid(50));m.append(assigned)
        assigned.set('Pos','10,20,30')
        E.SubElement(actor.find('EntityLinks'),'Link',Name='sleepBed',TargetId='50',TargetGuid=native_guid(50))
        E.SubElement(E.SubElement(assigned,'EntityLinks'),'Link',Name='preferedSleeper',
                     TargetId=actor.get('EntityId'),TargetGuid=actor.get('EntityGuid'))
        row=copy.deepcopy(s.find('Schedulers')[2]);row.set('EntityGuid','50');s.find('Schedulers').append(row)
        before=[signature(l) for l in s.find('Schedulers')[0].find('Links')]
        files={'objects_mission0.xml':E.tostring(m),'tables/ai/scheduler.xml':E.tostring(s),
               'waitinglinks.xml':b'<StaticLinksInfo version="1"><WaitingLinks/></StaticLinksInfo>'}
        result=apply(files);self.assertEqual(result,apply(result))
        rows=E.fromstring(result['tables/ai/scheduler.xml']).find('Schedulers')
        self.assertEqual(before,[signature(l) for l in rows[0].find('Links')])
        pool=next(r for r in rows if r.get('EntityGuid')==str(guid_value(identity(actor))))
        self.assertEqual(pool.get('Position'),'10,20,30')
        pool_entity=next(e for e in E.fromstring(result['objects_mission0.xml']) if e.get('EntityGuid')==identity(actor))
        self.assertEqual(pool_entity.get('Pos'),'10,20,30')
        links=pool.findall("Links/S_ActivityLink[@TargetGuid='50']")
        self.assertEqual({(int(l.find('Parameters').get('TimeOfDayStart')),int(l.find('Parameters').get('TimeOfDayEnd'))) for l in links},set(clock['intervals']))
        self.assertTrue(all(l.find('Parameters').get('Priority')=='100' for l in links))
        # A later generic sleep upgrade must recognize the installed assignment,
        # rather than rejecting it or putting the actor back on fallback beds.
        from home_bed_assignment import choices
        installed=E.fromstring(result['objects_mission0.xml'])
        scheduler=E.fromstring(result['tables/ai/scheduler.xml'])
        before_schedule=E.tostring(scheduler)
        beds,network,changed=bind(installed,scheduler,'worker',clock,
                                c+choices(installed,installed[0]),'bed',activity)
        self.assertFalse(changed)
        self.assertEqual(network,[])
        self.assertEqual(E.tostring(scheduler),before_schedule)
        self.assertIn('assigned_bed',{b.get('entity_name') for b in beds})


if __name__=='__main__':unittest.main()
