import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
import zipfile
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from setup_merchant_upgrade import upgrade, check_identity, MERCHANTS, SOURCE_SHOP
from setup_gameplay import QUEST_PATH


class MerchantSetupTests(unittest.TestCase):
    def package(self, root, installed=(), incomplete=False):
        """installed: the (keeper, namespace) pairs an earlier build already published."""
        package=root/'package';(package/'Data').mkdir(parents=True)
        with zipfile.ZipFile(package/'Data/gluemappertravel.pak','w') as z:
            z.writestr(QUEST_PATH,b'<quest/>')
            for person,namespace in installed:
                z.writestr('Libs/GlueMapper/'+namespace+'.json',json.dumps(dict(person=person)))
                if not incomplete:
                    for n in ('Quests/GlueTravel/entry/'+namespace+'_trade.xml',
                        'Libs/Tables/shop/shop__'+namespace+'.xml',
                        'Libs/Tables/item/InventoryPreset__'+namespace+'_stock.xml'):z.writestr(n,b'<data/>')
        return package

    def test_verified_test_package_is_adopted_without_rebuilding(self):
        with tempfile.TemporaryDirectory() as temp:
            package=self.package(Path(temp),MERCHANTS)
            with patch('build_quest_people_test.build') as actors,patch('source_merchant_upgrade.build') as service:
                changed,reports=upgrade(package,None,None)
            self.assertEqual(changed,{})
            self.assertEqual({n:r['person'] for n,r in reports.items()},{n:p for p,n in MERCHANTS})
            actors.assert_not_called();service.assert_not_called()

    def test_incomplete_marker_does_not_skip_missing_dependencies(self):
        with tempfile.TemporaryDirectory() as temp:
            with self.assertRaisesRegex(ValueError,'Incomplete'):
                upgrade(self.package(Path(temp),MERCHANTS[:1],True),None,None)

    def service(self, calls=None, shop_id=None):
        """A service builder double that reports the identity the generic builder derives."""
        def build(source,target,baseline,stage,person,namespace,entry,level,**options):
            if calls is not None: calls.append((person,namespace,baseline,stage,options))
            identity=shop_id if shop_id is not None else (
                20000+int(namespace[len(SOURCE_SHOP):]) if namespace.startswith(SOURCE_SHOP) else 20017)
            return dict(person=person,stock=dict(shop_name=namespace+'_shop',shop_id=identity))
        return build

    def test_fresh_and_old_packages_call_same_generic_builders_and_consume_stage(self):
        with tempfile.TemporaryDirectory() as temp:
            package=self.package(Path(temp))
            calls=[];stages=[]
            def actors(a):
                # Every pending keeper is staged once, in scope order.
                self.assertEqual(a.person,[person for person,_ in MERCHANTS])
                self.assertTrue(a.output.is_relative_to(package.parent))
                a.output.mkdir(parents=True);stages.append(a.output)
                (a.output/'report.json').write_text(json.dumps(dict(pending=[],converted=[dict(person=n) for n in a.person])))
            with patch('build_quest_people_test.build',side_effect=actors) as staged,patch('source_merchant_upgrade.build',side_effect=self.service(calls)),patch('build_recipe.apply_overlay',return_value={'Data/new.pak':'hash'}) as apply:
                changed,reports=upgrade(package,Path('source'),Path('target'))
                self.assertEqual(changed,{'Data/new.pak':'hash'})
                staged.assert_called_once();apply.assert_called_once()
                self.assertTrue(apply.call_args.kwargs['consume'])
            self.assertEqual([(person,namespace) for person,namespace,*_ in calls],list(MERCHANTS))
            self.assertEqual(set(reports),{namespace for _,namespace in MERCHANTS})
            for person,namespace,baseline,stage,options in calls:
                self.assertEqual(baseline,package)
                self.assertEqual(stage,stages[0]/'package')
                # Weekday restock masks and item assets follow the source shop, not a per-keeper setting.
                self.assertEqual(options,dict(restock_policy='source',asset_archive=namespace+'_assets'))
            self.assertFalse(stages[0].parent.exists())

    def test_installed_keepers_are_adopted_and_only_the_new_ones_are_staged(self):
        with tempfile.TemporaryDirectory() as temp:
            package=self.package(Path(temp),MERCHANTS[:1])
            calls=[]
            def actors(a):
                self.assertNotIn('ska_collierVarlet',a.person)
                a.output.mkdir(parents=True)
                (a.output/'report.json').write_text(json.dumps(dict(pending=[],converted=[dict(person=n) for n in a.person])))
            with patch('build_quest_people_test.build',side_effect=actors),patch('source_merchant_upgrade.build',side_effect=self.service(calls)),patch('build_recipe.apply_overlay',return_value={}):
                _,reports=upgrade(package,Path('source'),Path('target'))
            self.assertEqual(reports['gm_charcoal']['person'],'ska_collierVarlet')
            self.assertEqual([person for person,*_ in calls],[person for person,_ in MERCHANTS if person!='ska_collierVarlet'])

    def test_new_keepers_need_both_games(self):
        with tempfile.TemporaryDirectory() as temp:
            with self.assertRaisesRegex(ValueError,'Source games required'):
                upgrade(self.package(Path(temp),MERCHANTS[:1]),None,None)

    def test_one_unconverted_keeper_publishes_nothing(self):
        with tempfile.TemporaryDirectory() as temp:
            package=self.package(Path(temp))
            def actors(a):
                a.output.mkdir(parents=True)
                (a.output/'report.json').write_text(json.dumps(dict(pending=[],converted=[dict(person=n) for n in a.person[1:]])))
            with patch('build_quest_people_test.build',side_effect=actors),patch('source_merchant_upgrade.build') as service,patch('build_recipe.apply_overlay') as apply:
                with self.assertRaisesRegex(ValueError,'actor conversion is incomplete'):
                    upgrade(package,Path('source'),Path('target'))
            service.assert_not_called();apply.assert_not_called()

    def test_keeper_of_another_shop_publishes_nothing(self):
        with tempfile.TemporaryDirectory() as temp:
            package=self.package(Path(temp),MERCHANTS[:1])
            def actors(a):
                a.output.mkdir(parents=True)
                (a.output/'report.json').write_text(json.dumps(dict(pending=[],converted=[dict(person=n) for n in a.person])))
            with patch('build_quest_people_test.build',side_effect=actors),patch('source_merchant_upgrade.build',side_effect=self.service(shop_id=20001)),patch('build_recipe.apply_overlay') as apply:
                with self.assertRaisesRegex(ValueError,'keeps a different shop'):
                    upgrade(package,Path('source'),Path('target'))
            apply.assert_not_called()

    def test_scope_names_each_keeper_and_shop_once_with_the_derived_identity(self):
        people=[person for person,_ in MERCHANTS];spaces=[namespace for _,namespace in MERCHANTS]
        self.assertEqual(len(set(people)),len(people))
        self.assertEqual(len(set(spaces)),len(spaces))
        self.assertEqual(MERCHANTS[0],('ska_collierVarlet','gm_charcoal'))
        for person,namespace in MERCHANTS[1:]:
            # The profile builder's namespace for the same source shop.
            self.assertRegex(namespace,r'^gm_source_shop_[1-9][0-9]*$')
            check_identity(person,namespace,dict(stock=dict(shop_name=namespace+'_shop',
                shop_id=20000+int(namespace[len(SOURCE_SHOP):]))))
            with self.assertRaisesRegex(ValueError,'shop name changed'):
                check_identity(person,namespace,dict(stock=dict(shop_name='other_shop',shop_id=1)))

if __name__=='__main__':unittest.main()
