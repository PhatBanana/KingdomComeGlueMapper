from pathlib import Path
import struct
import sys
from types import SimpleNamespace
import unittest
import xml.etree.ElementTree as ET

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'tools'))
from puddle_decals import decal_record, planar_quad, sort_priority
from puddle_materials import convert_puddle_proxies, puddle_decal_slots
from terrain_object_tree import bounds, maximum_view_distance, place, read_tree


# The imported KCD1 puddle quad: half extent 0.834, u along +x, v along -y.
QUAD = np.array([[[0.834, -0.834, 0], [0.834, 0.834, 0], [-0.834, 0.834, 0]],
                 [[-0.834, 0.834, 0], [-0.834, -0.834, 0], [0.834, -0.834, 0]]])
UV = np.array([[[1, 1], [1, 0], [0, 0]], [[0, 0], [0, 1], [1, 1]]], dtype=float)

PUDDLE = '''<Material><SubMaterials>
  <Material Name="soil" Shader="Illum" SurfaceType="mat_mudwater" CustomSortPriority="40"
    StringGenMask="%DECAL%DETAIL_ATLAS%NORMAL_MAP%PARALLAX_OCCLUSION_MAPPING">
    <Textures><Texture Map="Diffuse" File="gluebuild/setup_props/t1_puddle_4_diff.dds"/></Textures>
  </Material>
  <Material Name="proxy" Shader="Nodraw" SurfaceType="mat_water"/>
</SubMaterials></Material>'''


def transform(scale=2.133, yaw=0.3, origin=(791.18, 3477.0, 50.71)):
    c, s = np.cos(yaw), np.sin(yaw)
    rotation = np.array([[c, -s, 0], [s, c, 0], [0, 0, 1]]) * scale
    return np.column_stack((rotation, origin)).reshape(-1)


class PlanarQuadTests(unittest.TestCase):
    def test_imported_quad_maps_uv_affinely(self):
        origin, u, v, normal = planar_quad(QUAD, UV)
        np.testing.assert_allclose(origin, [-0.834, 0.834, 0], atol=1e-6)
        np.testing.assert_allclose(u, [1.668, 0, 0], atol=1e-6)
        np.testing.assert_allclose(v, [0, -1.668, 0], atol=1e-6)
        np.testing.assert_allclose(normal, [0, 0, 1], atol=1e-6)

    def test_rejects_tiled_sculpted_and_partial_geometry(self):
        self.assertIsNone(planar_quad(QUAD, UV * 2))  # tiled UVs
        bumpy = QUAD.copy(); bumpy[0, 1, 2] = 0.2
        self.assertIsNone(planar_quad(bumpy, UV))  # not flat
        self.assertIsNone(planar_quad(QUAD[:1], UV[:1]))  # half the square only
        self.assertIsNone(planar_quad(np.zeros((0, 3, 3)), np.zeros((0, 3, 2))))


class DecalRecordTests(unittest.TestCase):
    def record(self, matrix=None, sort=40, material=7):
        return decal_record(transform() if matrix is None else matrix, planar_quad(QUAD, UV), material, sort)

    def test_native_layout_fields(self):
        record = self.record()
        self.assertEqual(len(record), 120)
        self.assertEqual(struct.unpack_from('<I', record)[0], 7)
        self.assertEqual((record[42], record[43]), (100, 100))
        self.assertEqual(struct.unpack_from('<h', record, 44)[0], 0)  # planar
        self.assertEqual(record[46], 1)  # deferred
        self.assertEqual(record[28:42], bytes(14))
        radius, material, sort = struct.unpack_from('<fii', record, 108)
        self.assertAlmostEqual(radius, 0.834 * 2.133, places=4)
        self.assertEqual((material, sort), (7, 40))

    def test_frame_is_right_handed_faces_up_and_covers_the_quad(self):
        record = self.record()
        centre = np.array(struct.unpack_from('<3f', record, 48))
        normal = np.array(struct.unpack_from('<3f', record, 60))
        columns = np.array(struct.unpack_from('<9f', record, 72)).reshape(3, 3)
        np.testing.assert_allclose(centre, [791.18, 3477.0, 50.71], atol=1e-3)
        np.testing.assert_allclose(normal, [0, 0, 1], atol=1e-6)
        right, up, front = columns.T
        np.testing.assert_allclose(np.cross(right, up) / np.linalg.norm(np.cross(right, up)), normal, atol=1e-6)
        np.testing.assert_allclose(front, normal * np.linalg.norm(right), atol=1e-5)
        # Every quad corner lies inside the projection box (unit square in decal space).
        m = transform().reshape(3, 4)
        for corner in QUAD.reshape(-1, 3):
            local = np.linalg.solve(columns, m[:, :3] @ corner + m[:, 3] - centre)
            self.assertTrue((np.abs(local) <= 1 + 1e-5).all())

    def test_bounds_follow_native_half_front_rule(self):
        record = self.record()
        box = np.array(bounds(record))
        columns = np.array(struct.unpack_from('<9f', record, 72)).reshape(3, 3)
        half = np.abs(columns[:, 0]) + np.abs(columns[:, 1]) + 0.5 * np.abs(columns[:, 2])
        np.testing.assert_allclose((box[3:] - box[:3]) / 2, half, atol=1e-4)

    def test_mirrored_brush_still_projects_onto_its_visible_side(self):
        mirrored = transform().reshape(3, 4).copy()
        mirrored[:, 0] *= -1
        normal = np.array(struct.unpack_from('<3f', self.record(mirrored.reshape(-1)), 60))
        np.testing.assert_allclose(normal, [0, 0, -1], atol=1e-6)

    def test_octree_accepts_and_preserves_the_record(self):
        record = self.record()
        root_box = (0., 0., 0., 4096., 4096., 4096.)
        tree = SimpleNamespace(data=struct.pack('<HBB6fI', 8, 0, 0, *root_box, 0), tree_offset=0, version=29)
        out = place(tree, [record])
        _, nodes = read_tree(SimpleNamespace(data=out, tree_offset=0))
        self.assertEqual([r for n in nodes for r in n.records], [(7, record)])
        # 1.78 m radius * 0.75 * 60 at the native 100% byte, not the brush's 10%.
        self.assertAlmostEqual(maximum_view_distance(record), 0.834 * 2.133 * 45, places=2)


class PuddleMaterialTests(unittest.TestCase):
    def test_sort_priority_and_proxy_conversion_share_the_puddle_predicate(self):
        material = ET.fromstring(PUDDLE)
        self.assertEqual([s.get('Name') for s in puddle_decal_slots(material)], ['soil'])
        self.assertEqual(sort_priority(material), 40)
        self.assertEqual(convert_puddle_proxies(material), 1)

    def test_non_puddle_decals_are_rejected(self):
        material = ET.fromstring(PUDDLE.replace('puddle_4', 'soil_muddy'))
        self.assertEqual(puddle_decal_slots(material), [])
        with self.assertRaises(ValueError):
            sort_priority(material)
        self.assertEqual(convert_puddle_proxies(material), 0)


if __name__ == '__main__':
    unittest.main()
