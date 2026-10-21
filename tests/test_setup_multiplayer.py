"""Setup integration contracts; never launch the real game or server."""
import json
import os
from pathlib import Path
import sys
import tempfile
import tomllib
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
import setup_multiplayer as mp
from setup_mods import checked_config, worker
from setup_web import SetupAPI, planned_steps


class MultiplayerSetupTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name).resolve()

    def config(self,**changes):
        return dict(mods=['mp'],kcd2=str(self.root/'game'),workspace=str(self.root),
                    action='build_only',**changes)

    def profile(self):
        folder=self.root/'profile';server=folder/'server-profile';server.mkdir(parents=True)
        template=(mp.builder.PROJECT_ROOT/'templates/server.toml.template').read_text()
        for key in ('X','Y','Z','YAW'):template=template.replace('@@SPAWN_'+key+'@@','1')
        (server/'server.kcd1-map-only.toml').write_text(template)
        return dict(output=str(folder),server_profile=str(server),game=str(self.root/'game'),
                    client='client',server='server',name='Player',host='127.0.0.1:7777')

    def test_mp_only_needs_no_kcd1_or_shader_compiler_or_bake(self):
        c=checked_config(self.config(baking='all',rebuild_cache=True))
        self.assertEqual(c['baking'],'none');self.assertFalse(c['rebuild_cache'])
        self.assertEqual(c['kcd1'],'');self.assertEqual(planned_steps(c),['KCD1:MP'])
        both=dict(c,mods=['map','mp'],kcd1='source',baking='all',rebuild_cache=True)
        self.assertTrue(checked_config(both)['rebuild_cache'])
        self.assertEqual(planned_steps(both)[-1],'KCD1:MP')

    def test_conflicting_fishing_selection_rejected(self):
        with self.assertRaisesRegex(ValueError,'Fishing'):
            checked_config(dict(self.config(),mods=['mp','fishing']))

    def test_invalid_settings_rejected_before_writing(self):
        for change in ({'mp_port':0},{'mp_port':True},{'mp_max_players':999},
            {'mp_host':'server:65536'},{'mp_player':'x --map bad'},
            {'mp_time':'24:00'},{'mp_time_ratio':float('nan')},{'mp_pvp':'false'},
            {'mp_password':'bad password'},{'mp_server_name':'x\n[server]'}):
            with self.subTest(change=change),self.assertRaises(ValueError):mp.settings(change)

    def test_settings_roundtrip_keeps_map_and_validation_contract(self):
        p=self.profile()
        values=dict(mp_server_name='KCD1:MP "Friends"',mp_port=8123,mp_max_players=8,
            mp_password='a-token',mp_pvp=True,mp_time='19:45',mp_time_ratio=2.5,
            mp_host='example.test:8123',mp_player='Henry')
        mp.configure(p,values)
        parsed=tomllib.loads((Path(p['server_profile'])/'server.kcd1-map-only.toml').read_text())
        self.assertEqual(parsed['server']['name'],values['mp_server_name'])
        self.assertEqual(parsed['server']['port'],8123)
        self.assertEqual(parsed['server']['max_players'],8)
        self.assertEqual(parsed['server']['password'],'a-token')
        self.assertEqual(parsed['server']['level'],'kcd1_travel')
        self.assertEqual(parsed['world']['time'],'19:45');self.assertEqual(parsed['world']['time_ratio'],2.5)
        self.assertTrue(parsed['combat']['pvp']);self.assertEqual(parsed['master']['url'],'')
        self.assertEqual(parsed['validation']['navmesh'],'')
        saved=json.loads((Path(p['output'])/'profile.json').read_text())
        self.assertEqual(saved['host'],'example.test:8123');self.assertEqual(saved['token'],'a-token')

    def test_source_resolution_accepts_job_collection_or_map_not_cache(self):
        source=self.root/'job/package/map';source.mkdir(parents=True)
        (source/'mod.manifest').write_text('test')
        for candidate in (source,source.parent,source.parent.parent):
            self.assertEqual(mp.resolve_source(str(candidate),'unused'),source)
        with self.assertRaisesRegex(ValueError,'cache alone'):
            mp.resolve_source(str(self.root/'cache'),'unused')

    def test_find_sources_excludes_in_progress_jobs(self):
        for name,kind in (('done','done'),('running','stage'),('failed','error')):
            folder=self.root/name;(folder/'package/map').mkdir(parents=True)
            (folder/'package/map/mod.manifest').write_text('test')
            (folder/'events.jsonl').write_text(json.dumps(dict(kind=kind))+'\n')
        self.assertEqual([r['label'] for r in mp.sources(self.root,self.root/'game')],['done'])

    def test_client_uses_prepared_runtime_and_argv_token(self):
        p=self.profile();p['token']='secret-token'
        argv=['launcher.exe','--game',p['game'],'--name','Player','--connect',p['host']]
        with patch.object(mp.bridge,'launch_spec',return_value=(argv,Path('client'),{})), \
             patch('setup_launch.launch',return_value={'root':'private runtime'}) as prepare:
            args,cwd,env=mp.launch_spec(p,'client')
        prepare.assert_called_once_with(p['game'],prepare_only=True,mod_id=mp.MOD_ID)
        self.assertEqual(args[2],'private runtime');self.assertEqual(args[-2:],['--token','secret-token'])
        self.assertEqual(env['SteamAppId'],'1771300')

    def test_server_does_not_prepare_or_require_game_runtime(self):
        p=self.profile();expected=(['server.exe'],Path('server-profile'),{})
        with patch.object(mp.bridge,'launch_spec',return_value=expected),patch('setup_launch.launch') as prepare:
            self.assertEqual(mp.launch_spec(p,'server'),expected)
        prepare.assert_not_called()

    def test_worker_exports_after_shared_cache_environment_without_map_rebuild(self):
        c=checked_config(self.config());job=self.root/'job';job.mkdir()
        path=job/'job.json';path.write_text(json.dumps(c))
        def export(config,package,notify,cancelled):
            self.assertEqual(os.environ['GLUEMAPPER_BUILD_CACHE'],str(self.root/'cache'))
            self.assertEqual(package,job/'package');return str(package/'mp/profile.json')
        with patch('setup_mods.preflight'),patch.object(mp,'run',side_effect=export) as run, \
             patch('setup_mods.legacy.worker',side_effect=AssertionError('Unexpected world rebuild')):
            self.assertEqual(worker(path),0)
        run.assert_called_once()
        event=json.loads((job/'events.jsonl').read_text().splitlines()[-1])
        self.assertEqual(event['kind'],'done');self.assertTrue(event['mp_profile'].endswith('profile.json'))

    def test_api_blocks_launch_and_does_not_stop_unowned_server(self):
        api=SetupAPI();api._process=Mock();api._process.poll.return_value=None
        with patch.object(mp,'start_process') as start:
            self.assertFalse(api.multiplayer('client',{})['ok']);start.assert_not_called()
        api._process=None
        self.assertIn('No server started',api.multiplayer('stop_server',{})['error'])
        self.assertFalse(api._busy())

    def test_singleplayer_launch_refuses_active_mp_profile(self):
        game=self.root/'game';mod=game/'Mods/kingdomcomegluemapper'
        (mod/'ShaderCache').mkdir(parents=True);(mod/'mod.manifest').write_text('fixture')
        (mod/'ShaderCache/shader-build.json').write_text('{}')
        (game/'.gluemapper-kcdmp').mkdir();(game/'.gluemapper-kcdmp/active.json').write_text('{}')
        from setup_launch import launch
        with patch('setup_launch.subprocess.run') as run:
            with self.assertRaisesRegex(ValueError,'Restore single-player'):launch(str(game))
            run.assert_not_called()


if __name__=='__main__':unittest.main()
