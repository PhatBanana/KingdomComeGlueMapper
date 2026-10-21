"""Asset-free checks for the designer collision and barrier volume selection."""
from pathlib import Path
import struct
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
from building_brushes import (COLLISION_PROXY_MATERIALS, LANDSCAPE_DESIGNER_MATERIALS,
                              is_collision_designer, is_landscape_designer, convert_brush)


class DesignerCollisionTests(unittest.TestCase):
    def test_collision_materials_are_the_proxy_surface_types(self):
        self.assertGreaterEqual(len(COLLISION_PROXY_MATERIALS), 6)
        for name in COLLISION_PROXY_MATERIALS:
            self.assertTrue(name.startswith('materials/special/'), name)
        # The six headline barrier families the conversion must not drop.
        for family in ('collision_proxy_horseonly', 'collision_proxy_material',
                       'collision_proxy_player_only', 'collision_proxy_deep_water_barrier',
                       'collision_proxy_level_barrier', 'collision_proxy_return_to_skalice_barrier'):
            self.assertIn('materials/special/' + family, COLLISION_PROXY_MATERIALS)

    def test_visible_landscape_designers_never_classify_as_collision(self):
        for material in LANDSCAPE_DESIGNER_MATERIALS:
            self.assertFalse(is_collision_designer('%level%/brush/designer_0.cgf', material))
            self.assertTrue(is_landscape_designer('%level%/brush/designer_0.cgf', material))

    def test_collision_classifier_accepts_only_designer_paths(self):
        self.assertTrue(is_collision_designer('%LEVEL%/BRUSH/designer_123.cgf', 'materials/special/collision_proxy_material'))
        self.assertTrue(is_collision_designer('%level%/brush/designer_0.cgf', 'MATERIALS/SPECIAL/COLLISION_PROXY_HORSEONLY.mtl'))
        self.assertFalse(is_collision_designer('%level%/brush/clipvolume_0.cgf', 'materials/special/collision_proxy_material'))
        self.assertFalse(is_collision_designer('objects/buildings/houses/house_a.cgf', 'materials/special/collision_proxy_material'))
        self.assertFalse(is_collision_designer('%level%/brush/designer_0.cgf', 'materials/color/dark'))
        self.assertFalse(is_collision_designer('%level%/brush/designer_0.cgf', 'objects/structures/mining_structures/material_unwalk'))

    def test_converted_collision_record_bakes_material_into_mesh(self):
        source = bytearray(100)
        struct.pack_into("<I", source, 0, 1)
        struct.pack_into("<H", source, 28, 0)
        struct.pack_into("<I", source, 32, 0x40100408)  # hidden + legacy instancing bits
        struct.pack_into("<H", source, 36, 7081)
        struct.pack_into("<12f", source, 40, 1, 0, 0, 1653.7, 0, 1, 0, 2592.1, 0, 0, 1, 129.6)
        struct.pack_into("<HHiI", source, 88, 0, 0, 325, 17)
        result = convert_brush(bytes(source), 0, 9000, -1)
        self.assertEqual(len(result), 104)
        self.assertEqual(struct.unpack_from("<H", result, 40)[0], 9000)
        self.assertEqual(struct.unpack_from("<H", result, 92)[0], 0)  # neutral collision class, as native
        self.assertEqual(struct.unpack_from("<i", result, 96)[0], -1)  # material stays baked in the mesh
        self.assertEqual(result[44:92], source[40:88])
        flags = struct.unpack_from("<Q", result, 32)[0]
        self.assertFalse(flags & (1 << 8))
        self.assertFalse(flags & (1 << 20))


if __name__ == "__main__":
    unittest.main()
