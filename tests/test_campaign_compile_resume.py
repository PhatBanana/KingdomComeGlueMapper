"""The persistent work directory of campaign_compile (fork: skalitz-finish)."""
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
import campaign_compile_resume as resume

KCD1 = Path(os.environ.get('GLUEMAPPER_KCD1', 'D:/SteamLibrary/steamapps/common/KingdomComeDeliverance'))
KCD2 = Path(os.environ.get('GLUEMAPPER_KCD2', 'D:/SteamLibrary/steamapps/common/KingdomComeDeliverance2'))
RETAIL = (KCD1 / 'Data/Scripts.pak').is_file() and (KCD2 / 'Data/Scripts.pak').is_file()


class ResumeTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.work = Path(self.directory.name) / 'work'
        self.addCleanup(self.directory.cleanup)

    def test_without_a_work_directory_the_build_is_temporary_as_before(self):
        output = Path(self.directory.name) / 'out'
        with resume.work_directory(None, output) as temporary:
            self.assertTrue(Path(temporary).name.startswith('.campaign-convert-'))
            self.assertEqual(Path(temporary).parent, output.parent)
            Path(temporary, 'x').write_text('x')
        self.assertFalse(Path(temporary).exists())

    def test_a_work_directory_keeps_only_the_reusable_products(self):
        stage = self.work / 'stage'
        for name in ('source-ir/q.json', 'person-assets/p/a.bin', 'native-fragments/old.xml', 'bindings.json'):
            (stage / name).parent.mkdir(parents=True, exist_ok=True)
            (stage / name).write_text('x')
        (self.work / 'asset-cache').mkdir()
        with resume.work_directory(self.work, self.work / 'out') as temporary:
            self.assertEqual(Path(temporary), self.work)
            self.assertEqual(sorted(p.name for p in stage.iterdir()), ['person-assets', 'source-ir'])
            self.assertTrue((self.work / 'asset-cache').is_dir())
        self.assertTrue((stage / 'source-ir/q.json').is_file())

    def test_a_quest_model_is_reused_only_for_the_same_request(self):
        calls = []
        def build():
            calls.append(1)
            return dict(quest='q', pair=(1, 2), n=len(calls))
        first, reused = resume.quest_model(self.work / 'stage', 'q', dict(level='a'), build)
        self.assertEqual((first, reused), (dict(quest='q', pair=[1, 2], n=1), False))
        again, reused = resume.quest_model(self.work / 'stage', 'q', dict(level='a'), build)
        self.assertEqual((again, reused, len(calls)), (first, True, 1))
        changed, reused = resume.quest_model(self.work / 'stage', 'q', dict(level='b'), build)
        self.assertEqual((changed['n'], reused), (2, False))
        (self.work / 'stage/source-ir/q.key').unlink()
        self.assertEqual(resume.quest_model(self.work / 'stage', 'q', dict(level='b'), build)[1], False)

    def test_a_finished_person_is_reused_and_an_interrupted_one_rebuilt(self):
        built = []
        def fake(source, target, person, namespace, destination):
            built.append(namespace)
            destination.mkdir(parents=True)
            (destination / 'model.bin').write_bytes(b'x' * 10)
            return dict(inventory=namespace + '_inv', parts=('a', 'b'))
        with mock.patch('character_person_appearance.build_appearance', fake):
            build = resume.appearance_builder(self.work)
            destination = self.work / 'stage/person-assets/p1'
            first = build(None, None, None, 'p1', destination)
            self.assertEqual(first, dict(inventory='p1_inv', parts=['a', 'b']))
            self.assertEqual((build(None, None, None, 'p1', destination), built), (first, ['p1']))
            (destination.parent / 'p1.done.json').unlink()   # as if the build had been interrupted
            (destination / 'partial.bin').write_bytes(b'y')
            build(None, None, None, 'p1', destination)
            self.assertEqual((built, sorted(p.name for p in destination.iterdir())), (['p1', 'p1'], ['model.bin']))
            capped = resume.appearance_builder(self.work, cap=5)
            with self.assertRaises(ValueError):
                capped(None, None, None, 'p2', self.work / 'stage/person-assets/p2')
            self.assertEqual(capped(None, None, None, 'p1', destination), first)

    def test_the_cap_is_recorded_as_that_persons_failure_and_the_import_goes_on(self):
        from campaign_dependencies import DependencyImporter, ImportPlan
        capped = resume.appearance_builder(self.work, cap=-1)
        class Souls:
            def plan(self, identity):
                return ImportPlan()
            def convert(self, identity, plan, registered):
                if identity == 'ok':
                    return 'ok', {}, {}
                capped(None, None, None, identity, Path(self_work) / 'stage/person-assets' / identity)
        self_work = self.work
        importer = DependencyImporter(dict(souls=Souls()))
        self.assertIsNone(importer.ensure('souls', 'p1'))
        self.assertEqual(importer.ensure('souls', 'ok'), 'ok')
        self.assertEqual(importer.jobs[('souls', 'p1')]['status'], 'conversion_failed')
        self.assertIn('GB cap', importer.jobs[('souls', 'p1')]['error'])

    def test_registration_only_people_get_a_record_and_no_files(self):
        import xml.etree.ElementTree as ET
        with mock.patch.object(resume, 'PEOPLE', 'register'),                 mock.patch('character_person_appearance.build_appearance', side_effect=AssertionError('built')),                 mock.patch('build_npc_clothing_probe.native_soul_archetype', lambda table, sex: 'arch-' + sex),                 mock.patch('zipfile.ZipFile') as archive:
            archive.return_value.__enter__.return_value.read.return_value = b'<x/>'
            build = resume.appearance_builder(self.work, cap=-1)   # the cap does not apply: nothing is built
            destination = self.work / 'stage/person-assets/ns'
            woman = build(None, 'kcd2', dict(actor=ET.Element('Entity', EntityClass='NPC_Female')), 'ns', destination)
            man = build(None, 'kcd2', dict(actor=ET.Element('Entity', EntityClass='NPC')), 'ns2', destination)
        self.assertEqual((woman['archetype'], woman['gender'], woman['inventory'], woman['appearance']),
                         ('arch-Female', 'female', 'ns_clothes', {}))
        self.assertEqual((man['archetype'], man['gender'], man['appearance_deferred']), ('arch-Male', 'male', True))
        self.assertFalse(destination.exists())

    def test_person_assets_are_moved_and_other_payloads_copied(self):
        stage = self.work / 'stage'
        person, other = stage / 'person-assets/p/a.bin', self.work / 'asset-cache/b.bin'
        for path in (person, other):
            path.parent.mkdir(parents=True)
            path.write_bytes(path.name.encode())
        out = stage / 'native-fragments'
        out.mkdir()
        resume.place(person, out / 'a.bin', stage)
        resume.place(person, out / 'a_again.bin', stage)
        resume.place(other, out / 'b.bin', stage)
        self.assertEqual((person.exists(), other.exists()), (False, True))
        self.assertEqual([(out / n).read_bytes() for n in ('a.bin', 'a_again.bin', 'b.bin')], [b'a.bin', b'a.bin', b'b.bin'])
        resume.release_people(stage)
        self.assertFalse((stage / 'person-assets').exists())


@unittest.skipUnless(RETAIL, 'requires installed retail KCD1 and KCD2 scripts')
class RetailEquivalenceTests(unittest.TestCase):
    def test_a_quest_converts_identically_from_its_stored_form(self):
        """What a work run changes for a quest is the JSON form of its IR; the converted trees must not differ."""
        from campaign_behavior import convert_behaviors, native_catalog
        from campaign_sources import RetailSourceReader
        import quest_controller_conversion as c2
        with RetailSourceReader(KCD1) as reader:
            model, _ = c2.import_model(KCD1, 'q_tutorial_swordOne', reader)
        with tempfile.TemporaryDirectory() as tmp:
            stored, reused = resume.quest_model(Path(tmp), 'q_tutorial_swordOne', dict(level='rataje'), lambda: model)
            again, reused_again = resume.quest_model(Path(tmp), 'q_tutorial_swordOne', dict(level='rataje'), lambda: self.fail('rebuilt'))
        self.assertEqual((reused, reused_again, stored), (False, True, again))
        catalog = native_catalog(KCD2)
        direct = convert_behaviors([model], 'T', json.loads(json.dumps(catalog)))
        from_store = convert_behaviors([stored], 'T', json.loads(json.dumps(catalog)))
        self.assertEqual(direct[0], from_store[0])
        self.assertEqual(direct[1], from_store[1])
        self.assertEqual(json.dumps(direct[2], sort_keys=True, default=str), json.dumps(from_store[2], sort_keys=True, default=str))
        self.assertGreater(len(direct[2]['trees']), 0)


if __name__ == '__main__': unittest.main()
