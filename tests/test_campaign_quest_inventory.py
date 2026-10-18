import copy
import sys
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'tools'))
from campaign_quest_inventory import split
from container_loot import compile_inventory


class QuestInventoryTests(unittest.TestCase):
    def inventory(self):
        return dict(source_id='inventory-x', status='resolved', definition={},
                    item_dependencies=['reward', 'food'], preset_choices=[], direct_items=[
            dict(item_id='reward', amount='1', amount_random_add='2', health='1'),
            dict(item_id='food', amount='4', amount_random_add='0', health='1')])

    def test_split_keeps_normal_loot_and_source_immutable(self):
        source = self.inventory(); before = copy.deepcopy(source)
        regular, rows = split(source, {'reward'})
        self.assertEqual(source, before)
        self.assertEqual([r['item_id'] for r in rows], ['reward'])
        root, _, _ = compile_inventory(regular, {'food':'food'}, {'food':'bread'})
        self.assertEqual([r.get('Name') for r in root.iter('PresetItem')], ['bread'])

    def test_unsupported_weighted_quest_selection_rejected(self):
        source = self.inventory()
        source['preset_choices'] = [dict(items=[dict(item_id='reward')])]
        with self.assertRaisesRegex(ValueError, 'weighted'):
            split(source, {'reward'})

    def test_unsupported_quantity_and_health_rejected(self):
        for field,value in [('amount','0'), ('amount','1.5'), ('health_offset','0.1')]:
            source = self.inventory(); source['direct_items'][0][field] = value
            with self.assertRaises(ValueError): split(source, {'reward'})


if __name__ == '__main__': unittest.main()
