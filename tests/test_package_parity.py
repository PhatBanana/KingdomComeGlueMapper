import sys
from pathlib import Path
import tempfile
import unittest
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from audit_package_parity import compare


class PackageParityTests(unittest.TestCase):
    def test_resharding_is_not_missing_and_conflicting_overrides_are_visible(self):
        with tempfile.TemporaryDirectory() as directory:
            a, b = [Path(directory) / n for n in ('old', 'new')]
            for root in (a, b):
                (root / 'Data').mkdir(parents=True)
                (root / 'mod.manifest').write_text('<mod/>')
            def pak(root, name, entries):
                with zipfile.ZipFile(root / 'Data' / name, 'w') as z:
                    for path, payload in entries.items(): z.writestr(path, payload)
            pak(a, 'first.pak', {'Objects/A.cgf': b'old', 'Scripts/mother.lua': b'scene'})
            pak(b, 'different-shard.pak', {'objects/a.cgf': b'old'})
            result = compare(a, b)
            self.assertEqual(list(result['missing']), ['data/scripts/mother.lua'])
            self.assertEqual(result['changed_count'], 0)
            pak(b, 'override.pak', {'objects/a.cgf': b'new'})
            result = compare(a, b)
            self.assertIn('data/objects/a.cgf', result['conflicting_overrides']['candidate'])
            self.assertEqual(result['changed_count'], 1)


if __name__ == '__main__': unittest.main()
