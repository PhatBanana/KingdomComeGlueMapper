import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'tools'))
from setup_web import SetupAPI, CONVERTER_FILTER, converter_info
from webview.util import parse_file_type


class ConverterTests(unittest.TestCase):
    def test_filter_is_accepted_by_real_webview_parser(self):
        self.assertEqual(parse_file_type(CONVERTER_FILTER[0]), ('RAD Video Tools', '*.exe'))

    def test_selection_is_remembered_and_cancel_preserves_it(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'radvideo64.exe';path.write_bytes(b'MZfixture')
            api=SetupAPI();api._settings=Path(folder)/'settings.json'
            api._window=Mock()
            api._window.create_file_dialog.return_value=(str(path),)
            selected=api.locate_converter()
            again=SetupAPI();again._settings=api._settings
            self.assertEqual(again.find_converter(),selected)
            api._window.create_file_dialog.return_value=None
            self.assertIsNone(api.locate_converter())
            self.assertEqual(again.find_converter(),selected)
            api._window.create_file_dialog.assert_called_with(
                __import__('webview').FileDialog.OPEN,file_types=CONVERTER_FILTER)

    def test_wrong_program_and_invalid_executable_are_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'installer.exe';path.write_bytes(b'MZfixture')
            with self.assertRaises(ValueError):converter_info(path)
            path=Path(folder)/'radvideo64.exe';path.write_bytes(b'not executable')
            with self.assertRaises(ValueError):converter_info(path)


if __name__=='__main__':unittest.main()
