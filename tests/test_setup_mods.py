import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from setup_mods import checked_config,verify_fishing,install_fishing,worker
from setup_campaign import digest
from setup_fishing import RECEIPT,MOD_ID
from desktop_setup import Cancelled


class ModSetupTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
        self.game=self.root/'game';self.game.mkdir()
        self.package=self.make_package(self.root/'package','new')
        self.running=patch('setup_mods.legacy.game_running',return_value=False);self.running.start()

    def tearDown(self):self.running.stop();self.temp.cleanup()

    def make_package(self,path,value):
        (path/'Data').mkdir(parents=True)
        (path/'Data/fishing.pak').write_text(value)
        (path/'mod.manifest').write_text('<kcd_mod/>')
        files={p.relative_to(path).as_posix():digest(p) for p in path.rglob('*') if p.is_file()}
        (path/RECEIPT).write_text(json.dumps(dict(schema=1,owner=MOD_ID,files=files)))
        return path

    def test_fishing_does_not_require_kcd1_selection(self):
        c=checked_config(dict(mods=['fishing'],kcd2='game',workspace='builds',action='build_only'))
        self.assertEqual(c['kcd1'],'')
        with self.assertRaises(ValueError):checked_config(dict(c,mods=['map']))
        with self.assertRaises(ValueError):checked_config(dict(c,mods=['unknown']))
        with self.assertRaises(ValueError):checked_config(dict(c,mods=['fishing','fishing']))

    def test_map_failure_surfaces_child_error_without_installing(self):
        job = self.root/'job';job.mkdir()
        config = dict(mods=['map'],kcd1='source',kcd2='target',workspace=str(self.root),action='build_install')
        path = job/'job.json';path.write_text(json.dumps(config))
        def failed(child):
            (child.parent/'events.jsonl').write_text(json.dumps(dict(kind='error',message='Specific converter failure'))+'\n')
            return 1
        with patch('setup_mods.preflight'), patch('setup_mods.legacy.worker',side_effect=failed), patch('setup_mods.legacy.install_transaction') as install:
            self.assertEqual(worker(path),1)
            install.assert_not_called()
        events = [json.loads(line) for line in (job/'events.jsonl').read_text().splitlines()]
        self.assertIn('Specific converter failure', events[-1]['message'])

    def test_tamper_extra_file_and_traversal_blocked(self):
        (self.package/'Data/fishing.pak').write_text('tampered')
        with self.assertRaises(ValueError):verify_fishing(self.package)
        r=json.loads((self.package/RECEIPT).read_text());r['files']={'../outside':'bad'}
        (self.package/RECEIPT).write_text(json.dumps(r))
        with self.assertRaises(ValueError):verify_fishing(self.package)

    def test_install_preserves_mods_and_order_and_backs_up(self):
        old=self.make_package(self.game/'Mods'/MOD_ID,'old')
        sibling=self.game/'Mods/unrelated';sibling.mkdir();(sibling/'keep.txt').write_text('keep')
        order=self.game/'Mods/mod_order.txt';order.write_text('# keep comment\nunrelated\nkingdomcomegluemapper\n')
        result=install_fishing(self.package,self.game,lambda *a:None,lambda:False)
        self.assertEqual((old/'Data/fishing.pak').read_text(),'new')
        self.assertEqual((Path(result['backup'])/MOD_ID/'Data/fishing.pak').read_text(),'old')
        self.assertEqual((sibling/'keep.txt').read_text(),'keep')
        self.assertEqual(order.read_text().splitlines()[-1],MOD_ID)
        self.assertIn('# keep comment',order.read_text())

    def test_cancel_keeps_old_install(self):
        old=self.make_package(self.game/'Mods'/MOD_ID,'old')
        with self.assertRaises(Cancelled):install_fishing(self.package,self.game,lambda *a:None,lambda:True)
        self.assertEqual((old/'Data/fishing.pak').read_text(),'old')

    def test_failed_final_order_replace_rolls_back(self):
        old=self.make_package(self.game/'Mods'/MOD_ID,'old')
        order=self.game/'Mods/mod_order.txt';order.write_text('unrelated\n')
        with patch.object(Path,'replace',side_effect=OSError('injected failure')):
            with self.assertRaises(OSError):install_fishing(self.package,self.game,lambda *a:None,lambda:False)
        self.assertEqual((old/'Data/fishing.pak').read_text(),'old')
        self.assertEqual(order.read_text(),'unrelated\n')

    def test_running_game_blocks_install(self):
        with patch('setup_mods.legacy.game_running',return_value=True):
            with self.assertRaises(ValueError):install_fishing(self.package,self.game,lambda *a:None,lambda:False)


if __name__=='__main__':unittest.main()
