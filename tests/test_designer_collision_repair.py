import unittest
from contextlib import nullcontext
from pathlib import Path
import struct
import tempfile
from types import SimpleNamespace
from unittest.mock import patch
import zipfile
import xml.etree.ElementTree as E
from designer_collision_repair import hide_proxy, non_boundary_blockers, collision_geometry, upgrade
from building_brushes import convert_brush


def source_brush(x, material, layer=0):
    blob = bytearray(100)
    struct.pack_into('<I6f', blob, 0, 1, x, 0, 0, x+2, 2, 5)
    struct.pack_into('<H', blob, 28, layer)
    struct.pack_into('<12f', blob, 40, 1, 0, 0, x, 0, 1, 0, 0, 0, 0, 1, 0)
    struct.pack_into('<i', blob, 92, material)
    return bytes(blob)


class BoundaryMigration(unittest.TestCase):
    def test_geometry_identity_allows_material_rename_but_rejects_different_solid(self):
        from clothing_regions import Chunk, write_chunks
        def mesh(physics, material):
            return write_chunks([Chunk(0x1018, 1, 1, physics),
                                 Chunk(0x1014, 0x802, 2, material.ljust(128,b'\0'))], {})
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp); package=root/'package'; source=root/'source'
            source_pak=source/'Data/Levels/rataje/level.pak'
            target_pak=package/'Data/Levels/kcd1_travel/terrain.pak'
            source_pak.parent.mkdir(parents=True);target_pak.parent.mkdir(parents=True)
            with zipfile.ZipFile(source_pak,'w') as z:
                z.writestr('brush/designer_1.cgf',mesh(b'proxy physics',b'original/material'))
            with zipfile.ZipFile(target_pak,'w') as z:z.writestr('terrain/terrain.dat',b'fixture')
            with zipfile.ZipFile(package/'Data/geometry.pak','w') as z:
                z.writestr('proxy.cgf',mesh(b'proxy physics',b'renamed/material'))
                z.writestr('visible.cgf',mesh(b'visible physics',b'renamed/material'))
            terrain=SimpleNamespace(tables={'meshes':{'paths':['proxy.cgf','visible.cgf']}})
            with patch('compiled_terrain.parse',return_value=terrain), collision_geometry(package,source) as matches:
                candidate={'source_mesh':'%level%/brush/designer_1.cgf'}
                self.assertTrue(matches(0,candidate))
                self.assertFalse(matches(1,candidate))

    def test_source_identity_distinguishes_map_border_from_local_level_barrier(self):
        terrain = SimpleNamespace(tables={
            'meshes': {'paths': ['%level%/brush/designer_1.cgf']},
            'materials': {'paths': ['materials/special/collision_proxy_level_barrier',
                                    'materials/special/collision_proxy_material']}})
        records = [source_brush(0, 0), source_brush(10, 0, 583), source_brush(20, 1)]
        def visit(t, callback):
            for blob in records: callback(blob, 0, len(blob), 1)
        with patch('designer_collision_repair.read', return_value=b''), \
                patch('compiled_terrain.parse', return_value=terrain), \
                patch('water_volumes.read_water', side_effect=visit):
            found = non_boundary_blockers(None)
        self.assertEqual([r['position'][0] for r in found], [10, 20])

    def test_saved_package_removes_gate_fillers_keeps_border_and_visible_hearth(self):
        # Even identical origin and bounds are insufficient: a visible hearth
        # with different geometry must survive, as must the native mission data.
        source = source_brush(10, 1)
        removed = dict(position=[10, 0, 0], bbox=[10, 0, 0, 12, 2, 5])
        gate = convert_brush(source, 0, 1, -1)
        border = convert_brush(source_brush(100, 0), 0, 2, -1)
        hearth = bytearray(gate); struct.pack_into('<H', hearth, 40, 3)
        block = gate + border + hearth
        data = struct.pack('<II', 2, len(block)) + block
        metadata = ('<HLods><HLod DataOffset="4" DataSize="'+str(len(block)+4)+
                    '" Pos="0,0,0" Radius="200"/></HLods>').encode()
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); package = root/'package'; game = root/'source'
            level = package/'Data/Levels/kcd1_travel/level.pak'
            level.parent.mkdir(parents=True)
            source_level = game/'Data/Levels/rataje/level.pak'
            source_level.parent.mkdir(parents=True)
            with zipfile.ZipFile(source_level, 'w'): pass
            with zipfile.ZipFile(level, 'w') as z:
                z.writestr('terrain/hlods.dat', data)
                z.writestr('terrain/hlods.xml', metadata)
                z.writestr('objects_mission0.xml', b'<Objects><Entity EntityClass="AnimDoor"/></Objects>')
            with patch('designer_collision_repair.non_boundary_blockers', return_value=[removed]), \
                    patch('designer_collision_repair.collision_geometry',
                          side_effect=lambda *a: nullcontext(lambda mesh, record: mesh == 1)):
                changed, report = upgrade(package, game)
                self.assertIn('Data/Levels/kcd1_travel/level.pak', changed)
                self.assertEqual(len(report['removed_non_boundary_blockers']), 1)
                with zipfile.ZipFile(level) as z:
                    self.assertEqual(z.read('terrain/hlods.dat')[8:], border + hearth)
                    self.assertIn(b'AnimDoor', z.read('objects_mission0.xml'))
                before = level.read_bytes()
                self.assertEqual(upgrade(package, game)[0], {})
                self.assertEqual(level.read_bytes(), before)


class ProxyMaterials(unittest.TestCase):
    def test_relocated_proxy_keeps_physics_and_is_idempotent(self):
        root = E.fromstring('<Material Shader="Illum" SurfaceType="mat_horse_only"><Textures><Texture File="gluebuild/map/t8_collision_proxy.dds"/></Textures></Material>')
        self.assertEqual(hide_proxy(root), 1)
        self.assertEqual(root.get('Shader'), 'Nodraw')
        self.assertEqual(root.get('SurfaceType'), 'mat_horse_only')
        self.assertEqual(hide_proxy(root), 0)

    def test_visible_red_material_is_not_a_proxy(self):
        root = E.fromstring('<Material Shader="Illum" Diffuse="1,0,0" SurfaceType="mat_rock"><Textures><Texture File="stone.dds"/></Textures></Material>')
        before = E.tostring(root)
        self.assertEqual(hide_proxy(root), 0)
        self.assertEqual(E.tostring(root), before)

    def test_all_proxy_submaterials_keep_their_surfaces(self):
        root = E.fromstring('<Material><SubMaterials>' + ''.join(
            '<Material SurfaceType="'+surface+'"><Textures><Texture File="materials/special/collision_proxy.tif"/></Textures></Material>'
            for surface in ('mat_level_barrier','mat_player_only','mat_nodraw_designer')) + '</SubMaterials></Material>')
        self.assertEqual(hide_proxy(root), 3)
        self.assertEqual([n.get('SurfaceType') for n in root.findall('SubMaterials/Material')],
                         ['mat_level_barrier','mat_player_only','mat_nodraw_designer'])
