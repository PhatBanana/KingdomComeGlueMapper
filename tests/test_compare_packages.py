import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from compare_packages import compare, RECEIPT


class ComparePackageTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def package(self, name, when, created_on, entries=None, loose=b'{"world": 1}', compression=zipfile.ZIP_STORED):
        """Write a small package the way setup does: timestamped entries, dated manifest, digest receipt."""
        root = self.root / name
        (root / 'Data/Levels/kcd1_rataje').mkdir(parents=True)
        entries = entries or [('terrain/terrain.dat', b'heights'), ('levelinfo.xml', b'<LevelInfo/>')]
        with zipfile.ZipFile(root / 'Data/Levels/kcd1_rataje/level.pak', 'w', compression) as pak:
            for entry, data in entries:
                pak.writestr(zipfile.ZipInfo(entry, when), data, compression)
        (root / 'campaign.json').write_bytes(loose)
        (root / 'mod.manifest').write_text(f'<kcd_mod><info><modid>m</modid><created_on>{created_on}</created_on></info></kcd_mod>')
        files = {p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
                 for p in sorted(root.rglob('*')) if p.is_file()}
        (root / RECEIPT).write_text(json.dumps({'schema': 1, 'version': '1', 'files': files}))
        return root

    def test_rebuild_with_new_timestamps_and_date_is_equivalent(self):
        first = self.package('first', (2026, 10, 11, 9, 0, 0), '2026-10-11')
        second = self.package('second', (2026, 10, 12, 18, 30, 4), '2026-10-12')
        self.assertNotEqual((first / RECEIPT).read_bytes(), (second / RECEIPT).read_bytes())
        self.assertEqual(compare(first, second), [])
        self.assertEqual(compare(first, second, deep=True), [])

    def test_reports_changed_missing_and_reordered_entries(self):
        first = self.package('first', (2026, 1, 1, 0, 0, 0), 'd')
        changed = self.package('changed', (2026, 1, 1, 0, 0, 0), 'd',
                               [('terrain/terrain.dat', b'HEIGHTS'), ('extra.xml', b'<x/>')])
        self.assertEqual(compare(first, changed), [
            'Data/Levels/kcd1_rataje/level.pak: levelinfo.xml only in left',
            'Data/Levels/kcd1_rataje/level.pak: extra.xml only in right',
            'Data/Levels/kcd1_rataje/level.pak: terrain/terrain.dat differs in content'])
        reordered = self.package('reordered', (2026, 1, 1, 0, 0, 0), 'd',
                                 [('levelinfo.xml', b'<LevelInfo/>'), ('terrain/terrain.dat', b'heights')])
        self.assertEqual(compare(first, reordered), ['Data/Levels/kcd1_rataje/level.pak: entry order or duplicate entries differ'])

    def test_reports_compression_loose_receipt_manifest_and_missing_files(self):
        first = self.package('first', (2026, 1, 1, 0, 0, 0), 'd')
        deflated = self.package('deflated', (2026, 1, 1, 0, 0, 0), 'd', compression=zipfile.ZIP_DEFLATED)
        self.assertEqual(compare(first, deflated), [
            'Data/Levels/kcd1_rataje/level.pak: levelinfo.xml differs in compression',
            'Data/Levels/kcd1_rataje/level.pak: terrain/terrain.dat differs in compression'])
        loose = self.package('loose', (2026, 1, 1, 0, 0, 0), 'd', loose=b'{"world": 2}')
        self.assertEqual(compare(first, loose), ['campaign.json: content differs', f'{RECEIPT}: receipt differs in files'])
        (loose / 'mod.manifest').write_text('<kcd_mod><info><modid>other</modid></info></kcd_mod>')
        (loose / 'extra.txt').write_text('new')
        self.assertIn('mod.manifest: manifest differs beyond created_on', compare(first, loose))
        self.assertIn('extra.txt: only in right', compare(first, loose))
        self.assertNotIn('extra.txt: only in right', compare(first, loose, ignore=['extra.*']))


if __name__ == '__main__':
    unittest.main()
