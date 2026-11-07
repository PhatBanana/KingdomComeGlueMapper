"""Per-tile lighting reuse: a tile is reused only when everything it reads is unchanged."""
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
import zipfile

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from geometry_opacity import Assets
from tile_reuse import reuse, record_identities
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


class TileReuseTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.root = Path(self.temp.name)
        self.data = self.root / 'game/Data'
        pak(self.data / 'base.pak', {'mat/wall.mtl': MATERIAL.format('tex/wall.dds'),
                                     'mat/roof.mtl': MATERIAL.format('tex/roof.dds'),
                                     'tex/wall.dds': b'wall', 'tex/roof.dds': b'roof'})

    def tearDown(self): self.temp.cleanup()

    def scene(self, name, *, overrides=(), roof=EYE, catalog=None, built=False, code=None):
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
        if built:
            tiles = scene / 'tiles'; tiles.mkdir()
            for job in plan['tiles']:
                idx, vox, _ = build_tile(np.empty((0, 3, 3)), np.empty((0, 3, 2)), np.empty(0, np.int32), [],
                                         tuple(job['origin']), allow_empty=True)
                (tiles / (stem(job) + '.idx')).write_bytes(idx); (tiles / (stem(job) + '.vox')).write_bytes(vox)
                signature = tile_signature(code or code_digest(), catalog, plan, job, 2, True, 'auto', gpu_configuration())
                (tiles / (stem(job) + '.json')).write_text(json.dumps(
                    {'status': 'built', 'origin': job['origin'], 'signature': signature,
                     'sha256': hashlib.sha256(idx + vox).hexdigest()}))
        return scene, plan

    def check_reused(self, scene, plan, expected):
        reports = {}
        for job in plan['tiles']:
            path = scene / 'tiles' / (stem(job) + '.json')
            if not path.exists(): continue
            report = json.loads(path.read_text()); reports[stem(job)] = report
            # The current scene's own signature: build() keeps it as a verified tile.
            self.assertEqual(report['signature'], tile_signature(code_digest(), plan['asset_catalog_digest'], plan, job,
                                                                 2, True, 'auto', gpu_configuration()))
            data = (scene / 'tiles' / (stem(job) + '.idx')).read_bytes() + (scene / 'tiles' / (stem(job) + '.vox')).read_bytes()
            self.assertEqual(hashlib.sha256(data).hexdigest(), report['sha256'])
        self.assertEqual(sorted(reports), sorted(expected))

    def test_unrelated_package_changes_keep_every_tile(self):
        reference, _ = self.scene('reference', built=True)
        # Quest/NPC members and a new catalog digest are not inputs of any tile.
        npcs = pak(self.root / 'package/npcs.pak', {'objects/npc.cgf': b'npc', 'tex/npc.dds': b'npc'})
        scene, plan = self.scene('scene', overrides=[npcs], catalog='other-catalog')
        result = reuse(scene, reference)
        self.assertEqual((result['reused'], result['rebuild']), (2, 0))
        self.check_reused(scene, plan, [stem(j) for j in plan['tiles']])

    def test_moved_brush_rebakes_only_its_tile(self):
        reference, _ = self.scene('reference', built=True)
        scene, plan = self.scene('scene', roof=[1, 0, 0, 0.5, 0, 1, 0, 0, 0, 0, 1, 0])
        result = reuse(scene, reference)
        self.assertEqual(result['reused_tiles'], [stem(plan['tiles'][0])])
        self.assertEqual(result['changed'], [stem(plan['tiles'][1])])
        self.check_reused(scene, plan, [stem(plan['tiles'][0])])

    def test_changed_texture_or_new_split_piece_rebakes_tiles_that_read_it(self):
        reference, _ = self.scene('reference', built=True)
        for number, members in enumerate(({'tex/roof.dds': b'repainted roof'}, {'tex/roof.dds.1': b'top mip'})):
            with self.subTest(members=sorted(members)):
                patch = pak(self.root / f'patch-{number}/p.pak', members)
                scene, plan = self.scene(f'scene-{number}', overrides=[patch])
                self.assertEqual(reuse(scene, reference)['reused_tiles'], [stem(plan['tiles'][0])])

    def test_changed_material_rebakes(self):
        reference, _ = self.scene('reference', built=True)
        patch = pak(self.root / 'patch/p.pak', {'mat/wall.mtl': MATERIAL.format('tex/roof.dds')})
        scene, plan = self.scene('scene', overrides=[patch])
        self.assertEqual(reuse(scene, reference)['reused_tiles'], [stem(plan['tiles'][1])])

    def test_tiles_of_another_baker_are_not_reused(self):
        reference, _ = self.scene('reference', built=True, code='older-baker')
        scene, _ = self.scene('scene')
        self.assertEqual(reuse(scene, reference)['reused'], 0)

    def test_changed_reference_bytes_and_own_tiles_are_left_alone(self):
        reference, plan = self.scene('reference', built=True)
        first, second = (stem(j) for j in plan['tiles'])
        (reference / 'tiles' / (first + '.vox')).write_bytes(b'corrupt')
        scene, _ = self.scene('scene')
        (scene / 'tiles').mkdir(); (scene / 'tiles' / (second + '.json')).write_text('{"status": "failed"}')
        result = reuse(scene, reference)
        self.assertEqual(result['reused'], 0)
        self.assertEqual(json.loads((scene / 'tiles' / (second + '.json')).read_text()), {'status': 'failed'})

    def test_reference_whose_archives_changed_after_its_plan_is_refused(self):
        reference, _ = self.scene('reference', built=True)
        # Tiles were baked from the old bytes; identities read now would describe the new ones.
        pak(self.data / 'base.pak', {'mat/wall.mtl': MATERIAL.format('tex/wall.dds'),
                                     'mat/roof.mtl': MATERIAL.format('tex/roof.dds'),
                                     'tex/wall.dds': b'new wall', 'tex/roof.dds': b'roof'})
        scene, _ = self.scene('scene')
        with self.assertRaisesRegex(ValueError, 'assets changed'):
            reuse(scene, reference)

    def test_recorded_identities_match_recomputed_ones(self):
        reference, _ = self.scene('reference', built=True)
        recorded = record_identities(reference)
        scene, _ = self.scene('scene')
        self.assertEqual(reuse(scene, reference)['reused'], 2)
        self.assertEqual(json.loads((reference / 'tile-identities.json').read_text()), recorded)


if __name__ == '__main__':
    unittest.main()
