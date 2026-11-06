"""Tile pool settings and the dense-tile estimate that routes tiles to the dense processes."""
import io
import json
import os
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import zipfile

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from world_surface_tiles import (_TileBaker, _bounded_setting, _placement_side, dense_split, dense_texture_cache, gpu_budget,
                                 gpu_free_memory, gpu_lanes, heavy_slots, select_backend, tile_workers, brick_threads, GIB, HEAVY_TRIANGLES)


class ParallelBakeSettingsTests(unittest.TestCase):
    def test_defaults_and_overrides_stay_within_bounds(self):
        with patch.dict(os.environ, {}, clear=False):
            for name in ('GLUEMAPPER_BAKE_TILE_WORKERS', 'GLUEMAPPER_GPU_LANES', 'GLUEMAPPER_BAKE_HEAVY_TILES'):
                os.environ.pop(name, None)
            plenty = 60 * GIB
            with patch('os.cpu_count', return_value=24):
                self.assertEqual(tile_workers(2, plenty), 6)   # 24 threads: 6 tiles x (2 bricks + 1)
                self.assertEqual(tile_workers(7, plenty), 3)
                # Memory bounds the pool: a 32 GB machine with 28 GB free runs 3 processes and 1 dense tile.
                self.assertEqual(tile_workers(2, 28 * GIB), 3)
                self.assertEqual(tile_workers(2, 8 * GIB), 1)   # never below one process
                # Without an explicit value the free memory is queried when the bake starts.
                with patch('world_surface_tiles.available_memory', return_value=None):
                    self.assertEqual(tile_workers(2, None), 6)  # unknown memory: CPU rule only
                    self.assertEqual(heavy_slots(None), 2)
                with patch('world_surface_tiles.available_memory', return_value=28 * GIB):
                    self.assertEqual((tile_workers(2), heavy_slots()), (3, 1))
                with patch('world_surface_tiles.available_memory', return_value=plenty):
                    self.assertEqual((tile_workers(2), heavy_slots()), (6, 2))
            with patch('os.cpu_count', return_value=2):
                self.assertEqual(tile_workers(2, plenty), 1)
            self.assertEqual(gpu_lanes(), 1)
            self.assertEqual(heavy_slots(plenty), 2)
            self.assertEqual(heavy_slots(28 * GIB), 1)
        with patch.dict(os.environ, {'GLUEMAPPER_BAKE_TILE_WORKERS': '12', 'GLUEMAPPER_BAKE_HEAVY_TILES': '3'}):
            self.assertEqual(tile_workers(2, 8 * GIB), 12)  # explicit settings win over the estimate
            self.assertEqual(heavy_slots(8 * GIB), 3)
        for value in ('0', '33', 'six', '-1', ''):
            with patch.dict(os.environ, {'GLUEMAPPER_BAKE_TILE_WORKERS': value}), self.assertRaises(ValueError):
                _bounded_setting('GLUEMAPPER_BAKE_TILE_WORKERS', 6, 1, 32)

    def test_brick_threads_fill_the_cores_memory_left_idle(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop('GLUEMAPPER_BAKE_BRICK_WORKERS', None)
            with patch('os.cpu_count', return_value=24):
                self.assertEqual(brick_threads(6), 4)    # plenty of memory: 6 processes x 4 threads
                self.assertEqual(brick_threads(4), 6)    # memory allowed only 4 processes
                self.assertEqual(brick_threads(1), 8)    # low-memory machine: one process, capped at the measured plateau
            with patch('os.cpu_count', return_value=8):
                self.assertEqual(brick_threads(1), 8)
                self.assertEqual(brick_threads(6), 2)    # never below the previous two
            with patch('os.cpu_count', return_value=None):
                self.assertEqual(brick_threads(1), 2)
        with patch.dict(os.environ, {'GLUEMAPPER_BAKE_BRICK_WORKERS': '16'}):
            self.assertEqual(brick_threads(6), 16)       # explicit setting wins, up to the rasterizer's limit
        for value in ('0', '17', 'many'):
            with patch.dict(os.environ, {'GLUEMAPPER_BAKE_BRICK_WORKERS': value}), self.assertRaises(ValueError):
                brick_threads(1)

    def test_triangle_estimate_reads_mesh_headers_only(self):
        with tempfile.TemporaryDirectory() as t:
            scene = Path(t); (scene / 'meshes').mkdir()
            sizes = {'house': 25_000, 'church': 1_200_000}
            for key, count in sizes.items():
                stream = io.BytesIO()
                # Only the header is read, so the array payload can be left out.
                np.lib.format.write_array_header_1_0(stream, {'descr': '<f4', 'fortran_order': False, 'shape': (count, 3, 3)})
                with zipfile.ZipFile(scene / 'meshes' / (key + '.npz'), 'w') as archive:
                    archive.writestr('triangles.npy', stream.getvalue())
            baker = SimpleNamespace(scene=scene, mesh_triangles={}, vegetation=None,
                                    records={'1': {'cache_key': 'house'}, '2': {'cache_key': 'house'}, '3': {'cache_key': 'church'}},
                                    plan={'vegetation': {'groups': {'0': {'cache_key': 'house'}}}})
            light = {'placements': ['1', '2']}; dense = {'placements': ['1', '3']}
            self.assertEqual(_TileBaker.estimated_triangles(baker, light), 50_000)
            self.assertLess(_TileBaker.estimated_triangles(baker, light), HEAVY_TRIANGLES)
            self.assertGreaterEqual(_TileBaker.estimated_triangles(baker, dense), HEAVY_TRIANGLES)
            baker.vegetation = (None, np.array([0, 0]))
            self.assertEqual(_TileBaker.estimated_triangles(baker, dict(light, vegetation=[0, 1])), 100_000)
            self.assertEqual(set(baker.mesh_triangles), set(sizes))  # each header read once

    def test_dense_tiles_use_optix_only_when_they_fit_the_gpu(self):
        large = 32 * GIB; small = 6 * GIB   # free GPU memory of a 32 GB and an 8 GB card
        self.assertEqual(gpu_budget(1, large), 31 * GIB)
        self.assertEqual(gpu_budget(2, large), 31 * GIB // 2)
        self.assertEqual(gpu_budget(1, GIB // 2), 0)
        self.assertEqual(select_backend('auto', 500_000, gpu_budget(1, small)), ('compiled', None))
        self.assertEqual(select_backend('auto', 2_000_000, gpu_budget(1, small)), ('optix', None))
        self.assertEqual(select_backend('auto', 18_600_000, gpu_budget(1, large)), ('optix', None))
        selected, reason = select_backend('auto', 18_600_000, gpu_budget(1, small))
        self.assertEqual(selected, 'compiled'); self.assertIn('GPU memory', reason)
        self.assertEqual(select_backend('auto', 18_600_000, None), ('optix', None))   # unknown memory: try, fall back
        for backend in ('compiled', 'cuda', 'optix'):   # an explicit backend is never rerouted
            self.assertEqual(select_backend(backend, 18_600_000, 0), (backend, None))

    def test_unknown_gpu_memory_is_none(self):
        with patch('ctypes.CDLL', side_effect=OSError('no NVIDIA driver')):
            self.assertIsNone(gpu_free_memory())
        free = gpu_free_memory()   # whatever this machine reports
        self.assertTrue(free is None or free >= 0)

    def test_partial_nvml_does_not_abort_bake(self):
        with patch('ctypes.CDLL', return_value=SimpleNamespace()):
            self.assertIsNone(gpu_free_memory())

    def test_nvml_uses_smallest_device_budget_and_shuts_down_on_query_failure(self):
        stopped = []
        def count(pointer):
            pointer._obj.value = 2
            return 0
        def handle(index, pointer):
            pointer._obj.value = index + 1
            return 0
        def memory(device, pointer):
            pointer._obj.free = (12 if device.value == 1 else 4) * GIB
            return 0
        nvml = SimpleNamespace(nvmlInit_v2=lambda: 0, nvmlShutdown=lambda: stopped.append(True),
                               nvmlDeviceGetCount_v2=count, nvmlDeviceGetHandleByIndex_v2=handle,
                               nvmlDeviceGetMemoryInfo=memory)
        with patch('ctypes.CDLL', return_value=nvml):
            self.assertEqual(gpu_free_memory(), 4 * GIB)
            nvml.nvmlDeviceGetMemoryInfo = lambda *args: 1
            self.assertIsNone(gpu_free_memory())
            self.assertEqual(len(stopped), 2)

    def test_dense_tiles_get_their_own_processes_within_the_memory_limited_count(self):
        mixed = [False, True, True, False]
        self.assertEqual(dense_split(mixed, 5, 1), (1, 4))   # the measured build: 5 processes, 1 dense slot
        self.assertEqual(dense_split(mixed, 6, 2), (2, 4))
        self.assertEqual(dense_split(mixed, 2, 2), (1, 1))   # light tiles always keep a process
        self.assertEqual(dense_split([False] * 3, 4, 1), (0, 4))
        self.assertEqual(dense_split([True] * 3, 4, 2), (2, 0))
        self.assertEqual(dense_split([True] * 3, 1, 2), (1, 0))

    def test_dense_texture_cache_scales_with_free_memory_and_stays_bounded(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop('GLUEMAPPER_BAKE_DENSE_TEXTURE_MB', None)
            self.assertEqual(dense_texture_cache(36 * GIB), 36 * GIB // 8)   # this machine at bake start
            self.assertEqual(dense_texture_cache(200 * GIB), 6 * GIB)
            self.assertEqual(dense_texture_cache(2 * GIB), 512 * 2**20)      # a 16 GB machine never drops below today's cache
            with patch('world_surface_tiles.available_memory', return_value=None):
                self.assertEqual(dense_texture_cache(), 4 * GIB)
        with patch.dict(os.environ, {'GLUEMAPPER_BAKE_DENSE_TEXTURE_MB': '1024'}):
            self.assertEqual(dense_texture_cache(200 * GIB), GIB)
        for value in ('0', '65537', 'lots'):
            with patch.dict(os.environ, {'GLUEMAPPER_BAKE_DENSE_TEXTURE_MB': value}), self.assertRaises(ValueError):
                dense_texture_cache(GIB)

    def test_placement_shortcut_matches_the_per_triangle_test(self):
        rng = np.random.default_rng(7)
        origin = [256, 512, 0]
        for case in range(400):
            tris = rng.uniform(-3, 3, (int(rng.integers(1, 40)), 3, 3))
            angle = rng.uniform(0, 6.3); c, s = np.cos(angle), np.sin(angle); scale = rng.uniform(.2, 3)
            # Positions around the tile, so inside, outside and straddling placements all occur.
            matrix = np.c_[np.array([[c, -s, 0], [s, c, 0], [0, 0, 1]]) * scale, rng.uniform(-30, 300, 3) + origin]
            flat = tris.reshape(-1, 3)
            side = _placement_side((flat.min(0), flat.max(0)), matrix.ravel(), origin)
            world = tris @ matrix[:, :3].T + matrix[:, 3]
            hit = np.all(world.max(1) >= origin, axis=1) & np.all(world.min(1) < np.asarray(origin) + 256, axis=1)
            if side is True: self.assertTrue(hit.all(), case)
            if side is False: self.assertFalse(hit.any(), case)
        box = (np.zeros(3), np.ones(3)); inside = [1, 0, 0, 300, 0, 1, 0, 600, 0, 0, 1, 10]
        self.assertTrue(_placement_side(box, inside, origin))
        self.assertFalse(_placement_side(box, [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0], origin))
        self.assertIsNone(_placement_side(box, [1, 0, 0, 255.5, 0, 1, 0, 600, 0, 0, 1, 10], origin))  # straddles
        # Anything the per-triangle path would reject is left to it, so its errors still surface.
        self.assertIsNone(_placement_side(None, inside, origin))
        self.assertIsNone(_placement_side(box, [0] * 12, origin))                     # singular
        self.assertIsNone(_placement_side(box, [float('nan')] + inside[1:], origin))
        self.assertIsNone(_placement_side(box, inside[:9], origin))


def empty_scene(root, tiles):
    """A valid scene of empty tiles with an empty asset root, baked by the real tile code."""
    from geometry_opacity import Assets
    scene = Path(root) / 'scene'; (scene / 'assets').mkdir(parents=True)
    plan = {'errors': {}, 'source_packages': {}, 'pak_root': str(scene / 'assets'), 'overrides': [],
            'pending_categories': [], 'tiles': [{'origin': [256 * i, 0, 0], 'placements': []} for i in range(tiles)]}
    assets = Assets(plan['pak_root'], plan['overrides']); plan['asset_catalog_digest'] = assets.catalog_digest(); assets.close()
    (scene / 'plan.json').write_text(json.dumps(plan)); (scene / 'placements.json').write_text('{}')
    return scene


class ParallelBakeCancellationTests(unittest.TestCase):
    def test_both_gpu_backends_take_a_lane_and_release_it_after_failure(self):
        class Lane:
            active = False
            entries = 0
            def __enter__(self):
                self.active = True; self.entries += 1
            def __exit__(self, *args):
                self.active = False

        for backend in ('cuda', 'optix', 'compiled'):
            with self.subTest(backend=backend), tempfile.TemporaryDirectory() as t:
                scene = empty_scene(t, 1)
                (scene / 'tiles').mkdir()
                lane = Lane()
                baker = _TileBaker(scene, None, 2, False, backend, 1, lanes=lane)
                def fail_raster(*args, **kwargs):
                    self.assertEqual(lane.active, backend in ('cuda', 'optix'))
                    raise RuntimeError('raster failed')
                try:
                    with patch('world_surface_tiles.build_tile', side_effect=fail_raster):
                        result = baker.bake(0, 1, baker.plan['tiles'][0])
                    self.assertEqual(result['status'], 'failed')
                    self.assertEqual(result['error'], 'raster failed')
                    self.assertFalse(lane.active)
                    self.assertEqual(lane.entries, int(backend in ('cuda', 'optix')))
                finally:
                    baker.assets.close()

    def test_parallel_bake_with_fewer_dense_slots_reports_in_plan_order(self):
        from world_surface_tiles import build
        settings = {'GLUEMAPPER_BAKE_TILE_WORKERS': '2', 'GLUEMAPPER_BAKE_HEAVY_TILES': '1'}
        with tempfile.TemporaryDirectory() as t, patch.dict(os.environ, settings):
            scene = empty_scene(t, 4)
            # Make submission order differ from plan order without constructing huge meshes.
            with patch('world_surface_tiles._TriangleEstimate.estimated_triangles', side_effect=[1_000_000, 1_000_000, 0, 0]):
                results = build(scene)
            self.assertEqual([r['origin'] for r in results], [tile['origin'] for tile in json.loads((scene / 'plan.json').read_text())['tiles']])
            self.assertTrue(all(r['status'] == 'built' for r in results))

    def test_cancellation_during_order_planning_starts_no_workers(self):
        from world_surface_tiles import build
        settings = {'GLUEMAPPER_BAKE_TILE_WORKERS': '2', 'GLUEMAPPER_BAKE_HEAVY_TILES': '1'}
        with tempfile.TemporaryDirectory() as t, patch.dict(os.environ, settings):
            scene = empty_scene(t, 4)
            messages = []
            with patch('world_surface_tiles._TriangleEstimate.estimated_triangles', return_value=0) as estimate, \
                 patch('world_surface_tiles.ProcessPoolExecutor') as pool:
                with self.assertRaises(InterruptedError):
                    build(scene, progress=lambda *args: messages.append(args), cancelled=lambda: bool(messages))
                self.assertEqual(estimate.call_count, 1)
                pool.assert_not_called()
            self.assertEqual(messages[0][:3], ('Plan lighting tile order', 0, 4))
            self.assertEqual(list((scene / 'tiles').glob('*.vox')), [])

    def test_a_cancelled_parallel_bake_starts_no_tile(self):
        from world_surface_tiles import build
        with tempfile.TemporaryDirectory() as t, patch.dict(os.environ, {'GLUEMAPPER_BAKE_TILE_WORKERS': '2'}):
            scene = empty_scene(t, 2)
            with self.assertRaises(InterruptedError):
                build(scene, cancelled=lambda: True)
            self.assertEqual(list((scene / 'tiles').glob('*.vox')), [])

    def test_cancelling_during_a_parallel_bake_starts_no_further_tile_and_keeps_finished_ones(self):
        from world_surface_tiles import build
        with tempfile.TemporaryDirectory() as t, patch.dict(os.environ, {'GLUEMAPPER_BAKE_TILE_WORKERS': '2'}):
            scene = empty_scene(t, 6)
            tiles = scene / 'tiles'
            with self.assertRaises(InterruptedError):
                build(scene, cancelled=lambda: any(tiles.glob('*.json')))  # cancel once a tile is recorded
            finished = list(tiles.glob('*.vox'))
            # Two processes hold one tile each, so at most the two started tiles finish.
            self.assertGreaterEqual(len(finished), 1); self.assertLessEqual(len(finished), 2)
            for vox in finished:
                self.assertEqual(json.loads(vox.with_suffix('.json').read_text())['status'], 'built')


if __name__ == '__main__':
    unittest.main()
