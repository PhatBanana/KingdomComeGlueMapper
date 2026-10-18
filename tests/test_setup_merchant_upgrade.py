import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
import zipfile
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from setup_merchant_upgrade import upgrade
from setup_gameplay import QUEST_PATH


class MerchantSetupTests(unittest.TestCase):
    def package(self, root, installed=False, incomplete=False):
        package=root/'package';(package/'Data').mkdir(parents=True)
        with zipfile.ZipFile(package/'Data/gluemappertravel.pak','w') as z:
            z.writestr(QUEST_PATH,b'<quest/>')
            if installed:
                z.writestr('Libs/GlueMapper/gm_charcoal.json',json.dumps(dict(person='ska_collierVarlet')))
                if not incomplete:
                    for n in ('Quests/GlueTravel/entry/gm_charcoal_trade.xml',
                        'Libs/Tables/shop/shop__gm_charcoal.xml',
                        'Libs/Tables/item/InventoryPreset__gm_charcoal_stock.xml'):z.writestr(n,b'<data/>')
        return package

    def test_verified_test_package_is_adopted_without_rebuilding(self):
        with tempfile.TemporaryDirectory() as temp:
            package=self.package(Path(temp),True)
            with patch('build_quest_people_test.build') as actors,patch('source_merchant_upgrade.build') as service:
                changed,reports=upgrade(package,None,None)
            self.assertEqual(changed,{})
            self.assertEqual(reports['gm_charcoal']['person'],'ska_collierVarlet')
            actors.assert_not_called();service.assert_not_called()

    def test_incomplete_marker_does_not_skip_missing_dependencies(self):
        with tempfile.TemporaryDirectory() as temp:
            with self.assertRaisesRegex(ValueError,'Incomplete'):
                upgrade(self.package(Path(temp),True,True),None,None)

    def test_fresh_and_old_packages_call_same_generic_builders_and_consume_stage(self):
        with tempfile.TemporaryDirectory() as temp:
            package=self.package(Path(temp))
            def actors(a):
                self.assertEqual(a.person,['ska_collierVarlet'])
                self.assertTrue(a.output.is_relative_to(package.parent))
                a.output.mkdir(parents=True)
                (a.output/'report.json').write_text(json.dumps(dict(pending=[],converted=[dict(person=a.person[0])])))
            with patch('build_quest_people_test.build',side_effect=actors),patch('source_merchant_upgrade.build',return_value={'service':'verified path'}) as build,patch('build_recipe.apply_overlay',return_value={'Data/new.pak':'hash'}) as apply:
                changed,reports=upgrade(package,Path('source'),Path('target'))
                self.assertEqual(changed,{'Data/new.pak':'hash'})
                self.assertEqual(reports['gm_charcoal'],{'service':'verified path'})
                self.assertEqual(build.call_args.args[2],package)
                self.assertTrue(apply.call_args.kwargs['consume'])
                stage=build.call_args.args[3]
            self.assertFalse(stage.parent.exists())

if __name__=='__main__':unittest.main()
