import sys
import unittest
from pathlib import Path
import xml.etree.ElementTree as E
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from campaign_behavior_schedule import connect, source_policy, validate_compiled
from campaign_entity_links import append_links, guid_value
from character_person_activity import validate_scheduler_targets


class BehaviorScheduleTests(unittest.TestCase):
    def test_invalid_template_does_not_leave_an_anchor_or_empty_links(self):
        objects = E.fromstring('<Objects><Entity EntityId="1" EntityGuid="00000001-0000-0000" Pos="1,2,3"/><Entity EntityId="2" EntityGuid="00000002-0000-0000"/></Objects>')
        scheduler = E.fromstring('<database><Schedulers><C_SmartHub EntityGuid="1"/></Schedulers></database>')
        before = E.tostring(objects), E.tostring(scheduler)
        additions = []
        with self.assertRaisesRegex(ValueError, 'parameter contract'):
            connect(objects, additions, objects[0], objects[1], 'job', 55, 'Slow', 'test', scheduler, E.Element('S_ActivityLink'))
        self.assertEqual(before, (E.tostring(objects), E.tostring(scheduler)))
        self.assertEqual(additions, [])

    def test_duplicate_anchor_does_not_add_links_to_baseline(self):
        import uuid
        from campaign_entity_links import native_guid
        guid = native_guid(uuid.uuid5(uuid.NAMESPACE_URL,'test/schedule-anchor').int & ((1<<64)-1))
        objects = E.fromstring('<Objects><Entity EntityId="1" EntityGuid="00000001-0000-0000" Pos="1,2,3"/><Entity EntityId="2" EntityGuid="00000002-0000-0000"/></Objects>')
        E.SubElement(objects,'Entity',EntityId='3',EntityGuid=guid)
        scheduler = E.fromstring('<database><Schedulers><C_SmartHub EntityGuid="1"/></Schedulers></database>')
        before=E.tostring(objects),E.tostring(scheduler);additions=[]
        with self.assertRaisesRegex(ValueError,'identity collision'):
            connect(objects,additions,objects[0],objects[1],'job',55,'Slow','test',scheduler,E.fromstring('<S_ActivityLink><Parameters/></S_ActivityLink>'))
        self.assertEqual(before,(E.tostring(objects),E.tostring(scheduler)));self.assertEqual(additions,[])

    def test_actor_can_reach_host_in_both_exported_networks(self):
        objects = E.fromstring('<Objects><Entity Name="unrelated_actor" EntityId="1" EntityGuid="00000001-0000-0000" Pos="1,2,3"><EntityLinks><Link Name="home" TargetId="2" TargetGuid="00000002-0000-0000"/></EntityLinks></Entity><Entity Name="host" EntityId="2" EntityGuid="00000002-0000-0000"/></Objects>')
        actor, host = list(objects)
        additions = []
        scheduler = E.fromstring('<database><Schedulers><C_SmartHub EntityGuid="1"><Links><S_ActivityLink TargetGuid="1" PositioningDelegate="0"><Parameters BehaviorName="existing"/></S_ActivityLink></Links></C_SmartHub></Schedulers></database>')
        template = E.fromstring('<S_ActivityLink TargetGuid="900" PositioningDelegate="0"><Parameters BehaviorName="schedulerWait" Priority="0" TimeOfDayStart="0" TimeOfDayEnd="1440"/></S_ActivityLink>')
        connect(objects, additions, actor, host, 'custom_work', 72, 'Instant', 'arbitrary', scheduler, template)
        network = E.fromstring(append_links(None, additions))
        edges = {(n.get('SourceId'), n.get('TargetId'), label.text)
                 for n in network.findall('WaitingLinks/WaitingLink') for label in n.findall('LinkDefinition')}
        schedule = actor.find("EntityLinks/Link[@Name='_72,!Instant,custom_work']")
        anchor = next(e for e in objects if e.get('EntityGuid') == schedule.get('TargetGuid'))
        self.assertEqual(anchor.find('EntityLinks/Link').get('TargetGuid'), host.get('EntityGuid'))
        self.assertIn((actor.get('EntityGuid'), anchor.get('EntityGuid'), schedule.get('Name')), edges)
        self.assertIn((anchor.get('EntityGuid'), host.get('EntityGuid'), '^delegate'), edges)
        self.assertIsNotNone(actor.find("EntityLinks/Link[@Name='home']"))
        validate_scheduler_targets(scheduler)
        validate_compiled(objects, scheduler, additions)
        compiled = scheduler.find("Schedulers/C_SmartHub[@EntityGuid='1']/Links")
        self.assertEqual(len(compiled), 2)  # Keep unrelated jobs.
        self.assertEqual(compiled[1].get('TargetGuid'), str(guid_value(host.get('EntityGuid'))))
        self.assertEqual(compiled[1].get('PositioningDelegate'), str(guid_value(anchor.get('EntityGuid'))))
        self.assertEqual(compiled[1].find('Parameters').get('TimeOfDayEnd'), '1440')
        compiled.remove(compiled[1])
        with self.assertRaisesRegex(ValueError, 'no unique compiled activity'):
            validate_compiled(objects, scheduler, additions)

    def test_source_policy_is_not_fixed_to_one_quest(self):
        self.assertEqual(source_policy({'values': 'priority(72), immediate(true)'}), (72, 'Slow'))
        self.assertEqual(source_policy({'values': 'priority(43), immediate(false)'}), (43, 'Slow'))
        self.assertEqual(source_policy({'values': 'priority(43),immediate(true),immediateDaycycleHaltSpeed($enum:daycycleHaltSpeed.fast)'}), (43, 'Fast'))
        with self.assertRaises(ValueError): source_policy({'values': 'priority(43),immediate(true),immediateDaycycleHaltSpeed($speed)'})
        with self.assertRaises(ValueError): source_policy({'values': 'priority(43)'})


if __name__ == '__main__': unittest.main()
