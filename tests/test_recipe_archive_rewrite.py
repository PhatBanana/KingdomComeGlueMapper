from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from build_horse_trader_test import rewrite


class RecipeArchiveRewriteTests(unittest.TestCase):
    def check_rewrite(self):
        with tempfile.TemporaryDirectory() as tmp:
            source, target = Path(tmp)/'source.pak', Path(tmp)/'target.pak'
            with zipfile.ZipFile(source, 'w') as archive:
                archive.writestr('keep', b'original geometry' * 80)
                archive.writestr('replace', b'old')
            rewrite(source, target, {'replace': b'new', 'added': b'quest'})
            with zipfile.ZipFile(target) as archive:
                self.assertIsNone(archive.testzip())
                self.assertEqual(set(archive.namelist()), {'keep', 'replace', 'added'})
                self.assertEqual(archive.read('keep'), b'original geometry' * 80)
                self.assertEqual(archive.read('replace'), b'new')
                self.assertEqual(archive.read('added'), b'quest')
            return target.read_bytes()

    def test_small_archive_does_not_emit_zip64(self):
        self.assertNotIn(b'PK\x06\x06', self.check_rewrite())

    def test_large_member_and_directory_offset_survive_rewrite(self):
        # Exercise the real ZIP64 writer without allocating gigabytes in tests.
        with patch.object(zipfile, 'ZIP64_LIMIT', 1024):
            self.assertIn(b'PK\x06\x06', self.check_rewrite())

    def test_entry_count_can_grow_past_classic_directory_limit(self):
        with patch.object(zipfile, 'ZIP_FILECOUNT_LIMIT', 2):
            self.assertIn(b'PK\x06\x06', self.check_rewrite())


if __name__ == '__main__':
    unittest.main()
