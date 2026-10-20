"""Baked tiles are reused across plans only when the tile's own inputs are unchanged."""
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import zipfile

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
import world_surface_tiles


ARCHIVE = None  # set per test: a zip holding the material each fake mesh binds


class FakeAssets:
    def __init__(self, root, overrides):
        with zipfile.ZipFile(ARCHIVE) as archive:
            self.entries = {n: (ARCHIVE, n) for n in archive.namelist()}
    def catalog_digest(self): return 'assets-v1'
    def get(self, name):
        with zipfile.ZipFile(ARCHIVE) as archive: return archive.read(name)


def materials(path, **contents):
    with zipfile.ZipFile(path, 'w') as archive:
        for name, blob in contents.items(): archive.writestr(name+'.mtl', blob)


def scene(base, name, placements):
    root = base/name; (root/'meshes').mkdir(parents=True)
    tiles = [{'origin': [0, 0, 0], 'placements': list(range(len(placements)))}]
    (root/'plan.json').write_text(json.dumps(dict(errors={}, source_packages={}, asset_catalog_digest='assets-v1',
        pending_categories=[], tiles=tiles, pak_root='', overrides=[])))
    (root/'placements.json').write_text(json.dumps(placements))
    for key in {p['cache_key'] for p in placements}:
        (root/'meshes'/(key+'.json')).write_text(json.dumps({'bindings': [['m'+key, 0]]}))
        np.savez(root/'meshes'/(key+'.npz'), triangles=np.full((1, 3, 3), 10.0), uv=np.zeros((1, 3, 2)),
                 ids=np.zeros(1, dtype=np.int32))
    return root


def placement(key, x=0.0):
    return {'mesh': key+'.cgf', 'material': '', 'cache_key': key, 'transform': [1, 0, 0, x, 0, 1, 0, 0, 0, 0, 1, 0]}


class BakeTileCacheTests(unittest.TestCase):
    def setUp(self):
        global ARCHIVE
        self.base = Path(tempfile.mkdtemp()); self.rasterized = 0
        ARCHIVE = str(self.base/'assets.pak')
        materials(ARCHIVE, ma='<Material/>', mb='<Material/>')

    def fake_tile(self, triangles, *args, **kwargs):
        self.rasterized += 1
        return b'idx-%d' % len(triangles), b'vox', {'blocks': 1}

    def bake(self, root, cache=True):
        with patch.object(world_surface_tiles, 'Assets', FakeAssets), \
             patch.object(world_surface_tiles, 'load_surface', return_value=(SimpleNamespace(coverage=None), None)), \
             patch.object(world_surface_tiles, 'build_tile', self.fake_tile), \
             patch.object(world_surface_tiles, 'validate_pair', lambda idx, vox: None):
            return world_surface_tiles.build(root, tile_cache=self.base/'tile-cache' if cache else None)

    def test_unchanged_tile_is_reused_from_another_plan(self):
        first = self.bake(scene(self.base, 'one', [placement('a'), placement('b')]))
        # Same records in another order, as in a plan built from different packages.
        second = self.bake(scene(self.base, 'two', [placement('b'), placement('a')]))
        self.assertEqual(self.rasterized, 1)
        self.assertTrue(second[0]['reused_from_cache'])
        self.assertEqual(second[0]['sha256'], first[0]['sha256'])
        self.assertEqual((self.base/'two/tiles/0128_0128_0128_0256.idx').read_bytes(), b'idx-2')

    def test_moved_placement_rebuilds(self):
        self.bake(scene(self.base, 'one', [placement('a')]))
        result = self.bake(scene(self.base, 'moved', [placement('a', x=1.0)]))
        self.assertEqual(self.rasterized, 2)
        self.assertNotIn('reused_from_cache', result[0])

    def test_damaged_cache_entry_is_rejected_and_rebuilt(self):
        self.bake(scene(self.base, 'one', [placement('a')]))
        entry, = (self.base/'tile-cache').iterdir()
        (entry/'tile.vox').write_bytes(b'damaged')
        result = self.bake(scene(self.base, 'two', [placement('a')]))
        self.assertEqual(self.rasterized, 2)
        self.assertEqual(result[0]['status'], 'built')
        self.assertNotIn('reused_from_cache', result[0])
        # The rebuilt tile replaces the damaged entry, so the next plan reuses it.
        again = self.bake(scene(self.base, 'three', [placement('a')]))
        self.assertEqual(self.rasterized, 2)
        self.assertTrue(again[0]['reused_from_cache'])

    def test_changed_material_invalidates_only_tiles_that_use_it(self):
        self.bake(scene(self.base, 'one', [placement('a')]))
        self.bake(scene(self.base, 'two', [placement('b')]))
        materials(ARCHIVE, ma='<Material/>', mb='<Material Diffuse="0.5,0.5,0.5"/>')
        reused = self.bake(scene(self.base, 'three', [placement('a')]))
        rebuilt = self.bake(scene(self.base, 'four', [placement('b')]))
        self.assertEqual(self.rasterized, 3)
        self.assertTrue(reused[0]['reused_from_cache'])
        self.assertNotIn('reused_from_cache', rebuilt[0])
        self.assertIn('mb.mtl', rebuilt[0]['dependencies'])

    def test_without_a_cache_nothing_is_shared(self):
        self.bake(scene(self.base, 'one', [placement('a')]), cache=False)
        self.bake(scene(self.base, 'two', [placement('a')]), cache=False)
        self.assertEqual(self.rasterized, 2)


if __name__ == '__main__':
    unittest.main()
