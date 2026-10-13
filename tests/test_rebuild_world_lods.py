import json
from pathlib import Path
import sys
import tempfile
import unittest
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'tools'))
from rebuild_world_lods import build


class WorldLods(unittest.TestCase):
    def test_additive_repair_keeps_installed_material_and_closes_lod_dependencies(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source, installed = root/'source', root/'installed'
            (source/'gluebuild').mkdir(parents=True)
            installed.mkdir()
            for name, blob in {
                'house.cgf': b'old base',
                'house_lod1.cgf': b'gluebuild/current.mtl',
                'house_lod1.cgfm': b'stream',
                'house_lod2.cgf': b'gluebuild/lod.mtl',
                'lod.mtl': b'gluebuild/lod.dds',
                'lod.dds': b'pixels', 'lod.dds.1': b'mip',
                'current.mtl': b'gluebuild/deleted.dds',
                'unplaced_lod1.cgf': b'unused'
            }.items():
                (source/'gluebuild'/name).write_bytes(blob)
            pak = installed/'world.pak'
            with zipfile.ZipFile(pak, 'w') as z:
                z.writestr('gluebuild/house.cgf', b'current base')
                z.writestr('gluebuild/current.mtl', b'current material')
            before = pak.read_bytes()
            report = build(source, installed, root/'output')
            self.assertEqual(report['restored_lods'], 2)
            self.assertEqual(report['missing_dependencies_after'], 0)
            self.assertEqual(pak.read_bytes(), before)
            names = {a['path'] for a in report['assets']}
            self.assertEqual(len(names), 6)
            self.assertNotIn('gluebuild/current.mtl', names)
            for archive in report['archives']:
                (installed/archive).write_bytes((root/'output'/archive).read_bytes())
            again = build(source, installed, root/'second')
            self.assertEqual(again['assets'], [])
            self.assertEqual(again['restored_lods'], 0)
