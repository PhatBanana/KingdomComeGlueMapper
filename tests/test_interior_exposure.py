import sys
from pathlib import Path
import unittest
import xml.etree.ElementTree as ET

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from interior_exposure import convert, restore

NATIVE = b'''<Mission><TimeOfDay Time="14">
  <Variable Name="EV Max" Value="11"><Spline Keys="0:11:36,"/></Variable>
  <Variable Name="EV Min" Value="8"><Spline Keys="0:6:36,0.5:6.5:65572,"/>
    <ColorSpaceOverride Type="1" Keys="0:7:36,0.5:8:36,"/></Variable>
  <Profile Name="dark"><Variable Name="EV Min" Value="2"><Spline Keys="0:2:36,"/></Variable></Profile>
</TimeOfDay></Mission>'''


def minimums(blob):
    return [ET.tostring(v) for v in ET.fromstring(blob).iter('Variable') if v.get('Name') == 'EV Min']


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

    def test_restore_returns_native_minimums_and_keeps_other_settings(self):
        capped = convert(NATIVE)[0].replace(b'Value="11"', b'Value="12"')  # a later, unrelated edit survives
        restored, report = restore(capped, NATIVE)
        self.assertEqual(report['restored_exposure_profiles'], 2)
        self.assertEqual(minimums(restored), minimums(NATIVE))
        self.assertEqual(ET.fromstring(restored).find("TimeOfDay/Variable[@Name='EV Max']").get('Value'), '12')
        self.assertEqual(restore(restored, NATIVE), (restored, {'restored_exposure_profiles': 0}))
        self.assertEqual(convert(restored)[0], capped)

    def test_restore_leaves_a_mission_not_capped_from_this_native_alone(self):
        other = NATIVE.replace(b'Value="8"', b'Value="3.5"')
        for blob in (other, convert(other)[0]):
            self.assertEqual(restore(blob, NATIVE), (blob, {'restored_exposure_profiles': 0}))

    def test_missing_settings_fail(self):
        for source in (b'<Mission/>', b'<Mission><TimeOfDay/></Mission>'):
            with self.assertRaises(ValueError):
                convert(source)


if __name__ == '__main__':
    unittest.main()
