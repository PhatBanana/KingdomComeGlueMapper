from pathlib import Path
import sys
import tempfile
import unittest
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from cinematic_subtitles import convert


class CinematicSubtitlesTests(unittest.TestCase):
    def test_original_timing_and_unique_localization_keys(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'language.pak'
            with zipfile.ZipFile(path, 'w') as archive:
                archive.writestr('text_ui_dialog.xml', '<Table><Row><Cell>original</Cell><Cell>Hello</Cell><Cell>Hello</Cell></Row></Table>')
            cues = [dict(key='@original', scale=1000, start=53834, duration=5215)]
            srt, strings, sources = convert(cues, path)
            self.assertIn(b'00:00:53,834 --> 00:00:59,049', srt)
            self.assertIn(b'gm_cin_', srt)
            self.assertIn(b'Hello', strings)
            self.assertEqual(sources['original'], 'text_ui_dialog.xml')
            cues[0]['key'] = '@absent'
            with self.assertRaisesRegex(ValueError, 'Missing localized'):
                convert(cues, path)


if __name__ == '__main__':
    unittest.main()
