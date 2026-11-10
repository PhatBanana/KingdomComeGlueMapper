"""The source stable sells its own source stock, not a native merchant's."""
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
import xml.etree.ElementTree as E
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'tools'))
from build_horse_trader_test import merge_item_strings, stage_stock
from horse_trader import SHOP_ID, SHOP_NAME, STOCK_NAMESPACE, stock_resources
from horse_trader_world import stash_properties
from region_travel_services import resolve_stock
from region_travel_tables import managed_patches
from world_item_clothing import accessory_without_native_mesh


MONEY = '00000000-0000-0000-0000-00000000000a'
IMPORTED = '00000000-0000-0000-0000-00000000000b'
SADDLE = '00000000-0000-0000-0000-00000000000c'
SPURS = '00000000-0000-0000-0000-00000000000d'
SADDLE_TABLE = 'Libs/Tables/item/item__containeritems_saddle.xml'
SPURS_TABLE = 'Libs/Tables/item/item__containeritems_spurs.xml'
COMPONENT_TABLE = 'Libs/Tables/Character/CharacterComponent__worlditems_cloth_spurs.xml'
PRESET_TABLE = 'Libs/Tables/item/InventoryPreset__gm_neuhof_horse_stock.xml'
SHOP_TABLE = 'Libs/Tables/shop/shop__gm_neuhof_horse.xml'
NATIVE_SHOPS = '''<database><Shops>
<ShopData shop_id="519" shop_name="shop_tsem_horseTrader" restock_period="7" inventory_preset="inventory_shop_horseTraderSemin">
<ShopItemFilter filter="armor.Saddle.*" price_buy_multiplier="0.7" price_sell_multiplier="0.5"/>
<ShopItemFilter filter="misc.skin.*" price_buy_multiplier="0.75" price_sell_multiplier="0.6"/>
</ShopData></Shops></database>'''


def items(*rows):
    root = E.Element('database', name='barbora')
    table = E.SubElement(root, 'ItemClasses', version='8')
    for tag, fields in rows:
        E.SubElement(table, tag, **fields)
    return E.tostring(root)


def armor(identity, name, **fields):
    return ('Armor', dict(dict(Id=identity, Name=name, Weight='1', DefenseStab='0', DefenseSlash='0',
        DefenseSmash='0', StrReq='0', Noise='0', Visibility='0', Conspicuousness='0', Charisma='0',
        SocialClassId='0', WealthLevel='0', IconId='icon'), **fields))


def source_shop(**fields):
    return dict(dict(shop_id='130', shop_name='neu_stables', shop_type_id='63', item_category_id='25',
        amount_multiplier='1', amount_multiplier_random_add='0', restock_day_mask='127',
        price_buy_multiplier='1', price_sell_multiplier='0.8'), **fields)


class SourceStockSelectionTests(unittest.TestCase):
    ROWS = [dict(shop_type_id='63', item_id=SADDLE, amount='1', default_on='True'),
            dict(shop_type_id='63', item_id=SPURS, amount='3', default_on='False'),
            dict(shop_type_id='63', item_id=MONEY, amount='4000', default_on='True'),
            dict(shop_type_id='62', item_id='another stable type', amount='9', default_on='True')]

    def test_stable_stock_is_every_row_of_its_source_shop_type(self):
        # default_on is not a stock predicate, and another type's rows are not this shop's.
        self.assertEqual(resolve_stock(source_shop(), self.ROWS, []), {SADDLE: 1, SPURS: 3, MONEY: 4000})

    def test_only_this_shops_overrides_scale_its_quantities(self):
        overrides = [dict(shop_id='130', item_id=SPURS, amount_multiplier='2'),
                     dict(shop_id='131', item_id=SADDLE, amount_multiplier='0')]
        self.assertEqual(resolve_stock(source_shop(), self.ROWS, overrides), {SADDLE: 1, SPURS: 6, MONEY: 4000})

    def test_unsupported_quantity_policy_is_not_rounded(self):
        with self.assertRaisesRegex(ValueError, 'Random shop quantity'):
            resolve_stock(source_shop(amount_multiplier_random_add='0.5'), self.ROWS, [])
        with self.assertRaisesRegex(ValueError, 'rounding policy'):
            resolve_stock(source_shop(amount_multiplier='0.5'), self.ROWS, [])


class StableStockResourcesTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.target, self.package = self.root/'target', self.root/'package'
        (self.target/'Data').mkdir(parents=True)
        (self.package/'Data').mkdir(parents=True)
        with zipfile.ZipFile(self.target/'Data/Tables.pak', 'w') as z:
            z.writestr('Libs/Tables/item/item.xml', items(('MiscItem', dict(Id=MONEY, Name='money'))))
            z.writestr('Libs/Tables/shop/shop.xml', NATIVE_SHOPS)
        # One stock item was already imported by an earlier stage of the same package.
        with zipfile.ZipFile(self.package/'Data/containers.pak', 'w') as z:
            z.writestr('Libs/Tables/item/item__containeritems_old.xml', items(armor(IMPORTED, 'containeritems_item_bridle')))
        self.person = dict(name='neu_zdena', shop=source_shop(),
                           stock={MONEY: 4000, IMPORTED: 1, SADDLE: 1, SPURS: 3})
        self.converted = {
            SADDLE_TABLE: items(armor(SADDLE, 'containeritems_item_saddle', Clothing='worlditems_cloth_saddle')),
            SPURS_TABLE: items(armor(SPURS, 'containeritems_item_spurs', Clothing='worlditems_cloth_spurs')),
            COMPONENT_TABLE: b'<database name="barbora"><CharacterComponents version="6"><Component '
                b'Name="worlditems_cloth_spurs_root"/></CharacterComponents></database>',
            'objects/characters/gluetravel/worlditems/saddle/horse_back.skin': b'saddle mesh',
            'objects/gluecampaign/gm_neuhof_horse/saddle.cgf': b'saddle pickup',
            'localization/English/text_saddle.xml': b'<Table><Row><Cell>containeritems_ui_nm_saddle</Cell>'
                b'<Cell>Saddle</Cell><Cell>Saddle</Cell></Row></Table>'}
        self.jobs = [
            dict(group='items', identity=SPURS, evidence=dict(target_id=SPURS)),
            dict(group='clothing', identity=SADDLE, evidence=dict(role='Saddle', omitted_source_mesh=None)),
            dict(group='clothing', identity=SPURS, evidence=dict(role='Spurs', omitted_source_mesh='spur_mesh')),
            dict(group='clothing', identity='failed', error='no evidence was recorded')]

    def converter(self, *args, **kwargs):
        self.requested = (set(args[4]), kwargs)
        for name, blob in self.converted.items():
            path = Path(args[3])/'converted'/name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(blob)
        return dict(unresolved_items=[], registered_items={i: i for i in self.person['stock']}, jobs=self.jobs)

    def run_stock(self, converter=None):
        with patch('container_items.build', side_effect=converter or self.converter):
            return stock_resources(self.person, self.root/'source', self.target, self.package, self.root/'stock')

    def test_every_source_stock_item_is_requested_and_sold(self):
        tables, _, _, report = self.run_stock()
        self.assertEqual(self.requested[0], set(self.person['stock']))
        self.assertEqual(self.requested[1]['asset_namespace'], STOCK_NAMESPACE)
        preset = E.fromstring(tables[PRESET_TABLE]).find('InventoryPresets/InventoryPreset')
        self.assertEqual(preset.get('Name'), SHOP_NAME+'_stock')
        self.assertEqual({(r.get('ItemClassId'), r.get('Name'), r.get('Amount')) for r in preset}, {
            (MONEY, 'money', '4000'), (IMPORTED, 'containeritems_item_bridle', '1'),
            (SADDLE, 'containeritems_item_saddle', '1'), (SPURS, 'containeritems_item_spurs', '3')})
        self.assertEqual(report['stock'], self.person['stock'])
        self.assertEqual(report['stock_types'], 4)

    def test_shop_row_keeps_its_identity_and_uses_source_terms(self):
        tables, _, _, report = self.run_stock()
        rows = E.fromstring(tables[SHOP_TABLE]).findall('Shops/ShopData')
        self.assertEqual(len(rows), 1)
        self.assertEqual(dict(rows[0].attrib), dict(shop_id=SHOP_ID, shop_name=SHOP_NAME, restock_period='1',
                                                   inventory_preset=SHOP_NAME+'_stock'))
        self.assertEqual((SHOP_ID, SHOP_NAME), ('20130', 'gm_neuhof_horse_shop'))
        # The source stable trades every player item at its own two multipliers.
        self.assertEqual([dict(f.attrib) for f in rows[0]], [dict(filter='player_item.*.*',
            price_buy_multiplier='1', price_sell_multiplier='0.8')])
        self.assertEqual(report['source_shop']['shop_name'], 'neu_stables')
        self.assertTrue(report['restock']['preserves_source_weekdays'])

    def test_no_native_merchant_stock_or_buy_list_is_inherited(self):
        tables, assets, _, _ = self.run_stock()
        for blob in list(tables.values()) + list(assets.values()):
            self.assertNotIn(b'horseTraderSemin', blob)
            self.assertNotIn(b'armor.Saddle', blob)
            self.assertNotIn(b'misc.skin', blob)

    def test_tables_assets_and_strings_are_separated_for_packing(self):
        tables, assets, strings, _ = self.run_stock()
        self.assertEqual(set(tables), {SADDLE_TABLE, SPURS_TABLE, COMPONENT_TABLE, PRESET_TABLE, SHOP_TABLE})
        self.assertEqual(set(assets), {'objects/characters/gluetravel/worlditems/saddle/horse_back.skin',
                                       'objects/gluecampaign/gm_neuhof_horse/saddle.cgf'})
        self.assertEqual(strings, [self.converted['localization/English/text_saddle.xml']])

    def test_stock_tables_merge_into_one_mod_patch_per_table(self):
        tables, _, _, _ = self.run_stock()
        merged = managed_patches(tables, 'testmod')
        self.assertEqual({r.get('Id') for r in E.fromstring(merged['Libs/Tables/item/item__testmod.xml'])[0]},
                         {SADDLE, SPURS})
        self.assertEqual(E.fromstring(merged['Libs/Tables/shop/shop__testmod.xml'])[0][0].get('shop_id'), SHOP_ID)
        self.assertEqual(len(E.fromstring(merged['Libs/Tables/item/InventoryPreset__testmod.xml'])[0][0]), 4)

    def test_undrawn_source_meshes_are_reported(self):
        _, _, _, report = self.run_stock()
        self.assertEqual(report['undrawn_source_meshes'], [SPURS])

    def test_another_source_shop_cannot_take_the_stable_identity(self):
        self.person['shop']['shop_id'] = '131'
        with self.assertRaisesRegex(ValueError, 'shop identity changed'):
            self.run_stock()

    def test_unconverted_stock_fails_instead_of_shrinking(self):
        with self.assertRaisesRegex(ValueError, 'Unresolved source merchant stock'):
            self.run_stock(lambda *a, **k: dict(unresolved_items=[SPURS]))
        self.converted.pop(SPURS_TABLE)
        with self.assertRaisesRegex(ValueError, 'Stock items need native item conversion'):
            self.run_stock()

    def test_non_daily_source_restock_is_not_silently_made_daily(self):
        self.person['shop']['restock_day_mask'] = '85'
        with self.assertRaisesRegex(ValueError, 'explicit target policy'):
            self.run_stock()


class StableStorageTests(unittest.TestCase):
    def authored(self, database='<Database guidInventoryDBId="0" iMinimalShopItemPrice="0"/>'):
        return E.fromstring('<Entity Name="stash_neu_shop_stables" EntityClass="Stash"><Properties>'
                            + database + '</Properties></Entity>')

    def test_chest_generates_no_stock_of_its_own(self):
        props = stash_properties(self.authored())
        self.assertEqual(dict(props.find('Database').attrib),
                         dict(sGeneratedInventory='inventory_empty', iMinimalShopItemPrice='0'))
        self.assertEqual(props.find('Lock').get('bLocked'), '1')
        self.assertNotIn(b'horseTraderSemin', E.tostring(props))

    def test_source_minimum_price_is_copied_only_when_authored(self):
        props = stash_properties(self.authored('<Database guidInventoryDBId=""/>'))
        self.assertEqual(dict(props.find('Database').attrib), dict(sGeneratedInventory='inventory_empty'))
        self.assertEqual(stash_properties(self.authored('<Database iMinimalShopItemPrice="25"/>'))
                         .find('Database').get('iMinimalShopItemPrice'), '25')

    def test_independent_chest_contents_are_not_discarded(self):
        with self.assertRaisesRegex(ValueError, 'independent inventory'):
            stash_properties(self.authored('<Database guidInventoryDBId="4d783304-0000-0000-0000-000000000001"/>'))


class StablePackagingTests(unittest.TestCase):
    ROW = b'<Row><Cell>%s</Cell><Cell>%s</Cell><Cell>%s</Cell></Row>'

    def table(self, *rows):
        return b'<Table>' + b''.join(self.ROW % (k, v, v) for k, v in rows) + b'</Table>'

    def keys(self, blob):
        return [r[0].text for r in E.fromstring(blob).findall('Row')]

    def test_item_labels_are_added_once(self):
        texts = {'text_ui_items.xml': self.table((b'containeritems_ui_nm_bridle', b'Bridle')),
                 'text_ui_container_items.xml': self.table((b'containeritems_ui_in_saddle', b'A saddle.')),
                 'text_ui_soul.xml': b'<Table>'}  # unrelated tables are not parsed
        strings = [self.table((b'containeritems_ui_in_saddle', b'A saddle.')),
                   self.table((b'containeritems_ui_nm_bridle', b'Bridle')),
                   self.table((b'containeritems_ui_nm_spur', b'Spurs')),
                   self.table((b'containeritems_ui_nm_spur', b'Spurs'))]
        merged = merge_item_strings(texts, strings)
        self.assertEqual(self.keys(merged), ['containeritems_ui_nm_bridle', 'containeritems_ui_nm_spur'])
        self.assertEqual(merge_item_strings(texts, []), texts['text_ui_items.xml'])

    def test_changed_item_label_is_rejected(self):
        texts = {'text_ui_items.xml': self.table((b'containeritems_ui_nm_bridle', b'Bridle'))}
        with self.assertRaises(ValueError):
            merge_item_strings(texts, [self.table((b'containeritems_ui_nm_bridle', b'Halter'))])

    def test_stock_tables_and_receipt_join_the_stable_resources(self):
        stock = dict(shop_id=20130, shop_name=SHOP_NAME, stock={SPURS: 3})
        staged = stage_stock({'Libs/Storm/storm.xml': b'<storm/>'}, dict(name='neu_zdena'), {SHOP_TABLE: b'<database/>'}, stock)
        self.assertEqual(staged[SHOP_TABLE], b'<database/>')
        self.assertEqual(staged['Libs/Storm/storm.xml'], b'<storm/>')
        receipt = json.loads(staged['Libs/GlueMapper/gm_neuhof_horse.json'])
        self.assertEqual(receipt, dict(version=1, person='neu_zdena', stock=stock, runtime_verified=False))
        with self.assertRaisesRegex(ValueError, 'collision'):
            stage_stock({SHOP_TABLE: b'<other/>'}, dict(name='neu_zdena'), {SHOP_TABLE: b'<database/>'}, stock)


class NativeAccessoryContractTests(unittest.TestCase):
    NATIVE = E.fromstring('''<Component Name="Feet"><DerivedComponents>
        <Clothing Name="Spurs" ArmorType="Spurs" ArmorArchetypeId="81"><DerivedComponents>
            <Clothing Name="Spurs01_m01" DropModel="spurs_dropmodel.cgf"><Features><Feature Name="SpurBase" Material="Iron"/></Features></Clothing>
        </DerivedComponents></Clothing>
        <Clothing Name="Ring" ArmorType="Ring"><Features><Feature Name="RingBase" Material="Gold"/></Features></Clothing>
        <Clothing Name="Necklace" ArmorType="Necklace"><Elements><SkinElement EquipmentPart="neck"/></Elements></Clothing>
        <Clothing Name="Boots"><Elements><SkinElement EquipmentPart="feet" BodyLayerId="2"/></Elements><DerivedComponents>
            <Clothing Name="BootsAnkle" ArmorType="BootsAnkle"/>
            <Clothing Name="Spurs" ArmorType="Spurs" Label="under a mesh family"/>
        </DerivedComponents></Clothing>
        <Clothing Name="LegsChain" ArmorType="LegsChain"/>
    </DerivedComponents></Component>''')
    PARENTS = {child: parent for parent in NATIVE.iter() for child in parent}

    def role(self, name, label=None):
        return next(n for n in self.NATIVE.iter('Clothing') if n.get('Name') == name and n.get('Label') == label)

    def omitted(self, name, role=None, label=None):
        return accessory_without_native_mesh(self.role(name, label), self.PARENTS, role or name)

    def test_role_drawn_only_by_variant_features_takes_no_source_mesh(self):
        # Its variants' features recolour the boots; the role attaches nothing.
        self.assertTrue(self.omitted('Spurs'))

    def test_roles_with_a_native_contract_keep_their_source_mesh(self):
        self.assertFalse(self.omitted('Ring'))       # material-feature contract
        self.assertFalse(self.omitted('Necklace'))   # own attachment
        self.assertFalse(self.omitted('Spurs', label='under a mesh family'))  # inherited attachment

    def test_missing_contract_on_a_garment_is_still_an_error_not_an_omission(self):
        self.assertFalse(self.omitted('LegsChain'))


if __name__ == '__main__':
    unittest.main()
