"""Background lighting bake: when it starts, how big it runs, and what the real bake gets back."""
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
import background_bake
from background_bake import GIB, processes, start, stop, wait


class BackgroundBakeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.root = Path(self.temp.name)
        self.package = self.root / 'travel'
        (self.package / 'Data/Levels/kcd1_travel').mkdir(parents=True)
        (self.package / 'Data/Levels/kcd1_travel/terrain.pak').write_bytes(b'')
        background_bake._process = None

    def tearDown(self):
        background_bake._process = None
        self.temp.cleanup()

    def start(self, mode='auto', preset='buildings', free=60 * GIB, cached=False):
        messages = []
        with patch.dict(os.environ, {background_bake.SETTING: mode}), \
                patch('bounded_pool.available_memory', return_value=free), \
                patch('background_bake._cached', return_value=cached), \
                patch('multiprocessing.context.SpawnProcess.start') as spawn, \
                patch('atexit.register'):
            result = start(self.package, [self.package / 'Data'], self.root / 'game', self.root / 'baking',
                           preset, messages.append)
        background_bake._process = None
        return result, spawn.called, messages

    def test_runs_only_where_it_fits_and_helps(self):
        self.assertTrue(self.start()[1])
        self.assertFalse(self.start(mode='0')[1])
        self.assertFalse(self.start(preset='none')[1])
        result, spawned, messages = self.start(free=20 * GIB)       # 16 GB-class machines keep the serial bake
        self.assertFalse(spawned); self.assertIn('GB free', messages[0])
        self.assertFalse(self.start(cached=True)[1])                # a cached bake on this PC is reused whole
        self.assertTrue(self.start(mode='1', free=20 * GIB, cached=True)[1])
        with patch.dict(os.environ, {background_bake.SETTING: 'sometimes'}), self.assertRaises(ValueError):
            start(self.package, [], self.root, self.root / 'baking', 'buildings')

    def test_tile_processes_leave_room_for_the_recipe(self):
        self.assertEqual(processes(45 * GIB), 3)   # 64 GB machine during combine
        self.assertEqual(processes(100 * GIB), 4)   # capped: pools size from memory free at the start
        self.assertEqual(processes(30 * GIB), 1)

    def test_needs_exactly_one_terrain_level(self):
        (self.package / 'Data/Levels/second').mkdir(); (self.package / 'Data/Levels/second/terrain.pak').write_bytes(b'')
        result, spawned, messages = self.start()
        self.assertFalse(spawned); self.assertIn('one converted terrain level', messages[0])

    def test_wait_returns_a_scene_only_when_one_exists(self):
        workspace = self.root / 'baking'
        self.assertIsNone(wait(workspace))
        scene = background_bake.folder(workspace) / 'scene'; (scene / 'tiles').mkdir(parents=True)
        self.assertIsNone(wait(workspace))
        (scene / 'plan.json').write_text('{}')
        (scene.parent / 'status.json').write_text(json.dumps({'status': 'stopped', 'error': 'cancelled'}))
        self.assertEqual(wait(workspace), scene)   # a partial bake still has useful tiles
        stop(workspace)                            # nothing running: no-op
        background_bake.cleanup(workspace)
        self.assertFalse(scene.exists())
        self.assertTrue((scene.parent / 'status.json').exists())  # kept for the build report


if __name__ == '__main__':
    unittest.main()
