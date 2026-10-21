import os
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from filesystem_paths import filesystem_path, staging_self_test


class FilesystemPathsTests(unittest.TestCase):
    def test_normalized_path_is_absolute_and_idempotent(self):
        path = filesystem_path('outputs/../outputs')
        self.assertTrue(path.is_absolute())
        self.assertEqual(filesystem_path(path), path)
        if os.name == 'nt':
            self.assertTrue(str(path).startswith('\\\\?\\'))

    def test_long_path_roundtrip_and_cleanup(self):
        with tempfile.TemporaryDirectory() as directory:
            report = staging_self_test(directory)
            self.assertEqual(report['status'], 'passed')
            self.assertGreater(report['path_length'], 260)
            self.assertEqual(list(Path(directory).iterdir()), [])


if __name__ == '__main__':
    unittest.main()
