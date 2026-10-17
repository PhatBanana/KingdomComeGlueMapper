import sys
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'tools'))
from setup_shaders import REPAIRS, patched, validate, compilation_result
from shader_fixture import package_shaders


class ShaderSetupTests(unittest.TestCase):
    def test_repairs_rebuild_against_previous_install_and_reject_unknown_source(self):
        for name, pair in REPAIRS.items():
            result = patched(name,pair[0])
            self.assertEqual(result,pair[1])
            self.assertEqual(patched(name,result),result)
            with self.assertRaises(ValueError): patched(name,b'unknown native shader')

    def test_compiler_exit_without_success_summary_or_with_errors_is_not_success(self):
        summary='Combinations: (Material: 20, Processed: 31; Compiled: 30; Removed: 5)'
        self.assertEqual(compilation_result(summary)['compiled'],30)
        for log in ('', summary+'\nerror X3000: invalid conversion', summary+'\nShader compile failed'):
            with self.assertRaises(ValueError): compilation_result(log)

    def test_compiled_package_is_explicitly_build_only(self):
        with tempfile.TemporaryDirectory() as t:
            root=Path(t); package=root/'package'; package.mkdir(); package_shaders(package)
            report=validate(package)
            self.assertEqual(report['installation'],'build_only')
            self.assertFalse(report['isolated_mount_verified'])
            self.assertFalse(report['runtime_verified'])

    def test_tampered_package_does_not_change_game(self):
        with tempfile.TemporaryDirectory() as t:
            root=Path(t); package=root/'package'; package.mkdir(); package_shaders(package)
            self.assertEqual(validate(package)['repairs'],3)
            (package/'Engine/ShaderCache.pak').write_bytes(b'tampered')
            with self.assertRaisesRegex(ValueError,'changed'): validate(package)
            self.assertFalse((root/'target').exists())


if __name__=='__main__': unittest.main()
