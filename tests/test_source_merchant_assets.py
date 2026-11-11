"""Imported shop stock assets stay out of the shared travel archive."""
from pathlib import Path
import sys
import tempfile
import unittest
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'tools'))
from source_merchant_assets import take_assets, merge_assets, write_asset_archives


class ShopAssetTests(unittest.TestCase):
    def test_tables_stay_with_the_shop_and_meshes_and_textures_leave(self):
        files = {'Libs/Tables/item/item__containeritems_a.xml': b'<item/>',
                 'libs/tables/shop/shop__gm_source_shop_54.xml': b'<shop/>',
                 'Libs/UI/Textures/Icons/items/a_icon.dds': b'icon',
                 'objects/gluecampaign/gm_source_shop_54/cuirass.cgf': b'mesh',
                 'objects/characters/gluetravel/worlditems/cuirass/cuirass.skin': b'skin'}
        assets = take_assets(files)
        self.assertEqual(sorted(assets), ['objects/characters/gluetravel/worlditems/cuirass/cuirass.skin',
                                          'objects/gluecampaign/gm_source_shop_54/cuirass.cgf'])
        self.assertEqual(sorted(files), ['Libs/Tables/item/item__containeritems_a.xml',
                                         'Libs/UI/Textures/Icons/items/a_icon.dds',
                                         'libs/tables/shop/shop__gm_source_shop_54.xml'])

    def test_stock_and_storage_may_share_an_identical_asset_only(self):
        assets = merge_assets({'objects/a.cgf': b'one'}, {'objects/a.cgf': b'one', 'objects/b.cgf': b'two'})
        self.assertEqual(assets, {'objects/a.cgf': b'one', 'objects/b.cgf': b'two'})
        with self.assertRaisesRegex(ValueError, 'asset collision: objects/a.cgf'):
            merge_assets(assets, {'objects/a.cgf': b'different'})

    def test_no_assets_writes_no_archive(self):
        with tempfile.TemporaryDirectory() as temp:
            self.assertEqual(write_asset_archives(Path(temp)/'Data', 'gm_source_shop_62_assets', {}), [])
            self.assertFalse((Path(temp)/'Data').exists())

    def test_assets_are_stored_in_sorted_zip32_shards_below_the_limit(self):
        assets = {'objects/%s.cgf' % letter: letter.encode()*300 for letter in 'dacb'}
        with tempfile.TemporaryDirectory() as temp:
            data = Path(temp)/'Data'
            names = write_asset_archives(data, 'gm_source_shop_54_assets', assets, limit=1000)
            self.assertEqual(names, ['gm_source_shop_54_assets.pak', 'gm_source_shop_54_assets_01.pak'])
            packed = []
            for name in names:
                self.assertLess((data/name).stat().st_size, 1000)
                with zipfile.ZipFile(data/name) as archive:
                    for entry in archive.infolist():
                        self.assertEqual(entry.compress_type, zipfile.ZIP_STORED)
                        self.assertEqual(entry.date_time, (2026, 1, 1, 0, 0, 0))
                        packed.append((entry.filename, archive.read(entry)))
            self.assertEqual(packed, sorted(assets.items()))
            # A second run is byte-identical, so an unchanged shop keeps its receipt hashes.
            again = Path(temp)/'again'
            write_asset_archives(again, 'gm_source_shop_54_assets', dict(reversed(list(assets.items()))), limit=1000)
            self.assertEqual([(again/n).read_bytes() for n in names], [(data/n).read_bytes() for n in names])
            with self.assertRaises(FileExistsError):
                write_asset_archives(data, 'gm_source_shop_54_assets', assets, limit=1000)

    def test_one_asset_larger_than_a_shard_is_refused(self):
        with tempfile.TemporaryDirectory() as temp:
            with self.assertRaisesRegex(ValueError, 'exceeds the archive shard limit: objects/huge.dds'):
                write_asset_archives(Path(temp), 'shop_assets', {'objects/huge.dds': b'x'*2000}, limit=1000)


if __name__ == '__main__':
    unittest.main()
