import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'tools'))
from build_recipe import apply_overlay, reviewed_blend_mesh, run


class RecipeTests(unittest.TestCase):
    def test_reviewed_models_include_their_lods_only(self):
        root = 'objects/buildings/houses/modular/6x15/'
        self.assertTrue(reviewed_blend_mesh(root+'6x15_roof_p_03_flipped.cgf'))
        self.assertTrue(reviewed_blend_mesh((root+'6x15_roof_p_03_flipped_lod2.cgf').upper().replace('/', '\\')))
        self.assertFalse(reviewed_blend_mesh(root+'6x15_roof_p_04.cgf'))
        self.assertFalse(reviewed_blend_mesh(None))

    def test_overlay_detaches_links_and_can_build_again(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            original = root/'original.pak'; original.write_bytes(b'old')
            overlay = root/'overlay'; (overlay/'Data').mkdir(parents=True)
            (overlay/'Data/test.pak').write_bytes(b'new')
            for index in range(2):
                package = root/str(index); (package/'Data').mkdir(parents=True)
                os.link(original, package/'Data/test.pak')
                changed = apply_overlay(package, overlay)
                self.assertEqual((package/'Data/test.pak').read_bytes(), b'new')
                self.assertEqual(original.read_bytes(), b'old')
                self.assertEqual(list(changed), ['Data/test.pak'])

    def test_cancel_and_completed_recipe_do_not_run_builders(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with patch('build_recipe.verify_package', return_value={'files': {}}), patch('build_open_test_gates.build') as gates:
                with self.assertRaises(InterruptedError):
                    run(root/'source', root/'target', root/'package', root/'work', cancelled=lambda: True)
                gates.assert_not_called()
            with patch('build_recipe.verify_package', return_value={'build_recipe': {'version': 1}}):
                with self.assertRaisesRegex(ValueError, 'already applied'):
                    run(root/'source', root/'target', root/'package', root/'other')
                self.assertFalse((root/'other').exists())


if __name__ == '__main__': unittest.main()
