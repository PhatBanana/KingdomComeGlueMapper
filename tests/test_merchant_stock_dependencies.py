"""Merchant stock must resolve before clean-build or upgrade presets are made."""
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
import xml.etree.ElementTree as E
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'tools'))
from region_travel_services import import_shop_resources


NATIVE = '00000000-0000-0000-0000-000000000001'
SOURCE = '00000000-0000-0000-0000-000000000002'
REPLACEMENT = '00000000-0000-0000-0000-000000000003'
ITEM_FILE = 'Libs/Tables/item/item__containeritems_test.xml'


def item(identity, name, **fields):
    root = E.Element('database')
    E.SubElement(E.SubElement(root, 'ItemClasses', version='8'), 'Food',
                 Id=identity, Name=name, **fields)
    return E.tostring(root)


class MerchantStockDependenciesTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.target = self.root/'target'
        self.package = self.root/'package'
        (self.target/'Data').mkdir(parents=True)
        (self.package/'Data').mkdir(parents=True)
        self.native_item = item(NATIVE, 'native_food', Price='7')
        with zipfile.ZipFile(self.target/'Data/Tables.pak', 'w') as z:
            z.writestr('Libs/Tables/item/item.xml', self.native_item)
            z.writestr('Libs/Tables/shop/shop.xml', '<database><Shops/></database>')
        self.merchant = dict(stock={NATIVE: 3, SOURCE: 11}, shop=dict(
            shop_id='7', restock_day_mask='127', price_buy_multiplier='1.2', price_sell_multiplier='0.4'))
        self.converted = item(SOURCE, 'converted_food', Price='9',
                              Model='gluecampaign/test/food.cgf', UIName='containeritems_food_name')
        self.strings = b'<Table><Row><Cell>containeritems_food_name</Cell><Cell>Food</Cell><Cell>Food</Cell></Row></Table>'

    def run_import(self, converter, **kwargs):
        with patch('container_items.build', side_effect=converter) as build:
            result = import_shop_resources(self.merchant, self.root/'source', self.target,
                'arbitrary_merchant', self.package, self.root/'dependencies', **kwargs)
        self.assertEqual(set(build.call_args.args[4]), set(self.merchant['stock']))
        return result

    def emit(self, *args, **kwargs):
        generated = {ITEM_FILE: self.converted,
            'objects/gluecampaign/test/food.cgf': b'converted mesh',
            'objects/gluecampaign/test/food.mtl': b'<Material/>',
            'localization/English/text_food.xml': self.strings}
        for name, blob in generated.items():
            path = Path(args[3])/'converted'/name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(blob)
        return dict(unresolved_items=[], registered_items={NATIVE:NATIVE, SOURCE:SOURCE})

    def preset(self, files):
        return E.fromstring(files['Libs/Tables/item/InventoryPreset__arbitrary_merchant_stock.xml'])

    def test_clean_stock_keeps_every_item_and_packages_dependencies(self):
        files, strings, report = self.run_import(self.emit)
        rows = {n.get('ItemClassId'): n for n in self.preset(files).iter('PresetItem')}
        self.assertEqual({k:int(v.get('Amount')) for k,v in rows.items()}, self.merchant['stock'])
        self.assertEqual(rows[SOURCE].get('Name'), 'converted_food')
        self.assertEqual(rows[NATIVE].get('Name'), 'native_food')
        self.assertEqual(files[ITEM_FILE], self.converted)
        self.assertEqual(files['objects/gluecampaign/test/food.cgf'], b'converted mesh')
        self.assertIn('objects/gluecampaign/test/food.mtl', files)
        self.assertFalse(any(n.lower().startswith('localization/') for n in files))
        self.assertEqual(strings, [self.strings])
        self.assertEqual(report['stock_types'], 2)
        self.assertEqual(report['native_items'][NATIVE]['Price'], '7')
        self.assertEqual(report['native_items'][SOURCE]['Price'], '9')

    def test_non_daily_stock_requires_explicit_native_policy(self):
        self.merchant['shop']['restock_day_mask']='85'
        with self.assertRaisesRegex(ValueError,'explicit target policy'):
            self.run_import(self.emit)

    def test_explicit_native_restock_uses_installed_merchant_period(self):
        self.merchant['shop']['restock_day_mask']='9'
        # A changed native period must be read from the target, not embedded in
        # a settlement-specific adapter or rounded from a source weekday mask.
        with zipfile.ZipFile(self.target/'Data/Tables.pak','w') as z:
            z.writestr('Libs/Tables/item/item.xml',self.native_item)
            z.writestr('Libs/Tables/shop/shop.xml','<database><Shops><ShopData shop_id="3" shop_name="common_merchant" restock_period="6"/></Shops></database>')
        files,_,report=self.run_import(self.emit,restock_policy='native_merchant')
        row=E.fromstring(files['Libs/Tables/shop/shop__arbitrary_merchant.xml']).find('.//ShopData')
        self.assertEqual(row.get('restock_period'),'6')
        self.assertEqual(report['restock']['source_day_mask'],9)
        self.assertFalse(report['restock']['preserves_source_weekdays'])

    def test_existing_package_and_staged_item_rows_are_reused(self):
        with zipfile.ZipFile(self.package/'Data/previous.pak', 'w') as z:
            z.writestr(ITEM_FILE, self.converted)
        staged = item(SOURCE, 'staged_food', Price='12')

        def reuse(*args, **kwargs):
            from container_items import item_patches
            from world_item_definitions import native_items, native_item_registry
            rows = native_items(args[1], item_patches(args[2]) + kwargs['extra_item_patches'])
            self.assertEqual(native_item_registry(rows)[SOURCE], SOURCE)
            self.assertEqual(rows[SOURCE].get('Name'), 'staged_food')
            return dict(unresolved_items=[], registered_items={NATIVE:NATIVE, SOURCE:SOURCE})

        files, strings, report = self.run_import(reuse, extra_item_patches=[staged])
        self.assertNotIn(ITEM_FILE, files)
        self.assertEqual(strings, [])
        self.assertEqual(report['native_items'][SOURCE]['Name'], 'staged_food')
        self.assertEqual(len(list(self.preset(files).iter('PresetItem'))), 2)

    def test_failed_dependency_is_not_silently_removed_from_stock(self):
        with self.assertRaisesRegex(ValueError, 'Unresolved source merchant stock'):
            self.run_import(lambda *a, **k: dict(unresolved_items=[SOURCE]))
        self.assertEqual(self.merchant['stock'], {NATIVE:3, SOURCE:11})

    def test_missing_emitted_definition_still_fails_validation(self):
        with self.assertRaisesRegex(ValueError, 'Stock items need native item conversion'):
            self.run_import(lambda *a, **k: dict(unresolved_items=[]))

    def test_retired_native_placeholder_uses_converted_target_identity(self):
        with zipfile.ZipFile(self.target/'Data/Tables.pak', 'a') as z:
            z.writestr('Libs/Tables/item/item__retired.xml', item(SOURCE, 'retired',
                       Model='preproduction/traffic_cone/cone'))
        self.converted = item(REPLACEMENT, 'containeritems_item_'+SOURCE.replace('-', '_'),
                              Model='gluecampaign/test/food.cgf')
        files, _, report = self.run_import(self.emit)
        rows = {n.get('ItemClassId'):n for n in self.preset(files).iter('PresetItem')}
        self.assertNotIn(SOURCE, rows)
        self.assertEqual(rows[REPLACEMENT].get('Amount'), '11')
        self.assertEqual(report['native_items'][SOURCE]['Id'], REPLACEMENT)


if __name__ == '__main__':
    unittest.main()
