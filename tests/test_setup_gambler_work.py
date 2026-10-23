from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from setup_gambler_work import upgrade


class GamblerUpgradeTests(unittest.TestCase):
    def test_updates_mounted_scheduler_and_is_repeatable(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);package=root/'package';source=root/'source';target=root/'target'
            level='Data/Levels/kcd1_travel/level.pak'
            old={'objects_mission0.xml':b'<Objects/>','tables/ai/scheduler.xml':b'<old/>','waitinglinks.xml':b'<links/>'}
            new=dict(old,**{'tables/ai/scheduler.xml':b'<new/>'})
            for path,contents in [(package/level,old),(package/'Data/gluemappertravel.pak',{'untouched':b'keep'}),
                                  (source/'Data/Levels/rataje/level.pak',{})]:
                path.parent.mkdir(parents=True,exist_ok=True)
                with zipfile.ZipFile(path,'w') as z:
                    for name,data in contents.items():z.writestr(name,data)
            (package/'mod.manifest').write_text('<mod><info><modid>example</modid></info></mod>')
            definitions={'AI/gluemapper/source_dice_10.xml':b'<BehaviorTrees/>'}
            with patch('campaign_sources.RetailSourceReader'),patch('campaign_dependency_adapters.SourceTables'),\
                 patch('profile_population_upgrade.discover',return_value=(None,{},None)),\
                 patch('character_gambler_work.extend_people',return_value=(new,definitions,[{'job':'source_gambler_dice_or_lean'}])),\
                 patch('gambler_schedule_activation.prepare',side_effect=lambda package,target,files,reports,defs:(files,defs)),\
                 patch('gambler_dialogue_registration.prepare',side_effect=lambda package,target,files:(files,{},{})),\
                 patch('campaign_combat_work.validate') as validate:
                changes,_=upgrade(package,source,target)
                self.assertEqual(set(changes),{level,'Data/gluemappertravel.pak'})
                with zipfile.ZipFile(package/'Data/gluemappertravel.pak') as z:
                    self.assertEqual(z.read('untouched'),b'keep')
                    self.assertEqual(z.read('Mods/example/Data/Levels/kcd1_travel/tables/ai/scheduler.xml'),b'<new/>')
                self.assertEqual(upgrade(package,source,target)[0],{})
                self.assertEqual(validate.call_count,2)


if __name__=='__main__':unittest.main()
