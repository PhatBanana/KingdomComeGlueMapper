import sys
from pathlib import Path
import unittest
import xml.etree.ElementTree as E
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from campaign_world_objects import merge
from campaign_entity_links import native_guid as guid


class WorldObjectMergeTests(unittest.TestCase):
    def fixture(self):
        world = E.Element('Objects')
        visual = E.SubElement(world, 'Entity', Name='glue_item_73', EntityClass='GeomEntity',
                              EntityId='40', EntityGuid=guid(40))
        existing = E.SubElement(world, 'Entity', Name='existing', EntityClass='TagPoint',
                               EntityId='90', EntityGuid=guid(90))
        E.SubElement(E.SubElement(existing, 'EntityLinks'), 'Link', TargetId='40', Name='tool')
        fragment = E.Element('Objects')
        tool = E.SubElement(fragment, 'Entity', Name='tool', EntityClass='ItemSlot',
                           EntityId='1', EntityGuid=guid(1))
        worker = E.SubElement(fragment, 'Entity', Name='worker', EntityClass='TagPoint',
                             EntityId='2', EntityGuid=guid(2))
        E.SubElement(E.SubElement(worker, 'EntityLinks'), 'Link', TargetId='1', Name='reservation')
        jobs = [dict(group='entities', status='imported', target=guid(1),
                     evidence={'replaces_visual_entities': ['glue_item_73']})]
        return world, fragment, jobs

    def test_merge_removes_visual_and_remaps_both_numeric_link_domains(self):
        world, fragment, jobs = self.fixture()
        data, report = merge(E.tostring(world), E.tostring(fragment), jobs)
        entities = {e.get('Name'):e for e in E.fromstring(data)}
        self.assertNotIn('glue_item_73', entities)
        self.assertEqual(entities['existing'].get('EntityId'), '90')
        self.assertEqual(entities['tool'].get('EntityId'), '91')
        for name in ('existing', 'worker'):
            link = entities[name].find('EntityLinks/Link')
            self.assertEqual(link.get('TargetId'), '91')
            self.assertEqual(link.get('TargetGuid'), guid(1))
        self.assertEqual(report['removed_visuals'], ['glue_item_73'])

    def test_failed_conversion_never_removes_visual(self):
        world, fragment, jobs = self.fixture()
        jobs[0]['status'] = 'conversion_failed'
        data, report = merge(E.tostring(world), E.tostring(fragment), jobs)
        self.assertIsNotNone(E.fromstring(data).find("Entity[@Name='glue_item_73']"))
        self.assertFalse(report['removed_visuals'])

    def test_missing_placement_and_live_entity_replacements_are_rejected(self):
        world, fragment, jobs = self.fixture()
        jobs[0]['target'] = guid(500)
        with self.assertRaisesRegex(ValueError, 'no converted placement'):
            merge(E.tostring(world), E.tostring(fragment), jobs)
        jobs[0]['target'] = guid(1)
        world[0].set('EntityClass', 'NPC')
        with self.assertRaisesRegex(ValueError, 'gameplay entity'):
            merge(E.tostring(world), E.tostring(fragment), jobs)

    def test_collision_does_not_silently_overwrite_existing_actor(self):
        world, fragment, jobs = self.fixture()
        fragment[1].set('EntityGuid', guid(90))
        with self.assertRaisesRegex(ValueError, 'collides'):
            merge(E.tostring(world), E.tostring(fragment), jobs)

    def test_attached_child_cannot_be_left_with_removed_parent(self):
        world, fragment, jobs = self.fixture()
        world[1].set('ParentId', '40')
        with self.assertRaisesRegex(ValueError, 'attached child'):
            merge(E.tostring(world), E.tostring(fragment), jobs)


if __name__ == '__main__': unittest.main()
