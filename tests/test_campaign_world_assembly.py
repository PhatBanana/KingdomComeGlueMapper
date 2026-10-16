from pathlib import Path
import sys
import unittest
import xml.etree.ElementTree as E
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from campaign_entity_links import native_guid as guid, append_links
from campaign_trigger_areas import TriggerArea, read_areas, write_areas
from campaign_world_assembly import assemble, PREFIX


class WorldAssemblyTests(unittest.TestCase):
    def fixture(self):
        base = {'objects_mission0.xml': b'<Objects/>',
                'whdata_0': b'<Root version="1"><AI><Keep/></AI><SoulList><Souls/></SoulList></Root>',
                'triggerareas.fubar': write_areas([], 99)}
        objects = E.Element('Objects')
        for i, cls in [(1, 'NPC'), (2, 'TriggerArea'), (3, 'SmartObjectHolder')]:
            E.SubElement(objects, 'Entity', EntityGuid=guid(i), EntityId=str(i), EntityClass=cls)
        souls = E.fromstring('<Root version="1"><SoulList><Souls/></SoulList></Root>')
        soul = E.SubElement(souls.find('SoulList/Souls'), 'Soul', version='8')
        E.SubElement(soul, 'Guid').text = 'instance-id'
        E.SubElement(soul, 'EntityGuid').text = guid(1)
        data = {'objects_mission0.xml': E.tostring(objects), 'whdata_0': E.tostring(souls),
                'triggerareas.fubar': write_areas([TriggerArea(2, 3, ((0,0,0),(1,1,1)))],99),
                'waitinglinks.xml': append_links(None, [(guid(1),guid(3),'_,work')]),
                'tables/ai/scheduler.xml': b'<database><Schedulers version="1"><C_SmartHub EntityGuid="1"><Links><S_ActivityLink TargetGuid="3" PositioningDelegate="0"><Parameters BehaviorName="work"/></S_ActivityLink></Links></C_SmartHub><C_SmartHub EntityGuid="3"/></Schedulers></database>',
                'smartobjecthelpersetanimations.xml': b'<SmartObjectAnimationCollections><Collection HelperSetName="tools"><SmartObjectHelperSetAnimationCollection HashValue="12"/></Collection></SmartObjectAnimationCollections>',
                'tables/ai/smartobjectanimations.xml': b'<database><SmartObjectAnimationss version="1"><SmartObjectAnimations EntityGuid="3" Hash="12"><SmartObjectTransform Position="1,2,3" Rotation="1,0,0,0"/></SmartObjectAnimations></SmartObjectAnimationss></database>'}
        return base, {PREFIX+p:v for p,v in data.items()}

    def test_assembles_connected_resources_and_preserves_world_metadata(self):
        base, registration = self.fixture()
        output, report = assemble(base, registration, [])
        self.assertEqual(len(output), 7)
        root = E.fromstring(output['whdata_0'])
        self.assertIsNotNone(root.find('AI/Keep'))
        self.assertEqual(root.findtext('SoulList/Souls/Soul/EntityGuid'), guid(1))
        self.assertEqual(read_areas(output['triggerareas.fubar'])['export_version'], 99)
        self.assertEqual(report['resource_additions']['whdata_0'], 1)
        self.assertEqual(report['objects']['added_entities'], 3)
        self.assertEqual(base['objects_mission0.xml'], b'<Objects/>')

    def test_unrelated_baseline_actor_and_scheduler_are_retained(self):
        base, registration = self.fixture()
        base['objects_mission0.xml'] = ('<Objects><Entity EntityId="50" EntityGuid="'+guid(50)+'"/></Objects>').encode()
        base['tables/ai/scheduler.xml'] = b'<database><Schedulers version="1"><C_SmartHub EntityGuid="50"/></Schedulers></database>'
        output, _ = assemble(base, registration, [])
        self.assertIsNotNone(E.fromstring(output['objects_mission0.xml']).find("Entity[@EntityId='50']"))
        self.assertEqual(len(E.fromstring(output['tables/ai/scheduler.xml']).find('Schedulers')), 3)

    def test_missing_actor_and_schedule_targets_are_rejected(self):
        for path, old, new in [('whdata_0', guid(1), guid(999)),
                               ('tables/ai/scheduler.xml', 'TargetGuid="3"', 'TargetGuid="999"')]:
            base, registration = self.fixture()
            registration[PREFIX+path] = registration[PREFIX+path].replace(old.encode(),new.encode())
            with self.assertRaisesRegex(ValueError, 'no assembled'):
                assemble(base, registration, [])

    def test_mismatched_export_and_unknown_resource_are_rejected(self):
        base, registration = self.fixture()
        base['triggerareas.fubar'] = write_areas([],100)
        with self.assertRaisesRegex(ValueError, 'export versions'):
            assemble(base, registration, [])
        base, registration = self.fixture()
        registration[PREFIX+'unknown.xml'] = b'<Unknown/>'
        with self.assertRaisesRegex(ValueError, 'requires an adapter'):
            assemble(base, registration, [])

    def test_conflicting_helper_family_is_not_silently_replaced(self):
        base, registration = self.fixture()
        path = 'smartobjecthelpersetanimations.xml'
        base[path] = registration[PREFIX+path].replace(b'HashValue="12"', b'HashValue="99"')
        with self.assertRaisesRegex(ValueError, 'Conflicting helper family'):
            assemble(base, registration, [])

    def test_cross_resource_scheduler_and_animation_dependencies_are_required(self):
        base, registration = self.fixture()
        path = PREFIX+'tables/ai/scheduler.xml'
        registration[path] = registration[path].replace(b'<C_SmartHub EntityGuid="3"/>', b'')
        with self.assertRaisesRegex(ValueError, 'compiled scheduler record'):
            assemble(base, registration, [])
        base, registration = self.fixture()
        registration.pop(PREFIX+'smartobjecthelpersetanimations.xml')
        with self.assertRaisesRegex(ValueError, 'no animation collection'):
            assemble(base, registration, [])


if __name__ == '__main__': unittest.main()
