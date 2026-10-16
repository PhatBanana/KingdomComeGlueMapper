import sys
import unittest
from pathlib import Path
import xml.etree.ElementTree as E

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from campaign_work_dependencies import discover, templates, import_all, merge_world
from campaign_dependency_adapters import EntityAdapter
from campaign_dependencies import DependencyImporter
from campaign_entity_links import native_guid
from campaign_trigger_areas import write_areas
from quest_import import ast


def record(number, cls, props=''):
    entity = E.fromstring(f'<Entity EntityId="{number}" EntityGuid="{number:016X}" '
                         f'EntityClass="{cls}" Name="arbitrary{number}" Pos="1,2,3">{props}</Entity>')
    return dict(attributes=dict(entity.attrib), entity=ast(entity), source='source-layer.xml')


class WorkDependencyTests(unittest.TestCase):
    def test_unlinked_workplace_resolves_authored_edges_from_full_level(self):
        workplace = record(1, 'SmartObjectHolder', '<EntityLinks><Link Name="tool" '
            'TargetId="2" TargetGuid="0000000000000002"/></EntityLinks>')
        all_entities = {'work':workplace, 'tool':record(2,'ItemSlot'), 'unrelated':record(3,'TagPoint')}
        closure = discover(dict(entities=all_entities,links=[]), ['0000000000000001'])
        merged = merge_world(dict(entities={}, links=[], unresolved=[]),all_entities,{'q':closure})
        self.assertEqual(set(merged['entities']), {'work','tool'})
        self.assertEqual(merged['links'][0]['to'],'tool')
        self.assertFalse(merged['unresolved'])
        again = merge_world(merged,all_entities,{'q':closure})
        self.assertEqual(again['links'],merged['links'])

    def test_authored_guid_id_disagreement_is_not_followed(self):
        workplace = record(1, 'SmartObjectHolder', '<EntityLinks><Link Name="tool" '
            'TargetId="3" TargetGuid="0000000000000002"/></EntityLinks>')
        closure = discover(dict(entities={'work':workplace,'tool':record(2,'ItemSlot')},links=[]),
                           ['0000000000000001'])
        self.assertEqual(len(closure['entities']),1)
        self.assertIn('disagree',closure['unresolved'][0]['reason'])

    def test_cycle_does_not_hide_tools_or_expand_other_residents(self):
        world = dict(entities={str(n): record(n, cls) for n, cls in
            [(1,'SmartAreaShape'),(2,'SmartObjectHolder'),(3,'ItemSlot'),(4,'NPC'),(5,'TagPoint')]},
            links=[dict(**{'from': a, 'to': b}, source_link={'Name': tag}) for a,b,tag in
                   [('1','2','work'),('2','3','tool'),('3','2','return'),('2','4','owner'),('4','5','otherJob')]])
        result = discover(world, ['0000000000000001'])
        self.assertEqual({r['source'] for r in result['entities']}, {'1','2','3','4'})
        self.assertEqual(len(result['edges']), 4)
        self.assertFalse(result['unresolved'])

    def test_missing_endpoint_reported_and_failed_parent_does_not_hide_children(self):
        world = dict(entities={'1': record(1,'SmartObjectHolder')},
                     links=[{'from':'1','to':'absent','source_link':{'Name':'tool'}}])
        closure = discover(world, ['0000000000000001'])
        self.assertIn('Missing source', closure['unresolved'][0]['reason'])
        class Importer:
            def ensure(self, group, guid, site): return None
        report = import_all({'quest':closure}, Importer())
        self.assertIsNone(report[0]['target'])
        self.assertEqual(report[0]['guid'], native_guid(1))

    def test_work_holder_preserves_template_category_and_source_placement(self):
        holder = record(1,'SmartObjectHolder', '<Properties guidSmartObjectType="original-template" '
            'sWH_AI_EntityCategory="WorkPivot" soclasses_SmartObjectHelpers="" bSaved_by_game="1" '
            'object_editorModel="editor-only.cgf"><Script Misc=""/></Properties>')
        closure = {'quest': discover(dict(entities={'1':holder},links=[]), ['0000000000000001'])}
        bindings = templates(closure, 'SmartObjectHolder', 'guidSmartObjectType')
        adapter = EntityAdapter(dict(entities={'1':holder}), E.fromstring('<Root/>'), write_areas([],1),1,
                                smart_objects=bindings)
        importer = DependencyImporter({'entities':adapter},
                    {'smart_entities':{'quest|original-template':'converted-template'}})
        self.assertEqual(importer.ensure('entities',native_guid(1)),native_guid(1))
        output = E.fromstring(importer.files['world/entities/'+native_guid(1)+'.xml'])
        self.assertEqual(output.get('Pos'),'1,2,3')
        self.assertEqual(output.find('Properties').get('guidSmartObjectType'),'converted-template')
        self.assertEqual(output.find('Properties').get('sWH_AI_EntityCategory'),'WorkPivot')
        self.assertNotIn('object_editorModel',output.find('Properties').attrib)

    def test_unconverted_helpers_are_not_silently_dropped(self):
        holder = record(1,'SmartObjectHolder', '<Properties soclasses_SmartObjectHelpers="customStand"/>')
        adapter = EntityAdapter(dict(entities={'1':holder}),E.fromstring('<Root/>'),write_areas([],1),1)
        importer = DependencyImporter({'entities':adapter})
        self.assertIsNone(importer.ensure('entities',native_guid(1)))
        self.assertFalse(importer.files)
        self.assertIn(('work_helpers','customstand'),importer.jobs)
        importer = DependencyImporter({'entities':adapter}, {'work_helpers':{'customstand':'nativeStand'}})
        self.assertEqual(importer.ensure('entities',native_guid(1)),native_guid(1))
        output = E.fromstring(importer.files['world/entities/'+native_guid(1)+'.xml'])
        self.assertEqual(output.find('Properties').get('soclass_SmartObjectHelpers'),'nativeStand')


if __name__ == '__main__': unittest.main()
