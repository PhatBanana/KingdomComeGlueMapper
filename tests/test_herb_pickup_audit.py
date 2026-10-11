import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from audit_herb_pickup import compare


class HerbPickupAuditTests(unittest.TestCase):
    def test_matching_ids_do_not_hide_missing_model_registration(self):
        descriptor = {'id': '2', 'guid_item_picked': 'ABC'}
        desc, models = compare([descriptor], [descriptor],
                               [{'material_name': 'objects/old/nettle.cgf', 'pickable_area_id': '2'}],
                               [{'material_name': 'objects/new/nettle.cgf', 'pickable_area_id': '2'}],
                               [{'Id': 'abc', '_type': 'Herb', 'Name': 'nettle'}])
        self.assertEqual(desc[0]['issues'], [])
        self.assertEqual(models[0]['issues'], ['source_model_path_not_registered'])

    def test_id_collision_and_missing_item_are_reported(self):
        desc, _ = compare([{'id': '2', 'guid_item_picked': 'abc'}],
                          [{'id': '2', 'guid_item_picked': 'different'}], [], [], [])
        self.assertEqual(desc[0]['issues'], ['descriptor_item_mismatch', 'missing_target_item'])


if __name__ == '__main__':
    unittest.main()
