import os
import json
from contextlib import ExitStack
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'tools'))
from campaign_start_policy import POLICY
from build_recipe import VERSION, apply_overlay, reviewed_blend_mesh, run, require_current
from setup_campaign import RECEIPT
from setup_gameplay import STAGE_IDS


class RecipeTests(unittest.TestCase):
    def test_old_or_incomplete_recipe_cannot_be_installed(self):
        report = dict(version=VERSION, status='complete',
                      content_validation={'actors': 11, 'start_policy': POLICY}, streaming_validation={'proxies': 1}, shader_validation={'compiled': True, 'installation': 'mod_private_root'},
                      steps=[{'id': identity} for identity in STAGE_IDS])
        self.assertEqual(require_current({'build_recipe': report}), report)
        for field, value in (('version', VERSION-1), ('status', 'building'),
                             ('content_validation', {}), ('content_validation', {'actors': 11}), ('streaming_validation', {}), ('shader_validation', {}),
                             ('shader_validation', {'compiled': True, 'installation': 'build_only'}),
                             ('steps', report['steps'][:-1]), ('steps', report['steps'][::-1])):
            with self.subTest(field=field, value=value), self.assertRaises(ValueError):
                require_current({'build_recipe': dict(report, **{field: value})})

    def exercise_recipe(self, fail=False):
        with tempfile.TemporaryDirectory() as directory, ExitStack() as stack:
            root = Path(directory); package = root/'package'; package.mkdir()
            (package/RECEIPT).write_text(json.dumps({'files': {}}))
            (package/'chain').write_text('base')
            seen = []
            def verify(path, **kwargs):
                return json.loads((Path(path)/RECEIPT).read_text())
            def stage(identity, output, folder='package'):
                previous = (package/'chain').read_text()
                self.assertEqual(previous, seen[-1] if seen else 'base')
                seen.append(identity)
                dest = output/folder; dest.mkdir(parents=True)
                (dest/'chain').write_text(identity)
            def gates(mod, output, **kwargs):
                # Gate output has Data directly; run() normalizes it.
                stage('gates', output, 'Data')
            stack.enter_context(patch('build_recipe.verify_package', side_effect=verify))
            # Keep the dependency assertion independent of the gates' archive layout.
            stack.enter_context(patch('build_open_test_gates.build', side_effect=gates))
            original_apply = apply_overlay
            def apply(package, overlay, **kwargs):
                result = original_apply(package, overlay, **kwargs)
                if (package/'Data/chain').exists() and len(seen) == 1:
                    (package/'chain').write_text('gates')
                return result
            stack.enter_context(patch('build_recipe.apply_overlay', side_effect=apply))
            for module, identity in [('build_recipe.build_containers','containers'),
                ('build_horse_trader_test.build','horses'),('build_debug_supplies.build','supplies'),
                ('build_rattay_smithery.build','smithery'),('build_smithing_voice.build','voice'),
                ('build_church_prayer.build','prayer'),('build_workshop_test.build','workshop')]:
                stack.enter_context(patch(module, side_effect=lambda *args, identity=identity, **kw: stage(identity,args[-1])))
            def gameplay(source, target, package, work):
                def failed(output):
                    raise ValueError('source dependency unresolved')
                return [(identity, identity, failed if fail and identity=='actors' else
                         lambda output, identity=identity: stage(identity,output)) for identity in STAGE_IDS]
            stack.enter_context(patch('setup_gameplay.steps', side_effect=gameplay))
            content = stack.enter_context(patch('setup_gameplay.validate', return_value={'actors':11, 'start_policy': POLICY}))
            streaming = stack.enter_context(patch('setup_streaming.validate', return_value={'proxies':1}))
            stack.enter_context(patch('setup_shaders.tool_root'))
            def shaders(target, output, *args):
                from shader_fixture import package_shaders
                (output/'package').mkdir(parents=True)
                package_shaders(output/'package')
                return {'compiled': True}
            stack.enter_context(patch('setup_shaders.build', side_effect=shaders))
            menu = stack.enter_context(patch('campaign_menu_stage.add_to_package'))
            if fail:
                with self.assertRaisesRegex(ValueError, 'source dependency'):
                    run(root/'source',root/'target',package,root/'work')
                self.assertEqual(verify(package)['build_recipe']['status'], 'building')
                content.assert_not_called(); streaming.assert_not_called(); menu.assert_not_called()
            else:
                report = run(root/'source',root/'target',package,root/'work')
                self.assertEqual(seen[-len(STAGE_IDS):], list(STAGE_IDS))
                require_current(verify(package))
                self.assertEqual(report['status'],'complete')
                self.assertEqual(report['shader_validation']['installation'],'mod_private_root')
                self.assertFalse((package/'Engine').exists())
                self.assertTrue((package/'ShaderCache/Engine/Shaders.pak').exists())
                self.assertFalse((package/'LaunchWithShaders.cmd').exists())
                self.assertIn('ShaderCache/shader-build.json', verify(package)['files'])
                self.assertEqual(report['shader_validation']['launcher'], 'setup')
                self.assertFalse((root/'work/shaders/package/Engine/Shaders.pak').exists())
                content.assert_called_once_with(package); streaming.assert_called_once_with(package, converted_data=None)
                menu.assert_called_once_with(root/'target',package)

    def test_stages_consume_previous_output_before_validating_and_registering_menu(self):
        self.exercise_recipe()

    def test_failed_campaign_stage_never_produces_complete_receipt_or_menu(self):
        self.exercise_recipe(fail=True)

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

    def test_consumed_overlay_does_not_retain_duplicate_archives(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); overlay = root/'overlay'; overlay.mkdir()
            (overlay/'asset.pak').write_bytes(b'converted')
            apply_overlay(root/'package', overlay, consume=True)
            self.assertFalse((overlay/'asset.pak').exists())
            self.assertEqual((root/'package/asset.pak').read_bytes(), b'converted')

    def test_cancel_and_completed_recipe_do_not_run_builders(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with patch('build_recipe.verify_package', return_value={'files': {}}), patch('build_open_test_gates.build') as gates, patch('setup_shaders.tool_root'):
                with self.assertRaises(InterruptedError):
                    run(root/'source', root/'target', root/'package', root/'work', cancelled=lambda: True)
                gates.assert_not_called()
            with patch('build_recipe.verify_package', return_value={'build_recipe': {'version': 1}}):
                with self.assertRaisesRegex(ValueError, 'already applied'):
                    run(root/'source', root/'target', root/'package', root/'other')
                self.assertFalse((root/'other').exists())


if __name__ == '__main__': unittest.main()
