import sys
from pathlib import Path
import unittest
import xml.etree.ElementTree as ET

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from interior_exposure import convert


class ExposureTests(unittest.TestCase):
    def test_native_overrides_and_dark_profiles_preserve_other_settings(self):
        source = b'''<Mission><Environment Active="1"/><TimeOfDay Time="14">
          <Variable Name="EV Max" Value="11"><Spline Keys="0:11:36,"/></Variable>
          <Variable Name="EV Min" Value="8"><Spline Keys="0:6:36,0.5:6.5:65572,"/>
            <ColorSpaceOverride Type="1" Keys="0:7:36,0.5:8:36,"/></Variable>
          <Profile Name="dark"><Variable Name="EV Min" Value="2">
            <Spline Keys="0:2:36,"/></Variable></Profile>
        </TimeOfDay></Mission>'''
        result, report = convert(source)
        root = ET.fromstring(result)
        minimum = root.find("TimeOfDay/Variable[@Name='EV Min']")
        self.assertEqual(minimum.get('Value'), '4')
        self.assertEqual(minimum.find('Spline').get('Keys'), '0:4:36,0.5:4:65572,')
        self.assertEqual(minimum.find('ColorSpaceOverride').get('Keys'), '0:4:36,0.5:4:36,')
        self.assertEqual(root.find('TimeOfDay/Profile/Variable').get('Value'), '2')
        self.assertEqual(root.find("TimeOfDay/Variable[@Name='EV Max']/Spline").get('Keys'), '0:11:36,')
        self.assertEqual(root.find('Environment').get('Active'), '1')
        self.assertEqual(report['exposure_profiles'], 2)
        self.assertEqual(convert(result)[0], result)

    def test_missing_settings_fail(self):
        for source in (b'<Mission/>', b'<Mission><TimeOfDay/></Mission>'):
            with self.assertRaises(ValueError):
                convert(source)


if __name__ == '__main__':
    unittest.main()
