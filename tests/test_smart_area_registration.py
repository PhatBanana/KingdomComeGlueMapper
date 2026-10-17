import sys
from pathlib import Path
import unittest
import xml.etree.ElementTree as ET
sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'tools'))
from smart_area_registration import reconcile


class RegistrationTests(unittest.TestCase):
    metadata = b'<Root><SoulList/><AI><SmartAreaManager version="2"><SmartAreas><SmartArea><Guid>12</Guid><Extra>keep</Extra></SmartArea></SmartAreas></SmartAreaManager></AI></Root>'
    mission = b'<Objects><Entity EntityClass="SmartAreaShape" EntityGuid="0000000a-0000-0000"/><Entity EntityClass="TriggerArea" EntityGuid="0000000b-0000-0000"/></Objects>'

    def test_adds_only_missing_smart_areas_and_preserves_other_registrations(self):
        fixed, missing = reconcile(self.metadata, self.mission)
        self.assertEqual(missing, [10])
        root = ET.fromstring(fixed)
        self.assertEqual([int(g.text) for g in root.findall('.//Guid')], [12, 10])
        self.assertEqual(root.findtext('.//Extra'), 'keep')
        self.assertIsNotNone(root.find('SoulList'))
        self.assertEqual(reconcile(fixed, self.mission), (fixed, []))
        reconcile(fixed, self.mission, validate_only=True)

    def test_setup_rejects_missing_registration(self):
        with self.assertRaisesRegex(ValueError, 'Unregistered'):
            reconcile(self.metadata, self.mission, validate_only=True)

    def test_rejects_missing_manager_and_duplicate_registration(self):
        with self.assertRaisesRegex(ValueError, 'Missing'):
            reconcile(b'<Root/>', self.mission)
        duplicate = self.metadata.replace(b'</SmartAreas>', b'<SmartArea><Guid>12</Guid></SmartArea></SmartAreas>')
        with self.assertRaisesRegex(ValueError, 'Duplicate'):
            reconcile(duplicate, self.mission)
