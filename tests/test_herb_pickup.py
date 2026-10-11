import sys
from pathlib import Path
import unittest
from unittest.mock import patch
import xml.etree.ElementTree as ET

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from herb_pickup import registration


class HerbRegistrationTests(unittest.TestCase):
    def tables(self, game, name):
        data = {
            'pickable_area_material': [{'material_name': 'objects/nettle.cgf', 'pickable_area_id': '2'}],
            'pickable_area_desc': [{'id': '2', 'guid_item_picked': 'abc', 'name': 'nettle'}],
            'item': [{'Id': 'abc'}],
        }
        return data[name], []

    def test_generated_paths_reuse_native_descriptor_without_decorative_rows(self):
        with patch('herb_pickup.table_rows', side_effect=self.tables):
            payload, report = registration('source', 'target', [
                {'source': 'Objects/nettle.cgf', 'target': 'glueveg/test/mesh7.cgf'},
                {'source': 'objects/tree.cgf', 'target': 'glueveg/test/mesh8.cgf'},
                {'source': 'objects/nettle.cgf', 'target': 'glueveg/test/mesh7.cgf'}])
        rows = ET.fromstring(payload).findall('./pickable_area_materials/pickable_area_material')
        self.assertEqual([r.attrib for r in rows], [dict(material_name='glueveg/test/mesh7.cgf', pickable_area_id='2')])
        self.assertFalse(report['runtime_verified'])

    def test_missing_native_item_is_logged_without_broken_registration(self):
        def missing(game, name):
            return ([], []) if name == 'item' else self.tables(game, name)
        with patch('herb_pickup.table_rows', side_effect=missing):
            payload, report = registration('source', 'target', [
                {'source': 'objects/nettle.cgf', 'target': 'glueveg/test/mesh7.cgf'}])
        self.assertEqual(len(ET.fromstring(payload)[0]), 0)
        self.assertEqual(len(report['unresolved']), 1)


if __name__ == '__main__':
    unittest.main()
