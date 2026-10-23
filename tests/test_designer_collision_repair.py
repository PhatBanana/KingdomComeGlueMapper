import unittest
import xml.etree.ElementTree as E
from designer_collision_repair import hide_proxy


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
