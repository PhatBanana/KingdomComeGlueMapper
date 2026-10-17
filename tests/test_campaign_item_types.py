import sys
from pathlib import Path
import unittest
import xml.etree.ElementTree as E
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from campaign_item_types import resolve, manipulation
from campaign_dependency_adapters import ItemAdapter
from campaign_dependencies import ImportPlan
from test_campaign_dependencies import Tables


class ItemTypeTests(unittest.TestCase):
    def test_placeholder_model_still_supplies_enum_evidence(self):
        from world_item_definitions import WorldItemAdapter, native_item_registry
        identity = '12345678-1234-1234-1234-123456789abc'
        source = [dict(npc_tool_type_id=n, npc_tool_type_name='meal_tray') for n in ('10','25')]
        target = [dict(npc_tool_type_id='10', npc_tool_type_name='chicken_tray'),dict(npc_tool_type_id='25', npc_tool_type_name='meal_tray')]
        native = {identity:E.Element('NPCTool', Id=identity, Type='25', Model='preproduction/traffic_cone/traffic_cone.cgf')}
        tables = Tables({'item/npc_tool_type':source,'item/npc_tool':[dict(item_id=identity,npc_tool_type_id='25')]})
        adapter = WorldItemAdapter(tables,'test',native,{},native_tool_types={'npc_tool_type':target})
        rows = {name:{} for name in adapter.FIELDS};rows['npc_tool']={'npc_tool_type_id':'25'}
        # Exercise the shared enum conversion without unrelated world-item fields.
        _,files,_ = ItemAdapter.convert(adapter,identity,ImportPlan([],dict(category='npc_tool',rows=rows)),{})
        self.assertEqual(E.fromstring(next(iter(files.values()))).find('ItemClasses/NPCTool').get('Type'),'25')
        self.assertNotIn(identity,native_item_registry(native))

    def test_tool_definition_gets_native_manipulation_not_source_number(self):
        source = [dict(id='9', tag='broom', allow_run='False', allow_sprint='False', sharpening_anim='')]
        target = [dict(Id='42', Tag='broom', AllowRun='false', AllowSprint='false')]
        adapter = ItemAdapter(Tables({'item/item_manipulation_type': source}), 'test',
                              {'item_manipulation_type': target})
        rows = {name: {} for name in adapter.FIELDS}
        rows['npc_tool'] = {'manipulation_type': '9'}
        _, files, evidence = adapter.convert('12345678-1234-1234-1234-123456789abc',
            ImportPlan([], dict(category='npc_tool', rows=rows)), {})
        node = E.fromstring(next(iter(files.values()))).find('ItemClasses/NPCTool')
        self.assertEqual(node.get('ManipulationType'), '42')
        self.assertTrue(evidence['item_type_mappings'][0]['movement_policy_preserved'])
        for bad in ([], target + target, [dict(target[0], AllowSprint='true')],
                    [dict(target[0], SharpeningAnim='unexpected')]):
            with self.assertRaises(ValueError): manipulation(source, bad, '9')

    def test_duplicate_source_names_use_retained_items_without_collapsing_types(self):
        source = [dict(npc_tool_type_id=n, npc_tool_type_name='meal_tray') for n in ('10', '25')]
        target = [dict(npc_tool_type_id='10', npc_tool_type_name='chicken_tray'),
                  dict(npc_tool_type_id='25', npc_tool_type_name='meal_tray')]
        with self.assertRaisesRegex(ValueError, 'Ambiguous source'):
            resolve(source, target, 'npc_tool_type', '10')
        mapped, evidence = resolve(source, target, 'npc_tool_type', '10', [dict(item_id='retained', target_id='10')])
        self.assertEqual(mapped, '10')
        self.assertEqual(evidence['target_name'], 'chicken_tray')
        with self.assertRaisesRegex(ValueError, 'Conflicting'):
            resolve(source, target, 'npc_tool_type', '10', [dict(item_id='a', target_id='10'), dict(item_id='b', target_id='25')])

    def test_numeric_collision_is_resolved_by_source_identity(self):
        source = [dict(npc_tool_type_id='10', npc_tool_type_name='meal_tray')]
        target = [dict(npc_tool_type_id='10', npc_tool_type_name='chicken_tray'),
                  dict(npc_tool_type_id='25', npc_tool_type_name='meal_tray')]
        tables = Tables({'item/npc_tool_type': source})
        adapter = ItemAdapter(tables, 'test', {'npc_tool_type': target})
        rows = {name: {} for name in adapter.FIELDS}
        rows['npc_tool'] = {'npc_tool_type_id': '10'}
        plan = ImportPlan([], dict(category='npc_tool', rows=rows))
        _, files, evidence = adapter.convert('12345678-1234-1234-1234-123456789abc', plan, {})
        self.assertEqual(E.fromstring(next(iter(files.values()))).find('ItemClasses/NPCTool').get('Type'), '25')
        self.assertEqual(rows['npc_tool']['npc_tool_type_id'], '10')
        self.assertEqual(evidence['item_type_mappings'][0]['source_name'], 'meal_tray')
        for candidates in (target[:1], target + [target[1]], target + [dict(npc_tool_type_id='25', npc_tool_type_name='other')]):
            with self.assertRaises(ValueError): resolve(source, candidates, 'npc_tool_type', '10')

    def test_unknown_ordinals_and_missing_target_tables_fail(self):
        with self.assertRaises(ValueError): resolve([], [], 'npc_tool_subtype', '9')
        adapter = ItemAdapter(Tables({}), 'test')
        rows = {name: {} for name in adapter.FIELDS}
        rows['npc_tool'] = {'npc_tool_type_id': '10'}
        with self.assertRaisesRegex(ValueError, 'tables are required'):
            adapter.convert('12345678-1234-1234-1234-123456789abc', ImportPlan([], dict(category='npc_tool', rows=rows)), {})


if __name__ == '__main__': unittest.main()
