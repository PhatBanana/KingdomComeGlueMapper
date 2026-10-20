import copy
from pathlib import Path
import sys
import unittest
import xml.etree.ElementTree as E

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from campaign_behavior import BehaviorCompiler
from campaign_training_equipment import lower
from campaign_quest_bridge import UnsupportedOperation
from test_campaign_behavior import catalog
from test_campaign_training_plan import equipment, ITEM


class TrainingEquipmentTests(unittest.TestCase):
    def compiler(self, registered=True):
        return BehaviorCompiler([], 'Imported', catalog(),
                                registered={'items': {ITEM: ITEM}} if registered else {})

    def lower(self, compiler=None, pair=None, variables=None):
        return lower(compiler or self.compiler(), 'q_arbitrary', 'libs/ai/quests/q_arbitrary.xml',
                     *(pair or equipment()), variables if variables is not None else
                     [dict(name='loan', type='_wuid', form='single', values='', isPersistent='0')])

    def test_instance_handle_survives_between_callbacks_and_no_inventory_type_removal(self):
        pair = equipment(); original = copy.deepcopy(pair)
        roots, variables, report = self.lower(pair=pair)
        self.assertEqual(pair, original)
        self.assertEqual(variables[0].get('isPersistent'), '1')
        create = E.fromstring(roots['prepare']).find('.//CreateItem')
        remove = E.fromstring(roots['cleanup']).find('.//RemoveItem')
        self.assertEqual(create.get('CreatedItem'), remove.get('Item'))
        self.assertEqual(remove.get('ItemGUID'), '')
        self.assertEqual(remove.get('FailOnDoesntExist'), 'false')
        self.assertTrue(report['requires_shared_controller_scope'])
        self.assertFalse(report['publication_ready'])
        for blob in roots.values():
            root = E.fromstring(blob)
            self.assertEqual(root.find('./Behavior/FuseBox/OnSuccess/Callback_empty').get('EventName'), "'Success'")
            self.assertEqual(root.find('./Behavior/FuseBox/OnFail/Callback_empty').get('EventName'), "'Fail'")

    def test_missing_item_blocks_both_roots_and_restores_compiler_scope(self):
        compiler = self.compiler(False); old = {'unrelated': {}}
        compiler.variables = old
        with self.assertRaisesRegex(UnsupportedOperation, 'Referenced item conversion'):
            self.lower(compiler=compiler)
        self.assertIs(compiler.variables, old)

    def test_source_common_wuid_type_uses_existing_type_adapter(self):
        _, variables, _ = self.lower(variables=[dict(name='loan', type='common:wuid', form='single')])
        self.assertEqual(variables[0].get('type'), '_wuid')
        self.assertEqual(variables[0].get('isPersistent'), '1')

    def test_missing_or_mistyped_shared_variable_blocks_conversion(self):
        for variables in ([], [dict(name='loan', type='_string', form='single')],
                          [dict(name='loan', type='_wuid', form='array')]):
            with self.assertRaises(UnsupportedOperation): self.lower(variables=variables)

    def test_cleanup_initialization_is_not_discarded(self):
        prepare, cleanup = equipment()
        cleanup['children'].insert(0, dict(op='OnInit', attributes={}, children=[
            dict(op='Sequence', attributes={}, children=[], text='')], text=''))
        roots, _, _ = self.lower(pair=(prepare, cleanup))
        self.assertIsNotNone(E.fromstring(roots['cleanup']).find('./OnInit/Sequence'))

    def test_unsupported_cleanup_prevents_partial_output(self):
        prepare, cleanup = equipment()
        cleanup['children'].insert(0, dict(op='OnInit', attributes={}, children=[
            dict(op='UnknownRestoration', attributes={}, children=[], text='')], text=''))
        with self.assertRaisesRegex(UnsupportedOperation, 'cleanup conversion failed'):
            self.lower(pair=(prepare, cleanup))


if __name__ == '__main__': unittest.main()
