from io import BytesIO
import json
from pathlib import Path
import sys
import tempfile
import unittest
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from upgrade_source_appearances import imports, owned_shards, validate_resources, verify_bindings
from setup_package_upgrade import rewrite
from build_profile_population_upgrade import clone_missing

NS = 'gm_person_' + 'a' * 32


def archive(entries):
    stream = BytesIO()
    with zipfile.ZipFile(stream, 'w') as z:
        for name, value in entries.items():
            z.writestr(name, value)
    stream.seek(0)
    return zipfile.ZipFile(stream)


class SourceAppearanceUpgradeTests(unittest.TestCase):
    def test_import_requires_explicit_unambiguous_owned_identity(self):
        row = dict(person='source_npc', namespace=NS, appearance='character_person_appearance')
        with archive({'Libs/GlueMapper/PersonImport/' + NS + '.json': json.dumps(row)}) as z:
            self.assertEqual(imports(z, ['source_npc']), {'source_npc': NS})
            with self.assertRaisesRegex(ValueError, 'No imported'):
                imports(z, ['unregistered'])
        row['namespace'] = '../outside'
        with archive({'Libs/GlueMapper/PersonImport/' + NS + '.json': json.dumps(row)}) as z:
            with self.assertRaisesRegex(ValueError, 'ownership'):
                imports(z, ['source_npc'])

    def test_only_appearance_tables_are_accepted(self):
        validate_resources({'Libs/Tables/Character/CharacterComponent__' + NS + '.xml': b'<database/>'}, NS)
        validate_resources({'Libs/Tables/item/clothing_preset__' + NS + '.xml': b'<database/>'}, NS)
        for path in ('Libs/Storm/storm.xml', 'Libs/Tables/item/item__another.xml',
                     'Libs/Tables/rpg/soul__' + NS + '.xml'):
            with self.subTest(path=path), self.assertRaisesRegex(ValueError, 'unrelated'):
                validate_resources({path: b'<database/>'}, NS)

    def test_changed_storm_identities_require_explicit_migration(self):
        entries = {'Libs/Storm/appearance/' + NS + '.xml':
                   '<storm><rules><rule><operations><setBody name="body"/></operations></rule></rules></storm>'}
        with archive(entries) as z:
            character = dict(appearance={'body': 'body'}, inventory=NS + '_clothes')
            verify_bindings(z, character, NS)
            character['appearance']['body'] = 'new_body'
            with self.assertRaisesRegex(ValueError, 'identities changed'):
                verify_bindings(z, character, NS)

    def test_refuses_shard_with_weapon_or_unrelated_assets(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / 'Data').mkdir()
            relative = 'Data/' + NS + '.pak'
            with zipfile.ZipFile(root / relative, 'w') as z:
                z.writestr('objects/characters/gluetravel/' + NS + '/body.skin', b'body')
            self.assertEqual(owned_shards(root, {relative: 'hash'}, NS), [relative])
            with zipfile.ZipFile(root / relative, 'a') as z:
                z.writestr('objects/weapons/sword.cgf', b'weapon')
            with self.assertRaisesRegex(ValueError, 'unrelated assets'):
                owned_shards(root, {relative: 'hash'}, NS)

    def test_copy_on_replace_preserves_baseline_and_gameplay_members(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            baseline, candidate = root / 'baseline', root / 'candidate'
            baseline.mkdir()
            with zipfile.ZipFile(baseline / 'travel.pak', 'w') as z:
                z.writestr('appearance.xml', b'old')
                z.writestr('quests.xml', b'original quests')
                z.writestr('scheduler.xml', b'original schedules')
            original = (baseline / 'travel.pak').read_bytes()
            clone_missing(baseline, candidate)
            rewrite(candidate, 'travel.pak', {'appearance.xml': b'new'})
            self.assertEqual((baseline / 'travel.pak').read_bytes(), original)
            with zipfile.ZipFile(candidate / 'travel.pak') as z:
                self.assertEqual(z.read('appearance.xml'), b'new')
                self.assertEqual(z.read('quests.xml'), b'original quests')
                self.assertEqual(z.read('scheduler.xml'), b'original schedules')


if __name__ == '__main__':
    unittest.main()
