"""Ordered, bounded worker pools keep serial output and limit queued inputs."""
import operator
import os
from pathlib import Path
import sys
import unittest
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from bounded_pool import ordered_map, worker_count  # noqa: E402

KCD1 = Path(os.environ.get('GLUEMAPPER_KCD1', r'C:\Program Files (x86)\Steam\steamapps\common\KingdomComeDeliverance'))


class BoundedPoolTests(unittest.TestCase):
    def test_parallel_results_match_serial_order(self):
        items = list(range(-40, 40))
        self.assertEqual(list(ordered_map(operator.neg, items, 4)), [operator.neg(i) for i in items])
        self.assertEqual(list(ordered_map(operator.neg, items, 1)), [operator.neg(i) for i in items])

    def test_inputs_are_pulled_only_as_slots_free(self):
        pulled = []
        def items():
            for i in range(50):
                pulled.append(i)
                yield i
        for done, _ in enumerate(ordered_map(operator.neg, items(), 3, window=2), 1):
            self.assertLessEqual(len(pulled) - done, 3 * 2)

    def test_worker_count_respects_memory_jobs_and_override(self):
        self.assertEqual(worker_count(1, 1), 1)
        self.assertEqual(worker_count(64, 1 << 60), 1)
        os.environ['GLUEMAPPER_TEST_WORKERS'] = '3'
        try:
            self.assertEqual(worker_count(64, 1 << 60, 'GLUEMAPPER_TEST_WORKERS'), 3)
        finally:
            del os.environ['GLUEMAPPER_TEST_WORKERS']

    def test_setup_pool_self_test_runs_real_workers(self):
        from setup_app import pool_self_test
        self.assertEqual(pool_self_test()['status'], 'passed')

    def test_deferred_clothing_bakes_preserve_inputs_and_staged_payloads(self):
        from contextlib import ExitStack
        import tempfile
        from types import SimpleNamespace
        from unittest.mock import patch
        import xml.etree.ElementTree as ET
        from PIL import Image
        from character_native_materials import bake_float_dds
        from static_assets import StagedAssets
        from world_item_clothing import ClothingAdapter

        with tempfile.TemporaryDirectory() as temporary, ExitStack() as stack:
            root = Path(temporary)
            staged = root / 'staged'; staged.mkdir()
            adapter = object.__new__(ClothingAdapter)
            adapter.assets = SimpleNamespace(emitted=StagedAssets(staged))
            adapter.stack, adapter.defer, adapter.pool = stack, True, None
            from collections import deque
            adapter.pending = deque()
            names, expected = [], {}
            with patch('world_item_clothing.worker_count', return_value=2):
                # The temporary material directory can go away before finish().
                with tempfile.TemporaryDirectory(dir=root) as material_directory:
                    folder = Path(material_directory)
                    bake = adapter.deferred_bake(folder, names)
                    for index in range(7):
                        image = Image.new('RGBA', (8, 8), (20 + index * 25, 128, 50, 255))
                        material = ET.Element('Material', Diffuse='.7,.8,.9')
                        specular = Image.new('RGBA', (8, 8), (40, 80, 120, 255))
                        serial = root / f'serial-{index}.dds'
                        bake_float_dds(serial, image, material, specular)
                        name = f'objects/garment-{index}.dds'
                        expected[name] = serial.read_bytes()
                        bake(folder / name, image, material, specular)
                        # Caller-owned inputs must be snapshotted before enqueueing.
                        image.paste((0, 0, 0, 0), (0, 0, 8, 8))
                        specular.paste((255, 255, 255, 0), (0, 0, 8, 8))
                        material.set('Diffuse', '0,0,0')
                        self.assertLessEqual(len(adapter.pending), 4)
                adapter.finish()
            self.assertEqual(names, list(expected))
            self.assertFalse(adapter.pending)
            self.assertEqual({name: path.read_bytes() for name, path in adapter.assets.emitted.items()}, expected)

    def test_world_voxels_build_serial_and_parallel_match_without_game(self):
        """Synthetic KCD1 tiles (same fixture as test_voxel_lighting) through the real build()."""
        import struct
        import tempfile
        import zlib
        from world_voxels import build
        raw = bytes([1, 1, 1, 1, 0, 0, 0, 1]) + bytes(8) + bytes([0xf0, 0x8f])
        packed = struct.pack('<I', len(raw)) + zlib.compress(raw)
        node = struct.pack('<I', len(packed)) + packed
        node += bytes((-len(node)) % 4)
        tile = struct.pack('<I', 0) + struct.pack('<II', 68, len(node)) + bytes(56) + node
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            level = root / 'Data/Levels/rataje'; level.mkdir(parents=True)
            with zipfile.ZipFile(level / 'level.pak', 'w') as z:
                z.writestr('leveldata.xml', '<LevelData><Layers><Layer Name="village_state0" Id="1"/></Layers></LevelData>')
            with zipfile.ZipFile(level / 'svo.pak', 'w') as z:
                for i in range(7):
                    z.writestr(f'terrain/svo/{128 + 256 * i}_{128 + 256 * (i % 3)}_0128_0256.dat', tile)
            def members(destination):
                result = []
                for pak in sorted(destination.glob('svo-part*.pak')):
                    with zipfile.ZipFile(pak) as z:
                        result += [(pak.name, n, z.read(n)) for n in z.namelist()]
                return result
            serial = build(root, root / 'serial', workers=1)
            parallel = build(root, root / 'parallel', workers=3)
            self.assertEqual(serial, parallel)
            self.assertEqual(len(serial['tiles']), 7)
            self.assertEqual(members(root / 'serial'), members(root / 'parallel'))

    @unittest.skipUnless((KCD1 / 'Data/Levels/rataje/svo.pak').is_file(), 'KCD1 voxel source not installed')
    def test_voxel_tiles_serial_and_parallel_bytes_match(self):
        import re
        import xml.etree.ElementTree as ET
        from entity_visuals import initial_layer
        from upgrade_map import read
        from world_voxels import _tile
        with zipfile.ZipFile(KCD1 / 'Data/Levels/rataje/level.pak') as world:
            layers = ET.fromstring(read(world, 'leveldata.xml')).find('Layers')
            active = {0} | {int(e.get('Id')) for e in layers if initial_layer(e.get('Name', ''))}
        with zipfile.ZipFile(KCD1 / 'Data/Levels/rataje/svo.pak') as src:
            names = sorted(n for n in src.namelist() if n.endswith('.dat'))[:6]
            def jobs():
                for name in names:
                    *center, extent = map(int, re.fullmatch(r'(\d+)_(\d+)_(\d+)_(\d+)\.dat', Path(name).name).groups())
                    yield read(src, name), center, extent, active
            serial = list(ordered_map(_tile, jobs(), 1))
            parallel = list(ordered_map(_tile, jobs(), 3))
        self.assertEqual(serial, parallel)


if __name__ == '__main__':
    unittest.main()
