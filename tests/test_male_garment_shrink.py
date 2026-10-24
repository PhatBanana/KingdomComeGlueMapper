"""Covered male garments fit onto #A_Shrink on the torso only, not the sleeves (issue #1)."""
import struct
import sys
from pathlib import Path
import unittest

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from character_person_appearance import male_garment_covered, torso_shrink_weights
from character_skin_upgrade import CompiledSkin, upgrade_skin
from clothing_regions import read_chunks, write_chunks, vertex_arm_weights, assign_upper_garment_regions
from test_character_upgrade import sample_skin

# (spine weight, arm weight) per vertex, as 8-bit bone weights.
WEIGHTS = [(255, 0), (0, 255), (204, 51), (128, 127), (255, 0), (255, 0)]


def arm_garment(shrink=True):
    """Six-vertex garment with bones Hips/LeftForeArm and an #A_Shrink of -1 x."""
    chunks = read_chunks(sample_skin())
    replacements = {}
    bones = next(c for c in chunks if c.kind == 0x2000)
    payload = bytearray(bones.data)
    payload[32+584+312:32+584+568] = b'LeftForeArm'.ljust(256, b'\0')
    replacements[bones.id] = bytes(payload)
    weights = next(c for c in chunks if c.kind == 0x1016 and struct.unpack_from('<I', c.data, 4)[0] == 9)
    replacements[weights.id] = weights.data[:24] + b''.join(
        struct.pack('<4H4B', 0, 1, 0, 0, spine, arm, 0, 0) for spine, arm in WEIGHTS)
    if shrink:
        morph = next(c for c in chunks if c.kind == 0x2002)
        name = b'#A_Shrink\0'
        header = struct.pack('<4I6fIf', 0xffffffff, len(name), 6, 6, -1, 0, 0, 0, 0, 0, 1, 1)
        replacements[morph.id] = struct.pack('<I', 1) + header + name + struct.pack('<2H', 0, 6) + bytes(18)
    return write_chunks(chunks, replacements)


def cloth(model):
    return dict(kind='cloth', model='objects/characters/humans/male/' + model)


class MaleGarmentShrinkTests(unittest.TestCase):
    def test_vertex_arm_weights_are_named_bone_fractions(self):
        expected = [arm / (spine + arm) for spine, arm in WEIGHTS]
        np.testing.assert_allclose(vertex_arm_weights(arm_garment()), expected)

    def test_shrink_weight_is_full_on_torso_none_on_sleeves_and_fades_between(self):
        weights = torso_shrink_weights(arm_garment())
        np.testing.assert_allclose(weights, [1, 0, 0.6, 1 - 2 * 127 / 255, 1, 1])
        with self.assertRaises(ValueError):
            torso_shrink_weights(arm_garment(), arm_weight_threshold=0)

    def test_sleeve_faces_keep_their_shape_and_torso_faces_shrink(self):
        source = arm_garment()
        weights = torso_shrink_weights(source)
        output, report = upgrade_skin(source, source, morph_weights={'#A_Shrink': weights})
        before, after = CompiledSkin(source).vertices, CompiledSkin(output).vertices
        np.testing.assert_allclose(after - before, np.c_[-weights, np.zeros(6), np.zeros(6)], atol=1e-6)
        # The faces the region split calls sleeves are exactly the unshrunk ones.
        regions = assign_upper_garment_regions(source, waist_z=-10)
        moved = np.linalg.norm(after - before, axis=1) > 1e-6
        for face, region in zip(CompiledSkin(source).faces, regions):
            if all(not moved[v] for v in face):
                self.assertEqual(region, 'arms')
        self.assertEqual(report['baked_morphs']['#A_Shrink']['per_vertex'], True)
        self.assertEqual(report['baked_morphs']['#A_Shrink']['maximum'], 1.0)
        self.assertEqual(report['preserved_morphs'], 0)

    def test_scalar_fit_is_unchanged(self):
        source = arm_garment()
        output, report = upgrade_skin(source, source, morph_weights={'#A_Shrink': 1.0})
        np.testing.assert_allclose(CompiledSkin(output).vertices, CompiledSkin(source).vertices + [-1, 0, 0])
        self.assertEqual(report['baked_morphs'], {'#A_Shrink': 1.0})

    def test_per_vertex_weight_must_cover_every_vertex_and_be_finite(self):
        source = arm_garment()
        for weights in (np.ones(5), np.ones((6, 1)), np.r_[np.ones(5), np.nan]):
            with self.assertRaises(ValueError):
                upgrade_skin(source, source, morph_weights={'#A_Shrink': weights})

    def test_coverage_uses_authored_part_and_layer_only(self):
        shirt, coat, apron = cloth('s1_p2_l1_v0.skin'), cloth('s1_p2_l2_v0.skin'), cloth('s1_p2_l4_v2.skin')
        hose, unlabelled = cloth('s1_p3_l1_v0.skin'), cloth('belt.skin')
        parts = [dict(kind='body', model='body.skin'), shirt, coat, apron, hose, unlabelled]
        self.assertTrue(male_garment_covered(shirt, parts))
        self.assertTrue(male_garment_covered(coat, parts))
        self.assertFalse(male_garment_covered(apron, parts))
        self.assertFalse(male_garment_covered(hose, parts))
        self.assertFalse(male_garment_covered(unlabelled, parts))
        self.assertFalse(male_garment_covered(shirt, [shirt, unlabelled, hose]))


if __name__ == '__main__':
    unittest.main()
