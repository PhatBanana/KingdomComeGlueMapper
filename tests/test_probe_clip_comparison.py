import copy
from pathlib import Path
import sys
import unittest
import xml.etree.ElementTree as ET

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'tools'))
from build_probe_clip_comparison import CASES, variant


class ProbeClipComparisonTests(unittest.TestCase):
    def test_cases_preserve_probe_transform_capture_and_other_entities(self):
        root = ET.fromstring('''<Objects>
          <Entity Name="gm_lighting_26457" Pos="735,3414,68" Rotate="0,0,0,1">
            <Properties BoxSizeX="9.6" GenOffsetY="-7" bActive="1">
              <Options bIgnoresVisAreas="1" bAffectsThisAreaOnly="1" bDeferredClipBounds="1" fAttenuationFalloffMax="0"/>
              <Color fDiffuseMultiplier="0.5"/>
            </Properties><EntityLinks><Link Name="ClipVolume" TargetId="wrong"/></EntityLinks>
          </Entity>
          <Entity Name="gm_lighting_26456"><Properties bActive="1"/></Entity>
          <Entity Name="gm_lighting_8795" EntityId="99" EntityGuid="clip-guid"><ClipVolume GeometryFileName="%level%/clip.cgf" Flags="68"/></Entity>
          <Entity Name="unrelated"><Properties untouched="1"/></Entity>
        </Objects>''')
        schema = ET.fromstring('<Properties><Options bIgnoresVisAreas="0" bAffectsThisAreaOnly="0" bDeferredClipBounds="0"/></Properties>')
        before = ET.tostring(root)
        for name, active, linked, area in CASES:
            with self.subTest(name=name):
                result = variant(root, schema, active, linked, area)
                upper = result[0]
                self.assertEqual(upper.attrib, root[0].attrib)
                p = upper.find('Properties')
                self.assertEqual(p.get('GenOffsetY'), '-7')
                self.assertEqual(p.get('BoxSizeX'), '9.6')
                self.assertEqual(ET.tostring(p.find('Color')), ET.tostring(root[0].find('Properties/Color')))
                self.assertEqual(p.get('bActive'), str(int(active)))
                self.assertEqual(result[1].find('Properties').get('bActive'), '0')
                self.assertEqual(p.find('Options').get('bDeferredClipBounds'), str(int(linked)))
                self.assertEqual(p.find('Options').get('bAffectsThisAreaOnly'), str(int(area)))
                links = upper.findall('EntityLinks/Link')
                self.assertEqual(len(links), int(linked))
                if linked:
                    self.assertEqual(links[0].get('TargetId'), '99')
                    self.assertEqual(links[0].get('TargetGuid'), 'clip-guid')
                self.assertEqual(ET.tostring(result[2]), ET.tostring(root[2]))
                self.assertEqual(ET.tostring(result[3]), ET.tostring(root[3]))
        self.assertEqual(ET.tostring(root), before)
