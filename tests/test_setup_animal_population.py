import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
import xml.etree.ElementTree as E
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from animal_population import VERSION
from build_animal_population_upgrade import LEVEL, TRAVEL
from setup_animal_population import MODE, upgrade, validate_package
from setup_gameplay import STATIC_WORLD_PROFILES
from setup_package_upgrade import rewrite
from upgrade_map import digest
from test_animal_population import source_site, native_world
from test_animal_population_package import fixture


class SetupAnimals(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.package = self.root/'package'
        fixture(self.package)
        self.source = self.root/'source'
        self.target = self.root/'target'
        source = self.source/'Data/Levels/rataje/level.pak'
        source.parent.mkdir(parents=True)
        entities = source_site()
        # An unsupported source contract must remain visible in the receipt.
        bad = source_site(radius='0')['1']
        bad.set('EntityId', '3'); bad.set('EntityGuid', '123'); bad.set('Name', 'point_spawn')
        entities['3'] = bad
        with zipfile.ZipFile(source, 'w') as archive:
            archive.writestr('objects_mission0.xml', b'<Objects>' +
                b''.join(E.tostring(e) for e in entities.values()) + b'</Objects>')
            archive.writestr('whdata_1', '<Root>' + ''.join(
                f'<GameProfile><Name>{profile}</Name><GameLayers/></GameProfile>'
                for profile in STATIC_WORLD_PROFILES) + '</Root>')
        (self.target/'Data').mkdir(parents=True)
        with zipfile.ZipFile(self.target/'Data/Scripts.pak', 'w'):
            pass
        mission, scheduler = native_world()
        self.native = patch('animal_population.native_catalog', return_value=(
            {'animal_cattle_cow': 'native-cow'}, None, [('trosecko', mission, scheduler)]))
        self.native.start()
        self.addCleanup(self.native.stop)

    def run_upgrade(self, **kwargs):
        return upgrade(self.package, self.source, self.target, STATIC_WORLD_PROFILES, **kwargs)

    def test_clean_package_converts_and_resume_is_byte_identical(self):
        files, report = self.run_upgrade()
        self.assertEqual(report['version'], VERSION)
        self.assertEqual(report['mode'], MODE)
        self.assertEqual(report['profiles'], list(STATIC_WORLD_PROFILES))
        self.assertTrue(report['scheduler_validation'])
        self.assertEqual(report['populations_added'], 1)
        self.assertEqual(len(report['pending']), 1)
        self.assertFalse(report['complete'])
        self.assertFalse(report['runtime_verified'])
        self.assertEqual(files, {name: digest(self.package/name) for name in (LEVEL, TRAVEL)})
        with zipfile.ZipFile(self.package/LEVEL) as level, zipfile.ZipFile(self.package/TRAVEL) as travel:
            self.assertEqual(level.read('terrain/keep.bin'), b'geometry unchanged')
            self.assertEqual(travel.read('Quests/existing.xml'), b'quest unchanged')
            self.assertEqual(level.read('tables/ai/scheduler.xml'),
                travel.read('Mods/example/Data/Levels/kcd1_travel/tables/ai/scheduler.xml'))
        with patch('setup_package_upgrade.rewrite', side_effect=AssertionError('Unneeded rewrite')):
            again, resumed = self.run_upgrade()
        self.assertEqual(again, files)
        self.assertEqual(resumed, report)

    def test_resume_does_not_mutate_hardlinked_baseline(self):
        baseline = self.root/'baseline'
        baseline.mkdir()
        before = {}
        for i, name in enumerate((LEVEL, TRAVEL)):
            path = baseline/f'{i}.pak'
            os.link(self.package/name, path)
            before[path] = digest(path)
        self.run_upgrade()
        self.assertEqual({p: digest(p) for p in before}, before)

    def test_missing_native_registration_fails_before_any_archive_replacement(self):
        mission, scheduler = native_world()
        scheduler.find('Schedulers').remove(scheduler.find('Schedulers')[-1])
        with patch('animal_population.native_catalog', return_value=(
                {'animal_cattle_cow': 'native-cow'}, None, [('trosecko', mission, scheduler)])), \
                patch('setup_package_upgrade.rewrite') as publish:
            with self.assertRaisesRegex(ValueError, 'Missing native animal home scheduler'):
                self.run_upgrade()
        publish.assert_not_called()

    def test_validation_rejects_stale_mounted_scheduler_and_wrong_profile(self):
        self.run_upgrade()
        with self.assertRaisesRegex(ValueError, 'profiles differ'):
            validate_package(self.package, ('different_profile',))
        rewrite(self.package, TRAVEL, {
            'Mods/example/Data/Levels/kcd1_travel/tables/ai/scheduler.xml': b'<stale/>'})
        with self.assertRaisesRegex(ValueError, 'scheduler differs'):
            validate_package(self.package, STATIC_WORLD_PROFILES)
        with patch('setup_package_upgrade.rewrite') as publish:
            with self.assertRaisesRegex(ValueError, 'scheduler differs'):
                self.run_upgrade()
        publish.assert_not_called()

    def test_cancel_or_missing_source_does_not_publish(self):
        with patch('setup_package_upgrade.rewrite') as publish:
            with self.assertRaises(InterruptedError):
                self.run_upgrade(cancelled=lambda: True)
            with self.assertRaisesRegex(ValueError, 'Both source games'):
                upgrade(self.package, None, self.target, STATIC_WORLD_PROFILES)
        publish.assert_not_called()


if __name__ == '__main__': unittest.main()
