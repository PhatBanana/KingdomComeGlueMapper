"""Converter C2: world profiles under the names the scene converter registers."""
from pathlib import Path
import sys
import unittest
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from campaign_controller_profiles import OwnedProfiles, native_name, report
from campaign_dependencies import DependencyImporter


class ProfileTests(unittest.TestCase):
    def importer(self, names=('q_Example_attack',)):
        adapter = OwnedProfiles(names)
        return DependencyImporter(dict(world_profiles=adapter)), adapter

    def test_a_registered_profile_keeps_the_scene_converters_name(self):
        importer, adapter = self.importer()
        self.assertEqual(importer.ensure('world_profiles', 'q_Example_attack', dict(tree='a')), 'gm_q_Example_attack')
        self.assertEqual(importer.ensure('world_profiles', 'q_example_attack', dict(tree='b')), 'gm_q_Example_attack')
        self.assertEqual(importer.files, {})
        self.assertEqual(native_name('x'), 'gm_x')

    def test_an_unregistered_profile_stays_unconverted_and_is_listed(self):
        importer, adapter = self.importer()
        importer.ensure('world_profiles', 'q_Example_attack', dict(tree='a'))
        self.assertIsNone(importer.ensure('world_profiles', 'q_example_cameras', dict(tree='a')))
        self.assertIsNone(importer.ensure('world_profiles', 'q_example_cameras', dict(tree='b')))
        self.assertEqual(importer.jobs[('world_profiles', 'q_example_cameras')]['error'],
                         'World profile is not registered by the scene converter: q_example_cameras')
        self.assertEqual(report(importer, adapter), dict(
            registered=['q_Example_attack'], used=dict(q_example_attack=dict(native='gm_q_Example_attack', sites=1)),
            to_register=dict(q_example_cameras=2), runtime_verified=False))

    def test_two_registered_names_cannot_differ_only_by_case(self):
        with self.assertRaises(ValueError):
            OwnedProfiles(['a_b', 'A_B'])


if __name__ == '__main__': unittest.main()
