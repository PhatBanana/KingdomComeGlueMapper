import sys
from pathlib import Path
import unittest
import xml.etree.ElementTree as ET

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from water_animation import convert_waterfall_speeds


class WaterAnimation(unittest.TestCase):
    def test_scroll_distance_matches_source_for_both_layers(self):
        for speed in (-3.5, 0, 1, 35.5, 100):
            doc = ET.fromstring(f'<Material Shader="Waterfall"><PublicParams '
                               f'SpeedLayer0="{speed}" SpeedLayer1="{speed}" '
                               'TillingLayer0="0.51"/></Material>')
            convert_waterfall_speeds(doc)
            params = doc.find('PublicParams')
            for seconds in (0, 0.5, 17, 1000):
                for name in ('SpeedLayer0', 'SpeedLayer1'):
                    self.assertAlmostEqual(seconds * .0125 * speed,
                                           seconds * .125 * float(params.get(name)))
            self.assertEqual(params.get('TillingLayer0'), '0.51')

    def test_mixed_slots_only_convert_waterfall_and_materialize_defaults(self):
        doc = ET.fromstring('<Material><SubMaterials><Material Shader="Waterfall"/>'
                            '<Material Shader="WaterVolume"><PublicParams WaterFlowSpeed="2"/>'
                            '</Material><Material Shader="Illum"/></SubMaterials></Material>')
        before = ET.tostring(doc.find('SubMaterials/Material[@Shader="WaterVolume"]'))
        self.assertEqual(len(convert_waterfall_speeds(doc)), 2)
        params = doc.find('SubMaterials/Material/PublicParams')
        self.assertEqual(params.attrib, {'SpeedLayer0': '0.1', 'SpeedLayer1': '0.2'})
        self.assertEqual(ET.tostring(doc.find('SubMaterials/Material[@Shader="WaterVolume"]')), before)


if __name__ == '__main__':
    unittest.main()
