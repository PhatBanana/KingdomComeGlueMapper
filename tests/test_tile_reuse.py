"""Per-tile lighting reuse from the shared cache: a tile is reused only when everything it reads is unchanged."""
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
import zipfile

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from geometry_opacity import Assets
from setup_build_cache import Cache, fingerprint
from tile_reuse import IDENTITIES, recorded_bakes, reuse_cached, settings, tile_identities
from validate_world_surfaces import stem
from voxel_surfaces import build_tile
from world_surface_tiles import code_digest, gpu_configuration, tile_signature

MATERIAL = ('<Material><SubMaterials><Material Shader="Illum"><Textures>'
            '<Texture Map="Diffuse" File="{}"/></Textures></Material></SubMaterials></Material>')
EYE = [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0]


def pak(path, members):
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, 'w') as archive:
        for name, data in members.items(): archive.writestr(name, data)
    return path


def empty_tile(job):
    idx, vox, _ = build_tile(np.empty((0, 3, 3)), np.empty((0, 3, 2)), np.empty(0, np.int32), [],
                             tuple(job['origin']), allow_empty=True)
    return idx, vox


class TileReuseTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.root = Path(self.temp.name)
        self.data = self.root / 'game/Data'
        pak(self.data / 'base.pak', {'mat/wall.mtl': MATERIAL.format('tex/wall.dds'),
                                     'mat/roof.mtl': MATERIAL.format('tex/roof.dds'),
                                     'tex/wall.dds': b'wall', 'tex/roof.dds': b'roof'})
        self.cache = Cache(self.root / 'cache/lighting')

    def tearDown(self): self.temp.cleanup()

    def scene(self, name, *, overrides=(), roof=EYE, catalog=None):
        scene = self.root / name; (scene / 'meshes').mkdir(parents=True)
        if catalog is None:
            assets = Assets(self.data, [str(p) for p in overrides])
            catalog = assets.catalog_digest(); assets.close()
        for key, material in (('wall-mesh', 'mat/wall'), ('roof-mesh', 'mat/roof')):
            (scene / 'meshes' / (key + '.json')).write_text(json.dumps(
                {'key': key, 'bindings': [[material, 0]], 'triangles': 1, 'bounds': [[0, 0, 0], [1, 1, 1]]}))
        (scene / 'placements.json').write_text(json.dumps([
            {'mesh': 'wall.cgf', 'material': '', 'cache_key': 'wall-mesh', 'transform': EYE},
            {'mesh': 'roof.cgf', 'material': '', 'cache_key': 'roof-mesh', 'transform': roof}]))
        plan = {'pak_root': str(self.data), 'overrides': [str(p) for p in overrides], 'source_packages': {},
                'asset_catalog_digest': catalog, 'category_policy': {}, 'pending_categories': {}, 'errors': {},
                'tiles': [{'origin': [0, 0, 0], 'placements': [0]}, {'origin': [256, 0, 0], 'placements': [1]}]}
        (scene / 'plan.json').write_text(json.dumps(plan))
        return scene, plan

    def bake(self, name, scene, plan, *, only=None, identities=None, meta=None):
        """Bake a scene's tiles and publish them as setup_baking does: shards plus per-tile identities."""
        tiles, members = {}, {}
        for job in plan['tiles']:
            idx, vox = empty_tile(job)
            tiles[stem(job)] = idx + vox
            if only is None or stem(job) in only:
                members['terrain/svo/' + stem(job) + '.idx'] = idx; members['terrain/svo/' + stem(job) + '.vox'] = vox
        shard = pak(self.root / (name + '.pak'), members)
        if identities is None: identities = tile_identities(scene)
        metadata = dict(tiles=len(plan['tiles']), limitations=[], vegetation_gi_upgrade=None,
                        preset='buildings', level='map', **{IDENTITIES: identities})
        metadata.update(meta or {})
        payload = self.cache.publish(fingerprint(name), {'svo-part0.pak': shard}, metadata)
        return fingerprint(name), payload, tiles

    def reuse(self, scene, notes=None):
        notify = notes.append if notes is not None else (lambda message: None)
        return reuse_cached(scene, self.cache, 'buildings', 'map', notify=notify)

    def check_reused(self, scene, plan, expected, tiles=None):
        reports = {}
        for job in plan['tiles']:
            path = scene / 'tiles' / (stem(job) + '.json')
            if not path.exists(): continue
            report = json.loads(path.read_text()); reports[stem(job)] = report
            # The current scene's own signature: build() keeps it as a verified tile.
            self.assertEqual(report['signature'], tile_signature(code_digest(), plan['asset_catalog_digest'], plan, job,
                                                                 2, True, 'auto', gpu_configuration()))
            self.assertEqual((report['status'], report['origin'], report['vegetation_instances']), ('built', job['origin'], 0))
            data = (scene / 'tiles' / (stem(job) + '.idx')).read_bytes() + (scene / 'tiles' / (stem(job) + '.vox')).read_bytes()
            self.assertEqual(hashlib.sha256(data).hexdigest(), report['sha256'])
            if tiles is not None: self.assertEqual(data, tiles[stem(job)])
        self.assertEqual(sorted(reports), sorted(expected))
        return reports

    def test_unrelated_package_changes_keep_every_tile(self):
        reference, plan = self.scene('reference')
        key, _, tiles = self.bake('bake', reference, plan)
        # Quest/NPC members and a new catalog digest are not inputs of any tile.
        npcs = pak(self.root / 'package/npcs.pak', {'objects/npc.cgf': b'npc', 'tex/npc.dds': b'npc'})
        scene, plan = self.scene('scene', overrides=[npcs], catalog='other-catalog')
        result = self.reuse(scene)
        self.assertEqual((result['reused'], result['rebuild'], result['sources']), (2, 0, {key: 2}))
        reports = self.check_reused(scene, plan, [stem(j) for j in plan['tiles']], tiles)
        self.assertEqual(reports[stem(plan['tiles'][0])]['reuse']['cache_key'], key)
        self.assertEqual(json.loads((scene / 'tile-reuse.json').read_text())['reused_tiles'], sorted(tiles))

    def test_moved_brush_rebakes_only_its_tile(self):
        reference, plan = self.scene('reference')
        self.bake('bake', reference, plan)
        scene, plan = self.scene('scene', roof=[1, 0, 0, 0.5, 0, 1, 0, 0, 0, 0, 1, 0])
        result = self.reuse(scene)
        self.assertEqual(result['reused_tiles'], [stem(plan['tiles'][0])])
        self.check_reused(scene, plan, [stem(plan['tiles'][0])])
        self.assertFalse((scene / 'tiles' / (stem(plan['tiles'][1]) + '.idx')).exists())

    def test_changed_texture_or_new_split_piece_rebakes_tiles_that_read_it(self):
        reference, plan = self.scene('reference')
        self.bake('bake', reference, plan)
        for number, members in enumerate(({'tex/roof.dds': b'repainted roof'}, {'tex/roof.dds.1': b'top mip'})):
            with self.subTest(members=sorted(members)):
                patch_pak = pak(self.root / f'patch-{number}/p.pak', members)
                scene, plan = self.scene(f'scene-{number}', overrides=[patch_pak])
                self.assertEqual(self.reuse(scene)['reused_tiles'], [stem(plan['tiles'][0])])

    def test_changed_material_rebakes(self):
        reference, plan = self.scene('reference')
        self.bake('bake', reference, plan)
        patch_pak = pak(self.root / 'patch/p.pak', {'mat/wall.mtl': MATERIAL.format('tex/roof.dds')})
        scene, plan = self.scene('scene', overrides=[patch_pak])
        self.assertEqual(self.reuse(scene)['reused_tiles'], [stem(plan['tiles'][1])])

    def test_tiles_of_another_baker_or_other_settings_are_not_reused(self):
        reference, plan = self.scene('reference')
        with patch('tile_reuse.settings', return_value=dict(settings(), code='older baker')):
            self.bake('bake', reference, plan)
        scene, _ = self.scene('scene')
        self.assertEqual(self.reuse(scene)['reused'], 0)
        self.assertFalse(list((scene / 'tiles').iterdir()))

    def test_other_level_preset_legacy_or_changed_entries_are_skipped(self):
        reference, plan = self.scene('reference')
        self.bake('level', reference, plan, meta=dict(level='other'))
        self.bake('preset', reference, plan, meta=dict(preset='all'))
        legacy = dict(tiles=2, limitations=[], vegetation_gi_upgrade=None, scene_identity='x', preset='buildings', level='map')
        self.cache.publish(fingerprint('legacy'), {'svo-part0.pak': self.root / 'level.pak'}, legacy)
        key, payload, _ = self.bake('corrupt', reference, plan)
        (payload / 'svo-part0.pak').write_bytes(b'changed')
        self.assertEqual([k for k, _ in recorded_bakes(self.cache, 'buildings', 'map')], [key])
        scene, _ = self.scene('scene')
        notes = []
        self.assertEqual(self.reuse(scene, notes)['reused'], 0)
        self.assertTrue(any('changed payload' in note for note in notes), notes)
        self.assertFalse(list((scene / 'tiles').iterdir()))

    def test_resumed_tiles_of_this_scene_are_left_alone(self):
        reference, plan = self.scene('reference')
        self.bake('bake', reference, plan)
        first, second = (stem(j) for j in plan['tiles'])
        scene, plan = self.scene('scene')
        (scene / 'tiles').mkdir(); (scene / 'tiles' / (second + '.json')).write_text('{"status": "failed"}')
        result = self.reuse(scene)
        self.assertEqual(result['reused_tiles'], [first])
        self.assertEqual(json.loads((scene / 'tiles' / (second + '.json')).read_text()), {'status': 'failed'})

    def test_newest_bake_is_preferred_and_older_ones_fill_its_gaps(self):
        reference, plan = self.scene('reference')
        first, second = (stem(j) for j in plan['tiles'])
        old_key, _, _ = self.bake('old', reference, plan)
        identities = tile_identities(reference)
        new_key, _, _ = self.bake('new', reference, plan, only={first}, identities={first: identities[first]})
        for name, age in (('old', 200), ('new', 100)):
            pointer = self.cache.folder / (fingerprint(name) + '.json')
            os.utime(pointer, (pointer.stat().st_atime, pointer.stat().st_mtime - age))
        self.assertEqual([k for k, _ in recorded_bakes(self.cache, 'buildings', 'map')], [new_key, old_key])
        scene, plan = self.scene('scene')
        result = self.reuse(scene)
        self.assertEqual(result['sources'], {new_key: 1, old_key: 1})
        reports = self.check_reused(scene, plan, [first, second])
        self.assertEqual((reports[first]['reuse']['cache_key'], reports[second]['reuse']['cache_key']), (new_key, old_key))

    def test_without_recorded_bakes_nothing_is_read_or_written(self):
        scene, plan = self.scene('scene')
        notes = []
        result = self.reuse(scene, notes)
        self.assertEqual((result['reused'], result['rebuild']), (0, 2))
        self.assertIn('No earlier lighting bake', notes[0])
        self.assertFalse(list((scene / 'tiles').iterdir()))


if __name__ == '__main__':
    unittest.main()
