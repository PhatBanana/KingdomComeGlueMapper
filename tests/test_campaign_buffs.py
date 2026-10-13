import copy
from pathlib import Path
import sys
import unittest
import xml.etree.ElementTree as E

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from campaign_buffs import BuffAdapter, ENUMS
from campaign_dependencies import DependencyImporter
from campaign_behavior import convert_behaviors
from test_campaign_behavior import source, catalog


ID = '11111111-2222-4333-8444-555555555555'
ROW = dict(buff_id=ID, buff_name='arbitrary_protection', buff_class_id='0',
           implementation='Cpp:Constant', params='apr+1', duration='-1', is_persistent='False')


class Tables:
    def __init__(self, row): self.buff = row
    def row(self, table, field, identity):
        return self.buff if table == 'rpg/buff' else {field: identity, table.split('/')[-1] + '_name': 'example'}
    def get(self, table): return dict(provenance=[dict(entry=table)])


def adapter(native_params='apr+1', row=None):
    native = dict(ROW)
    del native['params']
    native['buff_params'] = native_params
    native['is_persistent'] = 'false'
    contract = dict(records=[native], enums={n: [{n + '_id': '0', n + '_name': 'example'}] for n in ENUMS})
    return BuffAdapter(Tables(dict(row or ROW)), contract, 'test_import')


class BuffTests(unittest.TestCase):
    def test_equal_effects_merge_without_duplicate_registration(self):
        imp = DependencyImporter(dict(buffs=adapter()))
        self.assertEqual(imp.ensure('buffs', ID), ID)
        self.assertFalse(imp.files)
        self.assertEqual(imp.jobs['buffs', ID]['evidence']['mode'], 'merge_native')

    def test_same_id_different_effect_converts_without_overwriting_native(self):
        a = adapter('apr+1,kopr+1')
        original = copy.deepcopy(a.contract)
        imp = DependencyImporter(dict(buffs=a))
        converted = imp.ensure('buffs', ID)
        self.assertNotEqual(converted, ID)
        self.assertEqual(converted, imp.ensure('buffs', ID))
        buff = E.fromstring(next(iter(imp.files.values()))).find('./buffs/buff')
        self.assertEqual(buff.get('buff_params'), 'apr+1')
        self.assertEqual(buff.get('duration'), '-1')
        self.assertEqual(buff.get('is_persistent'), 'false')
        self.assertEqual(a.contract, original)

    def test_unknown_formula_and_enum_fail_explicitly(self):
        for change in [dict(params='unknown+9'), dict(buff_class_id='999')]:
            imp = DependencyImporter(dict(buffs=adapter(row=dict(ROW, **change))))
            self.assertIsNone(imp.ensure('buffs', ID))
            self.assertFalse(imp.files)

    def test_changed_duration_and_persistence_are_not_merged(self):
        for change in [dict(duration='10'), dict(is_persistent='True')]:
            imp = DependencyImporter(dict(buffs=adapter(row=dict(ROW, **change))))
            self.assertNotEqual(imp.ensure('buffs', ID), ID)

    def test_missing_text_dependency_blocks_registration(self):
        imp = DependencyImporter(dict(buffs=adapter('apr+1,kopr+1', dict(ROW, buff_ui_name='missing_text'))))
        # Expose the native field schema without adding a localization importer.
        imp.adapters['buffs'].contract['records'][0]['buff_ui_name'] = 'native_text'
        self.assertIsNone(imp.ensure('buffs', ID))
        self.assertFalse(imp.files)

    def test_add_remove_keep_guard_target_and_shared_conversion(self):
        m = source('''<Root><IfCondition condition="&quot;!$hasStarted&quot;"><Sequence>
          <AddBuff SoulWUID="&quot;someActor&quot;" BuffGUID="&quot;ID&quot;"/>
          <RemoveBuffs SoulWUID="&quot;someActor&quot;" BuffGUID="&quot;ID&quot;"/>
          </Sequence></IfCondition></Root>'''.replace('ID&quot;', ID + '&quot;'))
        imp = DependencyImporter(dict(buffs=adapter('apr+1,kopr+1')))
        files, _, report = convert_behaviors([m], 'Imported', catalog(), importer=imp)
        tree = E.fromstring(next(iter(files.values())))
        seq = tree.find('.//IfCondition/Sequence')
        self.assertEqual([n.tag for n in seq], ['AddBuff', 'RemoveBuffs'])
        self.assertEqual(seq[0].get('SoulWUID'), '$someActor')
        self.assertEqual(seq[0].get('BuffGUID'), seq[1].get('BuffGUID'))
        self.assertNotEqual(seq[0].get('BuffGUID'), "'" + ID + "'")
        self.assertEqual(report['whole_trees_emitted'], 1)

    def test_missing_buff_withholds_whole_tree(self):
        m = source('<Root><Sequence><Success/><AddBuff SoulWUID="&quot;actor&quot;" BuffGUID="&quot;x&quot;"/></Sequence></Root>')
        files, _, report = convert_behaviors([m], 'Imported', catalog())
        self.assertFalse(files)
        self.assertEqual(report['blocked_trees'], 1)


if __name__ == '__main__': unittest.main()
