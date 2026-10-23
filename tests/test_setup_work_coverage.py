import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from setup_work_coverage import RECORD, upgrade


class SetupWorkCoverageTests(unittest.TestCase):
    def test_audit_preserves_hardlinked_saved_package_and_is_repeatable(self):
        report = dict(version=1, selected_profiles=['source_profile'], actor_count=2,
                      assignments=[dict(person='source_worker')], ownership_counts={'selected_profile_assignment': 1})
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            original = root / 'saved.json'
            original.write_text('original saved work', encoding='utf-8')
            package = root / 'private'; package.mkdir()
            os.link(original, package / RECORD)
            with patch('source_work_coverage.audit', return_value=report):
                files, result = upgrade(str(package), 'source-game')
                stat = (package / RECORD).stat()
                again = upgrade(package, Path('source-game'))
            self.assertEqual(original.read_text(encoding='utf-8'), 'original saved work')
            self.assertEqual(again, (files, result))
            self.assertEqual((package / RECORD).stat().st_mtime_ns, stat.st_mtime_ns)
            self.assertEqual(json.loads((package / RECORD).read_text()), report)
            self.assertFalse(result['runtime_verified'])
            self.assertEqual(set(files), {RECORD})

    def test_missing_source_does_not_write_a_success_report(self):
        with tempfile.TemporaryDirectory() as temporary:
            with self.assertRaisesRegex(ValueError, 'source'):
                upgrade(temporary, None)
            self.assertEqual(list(Path(temporary).iterdir()), [])
