import copy
from pathlib import Path
import sys
import unittest
import xml.etree.ElementTree as E

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'tools'))
import character_work_pool as pool
from campaign_entity_links import native_guid, guid_value
from character_city_benches import signature
from character_person_activity import validate_scheduler_targets
import test_character_city_work as city_fixture


class WorkPoolTests(unittest.TestCase):
    def fixture(self):
        files, schedules = city_fixture.CityWorkTests().prepared()
        mission = E.fromstring(files['objects_mission0.xml'])
        scheduler = E.fromstring(files['tables/ai/scheduler.xml'])
        edges = scheduler.find('Schedulers')[0].find('Links')
        extra = copy.deepcopy(edges[0])
        extra.find('Parameters').set('TimeOfDayStart', '780')
        extra.find('Parameters').set('TimeOfDayEnd', '1080')
        edges.append(extra)
        mission.find("Entity[@Name='person']").set('EntityClass', 'NPC_Female')
        resource = E.SubElement(mission, 'Entity', EntityId='500', EntityGuid=native_guid(500), Name='shared_fire', Pos='1,2,3')
        leaf = E.Element('C_SmartHub', EntityGuid='500', IgnoreDeadEnds='false', StupidHub='false')
        activity = E.fromstring('''<S_ActivityLink TargetGuid="500" PositioningDelegate="0"><Parameters
            BehaviorName="cooking" BehaviorOverride="false" ProvidedRole="cooking" AllowedGenders="0"
            Priority="0" Privileged="false" TimeOfDayStart="0" TimeOfDayEnd="1440" HaltOnInvalid="false"/>
            </S_ActivityLink>''')
        return mission, scheduler, schedules['person'][0], [(resource, leaf)], activity

    def test_preserves_original_work_and_shared_resource_clock(self):
        m, s, entry, resources, activity = self.fixture()
        original = copy.deepcopy(s.find('Schedulers')[0])
        job, waiting, clock = pool.bind(m, s, 'person', entry, 'Cooking', resources, activity)
        self.assertEqual(clock, [(300, 720), (780, 1080)])
        owner = s.find('Schedulers')[0]
        self.assertEqual([signature(x) for x in owner.find('Links')[:len(original.find('Links'))]],
                         [signature(x) for x in original.find('Links')])
        terminal = s.find("Schedulers/C_SmartHub[@EntityGuid='500']")
        self.assertIsNotNone(terminal)
        hub = s.find("Schedulers/C_SmartHub[@EntityGuid='"+str(guid_value(job.get('EntityGuid')))+"']")
        p = hub.find('Links/S_ActivityLink/Parameters')
        self.assertEqual((p.get('TimeOfDayStart'), p.get('TimeOfDayEnd')), ('0', '1440'))
        self.assertEqual(p.get('ProvidedRole'), 'cooking')
        self.assertEqual(len(waiting), 2)
        validate_scheduler_targets(s)
        before = signature(m), signature(s)
        self.assertEqual(pool.bind(m, s, 'person', entry, 'Cooking', resources, activity)[1], [])
        self.assertEqual(before, (signature(m), signature(s)))

    def test_embroidery_override_is_on_pool_not_shared_seat(self):
        m, s, entry, resources, activity = self.fixture()
        p = activity.find('Parameters'); p.set('BehaviorName', 'embroidery'); p.set('AllowedGenders', '2')
        p.set('BehaviorOverride', 'true'); p.attrib.pop('ProvidedRole')
        job, _, _ = pool.bind(m, s, 'person', entry, 'embroider_sit', resources, activity, template='benchActivity')
        hub = s.find("Schedulers/C_SmartHub[@EntityGuid='"+str(guid_value(job.get('EntityGuid')))+"']")
        outgoing = hub.find('Links/S_ActivityLink/Parameters')
        self.assertEqual(outgoing.get('BehaviorName'), 'use')
        self.assertEqual(outgoing.get('AllowedGenders'), '0')
        self.assertEqual(outgoing.get('BehaviorOverride'), 'false')
        incoming = [l.find('Parameters') for l in s.find('Schedulers')[0].find('Links')
                    if l.get('TargetGuid') == hub.get('EntityGuid')]
        self.assertTrue(all(p.get('BehaviorName') == 'embroidery' and p.get('AllowedGenders') == '2' for p in incoming))

    def test_foreign_or_changed_ownership_rejected_atomically(self):
        for change in ('quest', 'identity', 'resource', 'phase'):
            with self.subTest(change=change):
                m, s, entry, resources, activity = self.fixture()
                if change == 'quest': s.find('.//S_ActivityLink/Parameters').set('RequiredRole', 'quest')
                if change == 'identity':
                    next(e for e in m if e.get('Name', '').startswith('gm_schedule_')).set('EntityGuid', native_guid(123))
                if change == 'resource':
                    row = E.SubElement(s.find('Schedulers'), 'C_SmartHub', EntityGuid='500'); E.SubElement(row, 'Links')
                if change == 'phase':
                    job, _, _ = pool.bind(m, s, 'person', entry, 'Cooking', resources, activity)
                    job.find('EntityLinks/Link').set('Name', 'foreign')
                before = signature(m), signature(s)
                with self.assertRaises(ValueError): pool.bind(m, s, 'person', entry, 'Cooking', resources, activity)
                self.assertEqual(before, (signature(m), signature(s)))

    def test_clipped_source_clock_is_inherited(self):
        m, s, entry, resources, activity = self.fixture()
        for l in s.find('Schedulers')[0].find('Links'):
            p = l.find('Parameters')
            if p.get('TimeOfDayStart') == '300': p.set('TimeOfDayStart', '420')
        _, _, clock = pool.bind(m, s, 'person', entry, 'Cooking', resources, activity)
        self.assertEqual(clock, [(420, 720), (780, 1080)])


if __name__ == '__main__': unittest.main()
