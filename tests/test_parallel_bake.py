"""Tile pool settings and the dense-tile estimate that gates the heavy slots."""
import io
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
from world_surface_tiles import _TileBaker, _bounded_setting, gpu_lanes, heavy_slots, tile_workers, GIB, HEAVY_TRIANGLES


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
                self.assertEqual(tile_workers(2, None), 6)      # unknown memory: CPU rule only
            with patch('os.cpu_count', return_value=2):
                self.assertEqual(tile_workers(2, plenty), 1)
            self.assertEqual(gpu_lanes(), 1)
            self.assertEqual(heavy_slots(plenty), 2)
            self.assertEqual(heavy_slots(28 * GIB), 1)
            self.assertEqual(heavy_slots(None), 2)
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


if __name__ == '__main__':
    unittest.main()
