import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
import setup_resume as resume
import setup_mods


class ResumeTests(unittest.TestCase):
    def config(self,root):
        return dict(mods=['map'],action='build_install',kcd1='source',kcd2='target',workspace=str(root),package='',baking='all',cutscenes='none')

    def test_failed_bake_resumes_without_rebuilding_map_or_replaying_cancel(self):
        with tempfile.TemporaryDirectory() as t:
            root=Path(t);(root/'job.json').write_text(json.dumps(self.config(root)))
            def converted(path):
                (Path(path).parent/'package').mkdir();return 0
            with patch('setup_mods.preflight'),patch('setup_mods.legacy.worker',side_effect=converted),patch('setup_mods.bake_package',side_effect=ValueError('bad mesh')):
                self.assertEqual(setup_mods.worker(root/'job.json'),1)
            original=(root/'events.jsonl').read_bytes()
            (root/'cancel.requested').touch()
            attempt=root/'resume-1';attempt.mkdir()
            (attempt/'job.json').write_text(json.dumps(resume.load_job(root)))
            with patch('setup_resume.preflight'),patch('setup_resume.map_receipt',return_value={'build_recipe':{'status':'complete'}}),patch('setup_mods.legacy.worker') as convert,patch('setup_mods.bake_package') as bake,patch('setup_mods.legacy.install_transaction') as install:
                self.assertEqual(setup_mods.worker(attempt/'job.json'),0)
                convert.assert_not_called();install.assert_called_once()
                self.assertEqual(bake.call_args.args[0],root/'package/map')
                self.assertEqual(bake.call_args.args[2],root/'baking')
            self.assertEqual((root/'events.jsonl').read_bytes(),original)

    def test_saved_options_come_from_original_job_even_when_resuming_attempt(self):
        with tempfile.TemporaryDirectory() as t:
            root=Path(t);(root/'job.json').write_text(json.dumps(self.config(root)))
            attempt=root/'resume-1';attempt.mkdir()
            (attempt/'job.json').write_text(json.dumps(dict(resume_from=str(root),baking='none')))
            self.assertEqual(resume.load_job(attempt)['baking'],'all')

    def test_changed_package_blocks_resume_before_bake_or_install(self):
        with tempfile.TemporaryDirectory() as t:
            root=Path(t);(root/'job.json').write_text(json.dumps(self.config(root)))
            attempt=root/'resume-1';attempt.mkdir();(attempt/'job.json').write_text(json.dumps(resume.load_job(root)))
            with patch('setup_resume.map_receipt',side_effect=ValueError('Package changed')),patch('setup_mods.bake_package') as bake,patch('setup_mods.legacy.install_transaction') as install:
                self.assertEqual(setup_mods.worker(attempt/'job.json'),1)
                bake.assert_not_called();install.assert_not_called()

    def test_completed_bake_is_not_repeated(self):
        with tempfile.TemporaryDirectory() as t:
            root=Path(t);(root/'job.json').write_text(json.dumps(self.config(root)))
            attempt=root/'resume-1';attempt.mkdir();(attempt/'job.json').write_text(json.dumps(resume.load_job(root)))
            with patch('setup_resume.preflight'),patch('setup_resume.map_receipt',return_value={'baking':{'preset':'all'}}),patch('setup_mods.legacy.worker') as convert,patch('setup_mods.bake_package') as bake,patch('setup_mods.legacy.install_transaction') as install:
                self.assertEqual(setup_mods.worker(attempt/'job.json'),0)
                convert.assert_not_called();bake.assert_not_called();install.assert_called_once()

    def test_legacy_upgrade_runs_after_checkpoint_bake_before_install(self):
        for baked in (False,True):
            with self.subTest(baked=baked),tempfile.TemporaryDirectory() as t:
                root=Path(t);(root/'job.json').write_text(json.dumps(self.config(root)))
                attempt=root/'resume-1';attempt.mkdir()
                (attempt/'job.json').write_text(json.dumps(resume.load_job(root)))
                saved={'travel_bridge':{'destination':'kcd1_travel'},'build_recipe':{'version':3}}
                if baked:saved['baking']={'preset':'all'}
                calls=[]
                with patch('setup_resume.preflight'),patch('setup_resume.map_receipt',return_value=saved),patch('setup_mods.legacy.worker') as convert,patch('setup_mods.bake_package',side_effect=lambda *a:calls.append('bake')),patch('setup_resume.update_private_package',side_effect=lambda *a:calls.append('upgrade')) as upgrade,patch('setup_mods.legacy.install_transaction',side_effect=lambda *a:calls.append('install')):
                    self.assertEqual(setup_mods.worker(attempt/'job.json'),0)
                    self.assertEqual(calls,(['bake'] if not baked else [])+['upgrade','install'])
                    convert.assert_not_called()
                    self.assertEqual(upgrade.call_args.args[0],root/'package/map')
                    from setup_package_upgrade import finalize
                    self.assertIs(upgrade.call_args.args[1],finalize)

    def test_atomic_swap_recovery_and_job_lock(self):
        with tempfile.TemporaryDirectory() as t:
            root=Path(t);previous=root/'map-before-bake';previous.mkdir();(previous/'receipt').write_text('good')
            resume.restore_swap(root/'map')
            self.assertEqual((root/'map/receipt').read_text(),'good')
            with resume.job_lock(root):
                with self.assertRaises(ValueError):
                    with resume.job_lock(root):pass
            with resume.job_lock(root):pass

    def test_failed_optional_update_does_not_modify_original_hardlinks(self):
        with tempfile.TemporaryDirectory() as t:
            package=Path(t)/'map';package.mkdir();(package/'asset').write_bytes(b'original')
            def failed(staged):
                pending=staged/'new';pending.write_bytes(b'changed');pending.replace(staged/'asset')
                raise ValueError('failed after preparing one replacement')
            with self.assertRaises(ValueError):resume.update_private_package(package,failed,lambda:False)
            self.assertEqual((package/'asset').read_bytes(),b'original')

    def test_ui_resume_reopens_original_job_and_starts_separate_attempt(self):
        import setup_web
        from unittest.mock import MagicMock
        with tempfile.TemporaryDirectory() as t:
            root=Path(t);(root/'job.json').write_text(json.dumps(self.config(root)))
            (root/'package/map').mkdir(parents=True)
            api=setup_web.SetupAPI();api._window=MagicMock()
            api._window.create_file_dialog.return_value=[str(root)]
            with patch('setup_web.subprocess.Popen') as process:
                result=api.resume()
                self.assertTrue(result['ok']);process.assert_called_once()
                attempt=Path(result['job'])
                self.assertEqual(attempt.parent,root)
                self.assertEqual(json.loads((attempt/'job.json').read_text())['resume_from'],str(root))
                self.assertEqual(result['steps'][0],'Verify saved work')
                self.assertIn('KCD1 Map · All (Forest) lighting bake',result['steps'])
                self.assertNotIn('Terrain and original materials',result['steps'])


if __name__=='__main__':unittest.main()
