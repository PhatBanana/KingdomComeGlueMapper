import base64
from pathlib import Path
import struct
import sys
import unittest

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from clothing_coverage import triangle_mask, source_opacity, covered_points, apply_membership, unculled_garment_visibility
from character_skin_upgrade import CompiledSkin, upgrade_skin
from test_character_upgrade import sample_skin


def encoded(bits):
    return base64.b64encode(struct.pack('<H', len(bits)) + np.packbits(bits, bitorder='little').tobytes()).decode()


class ClothingCoverageTests(unittest.TestCase):
    def test_source_mask_bit_order_and_topology_guard(self):
        bits = [True, False, False, True, True, False, True, False, True]
        np.testing.assert_array_equal(triangle_mask(encoded(bits), 9), bits)
        for count in (8, 10):
            with self.assertRaises(ValueError):
                triangle_mask(encoded(bits), count)

    def test_opacity_requires_exact_material_and_intersects_visibility(self):
        rows = [dict(skin='Dress.skin', material='Red.mtl',
                     opaque_triangle_mask=encoded([1, 0, 1]),
                     not_culled_triangle_mask=encoded([1, 1, 0]))]
        np.testing.assert_array_equal(source_opacity(rows, 'dress.skin', 'red.mtl', 3), [1, 0, 0])
        with self.assertRaises(ValueError):
            source_opacity(rows, 'dress.skin', 'blue.mtl', 3)
        rows[0]['opaque_triangle_mask'] = ''
        with self.assertRaises(ValueError):
            source_opacity(rows, 'dress.skin', 'red.mtl', 3)

    def test_surface_normal_coverage_preserves_exposed_opening_and_ignores_distant_mesh(self):
        # A sleeve surface only covers the first point, not the exposed shoulder
        # beside it or an unrelated surface half a metre away.
        triangle = np.array([[[-1, -1, .02], [1, -1, .02], [0, 1, .02]]])
        points = [[0, 0, 0], [2, 0, 0], [0, 0, -.5]]
        np.testing.assert_array_equal(covered_points(points, [[0, 0, 1]]*3, triangle), [1, 0, 0])
        # A slightly protruding body vertex still needs coverage from an inner surface.
        np.testing.assert_array_equal(covered_points([[0, 0, .04]], [[0, 0, 1]], triangle), [1])
        np.testing.assert_array_equal(covered_points(points, [[0, 0, 1]]*3, triangle[:0]), [0, 0, 0])

    def test_missing_visibility_can_use_converted_mesh_but_not_replace_opacity(self):
        rows = [dict(skin='dress.skin', material='red.mtl',
                     opaque_triangle_mask=encoded([1, 0, 1]), not_culled_triangle_mask='')]
        visible = np.array([True, True, False])
        np.testing.assert_array_equal(source_opacity(rows, 'dress.skin', 'red.mtl', 3, visible), [1, 0, 0])
        with self.assertRaises(ValueError): source_opacity(rows, 'dress.skin', 'red.mtl', 3, [1, 1, 1])
        rows[0]['opaque_triangle_mask'] = ''
        with self.assertRaises(ValueError): source_opacity(rows, 'dress.skin', 'red.mtl', 3, visible)

    def test_rebuilt_visibility_rejects_retained_hiding_bits(self):
        blob, _ = upgrade_skin(sample_skin(), sample_skin(), clear_hiding=True)
        skin = CompiledSkin(blob)
        self.assertTrue(unculled_garment_visibility(skin).all())
        hidden = apply_membership(blob, {4: np.ones(skin.n, dtype=bool)})
        with self.assertRaisesRegex(ValueError, 'hiding membership'):
            unculled_garment_visibility(CompiledSkin(hidden))

    def test_conditional_masks_restore_body_when_garment_is_removed(self):
        source = sample_skin()
        source, _ = upgrade_skin(source, source)
        before = CompiledSkin(source)
        outer = np.array([1, 1, 0, 0, 0, 0], dtype=bool)
        inner = np.array([0, 1, 1, 0, 0, 0], dtype=bool)
        result = CompiledSkin(apply_membership(source, {4: inner, 5: outer}))
        alpha = np.frombuffer(result.streams[3].data[24:], dtype=np.uint8).reshape(-1, 4)[:, 3]
        hidden_by_outer = (alpha & (1 << 5)) == 0
        hidden_by_inner = (alpha & (1 << 4)) == 0
        np.testing.assert_array_equal(hidden_by_outer, outer)
        np.testing.assert_array_equal(hidden_by_inner, inner)
        # No active group: every body vertex is available again, not deleted.
        np.testing.assert_array_equal(((255 ^ alpha) & 0) != 0, np.zeros(before.n, dtype=bool))
        for stream in (0, 1, 2, 5, 6, 9):
            self.assertEqual(before.streams[stream].data, result.streams[stream].data)
        for i, remap in enumerate(result.remap):
            self.assertEqual(result.internal.data[32+int(remap)*64+63], alpha[i])


if __name__ == '__main__':
    unittest.main()
