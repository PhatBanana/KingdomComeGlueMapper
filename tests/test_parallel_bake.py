"""Tile pool settings and the dense-tile estimate that gates the heavy slots."""
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
from world_surface_tiles import _TileBaker, _bounded_setting, gpu_lanes, heavy_slots, interleaved, tile_workers, GIB, HEAVY_TRIANGLES


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

    def test_dense_tiles_are_spread_through_the_submission_order(self):
        # Plan order clusters a town's dense tiles; submission spreads them, each kind in plan order.
        dense = [False, True, True, True, False, False, False, False, False]
        order = interleaved(dense)
        self.assertEqual(sorted(order), list(range(len(dense))))
        self.assertEqual([i for i in order if dense[i]], [1, 2, 3])
        self.assertEqual([i for i in order if not dense[i]], [0, 4, 5, 6, 7, 8])
        positions = [order.index(i) for i in (1, 2, 3)]
        self.assertTrue(all(b - a >= 2 for a, b in zip(positions, positions[1:])))
        self.assertEqual(interleaved([False] * 4), [0, 1, 2, 3])  # nothing dense: plan order
        self.assertEqual(interleaved([True] * 3), [0, 1, 2])
        self.assertEqual(interleaved([]), [])


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
