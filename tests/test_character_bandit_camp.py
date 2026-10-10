import sys
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'tools'))
from character_bandit_camp import faction_patch
from region_travel_tables import managed_patches


class BanditCampTests(unittest.TestCase):
    def test_destination_binding_preserves_enemy_inheritance_without_editing_native_tree(self):
        tree = ET.fromstring('<database><FactionTree version="1"><Faction Name="enemies"><Children>'
            '<Faction Name="native_region" LevelId="2" Labels="publicEnemy"><Relations>'
            '<Relation target="civilians" reputation="-1"/></Relations><Children>'
            '<Faction Name="native_camp" LocationId="old-camp" Labels="camp"/>'
            '</Children></Faction></Children></Faction></FactionTree></database>')
        before = ET.tostring(tree)
        data, name = faction_patch(tree, 'native_camp', 'test', 1001, 'local-camp')
        converted = ET.fromstring(data)
        leaf = next(f for f in converted.iter('Faction') if f.get('Name') == name)
        self.assertEqual(leaf.get('LocationId'), 'local-camp')
        self.assertEqual(leaf.get('LevelId'), '1001')
        self.assertEqual(leaf.find("Relations/Relation[@target='player']").get('reputation'), '-1')
        self.assertTrue(any(f.get('Labels') == 'publicEnemy' for f in converted.iter('Faction')))
        self.assertTrue(any(r.get('target') == 'civilians' for r in converted.iter('Relation')))
        self.assertNotIn(b'old-camp', data)
        self.assertNotIn(b'LevelId="2"', data)
        self.assertEqual(ET.tostring(tree), before)
        merged = managed_patches({'Libs/Tables/rpg/FactionTree__test.xml': data}, 'mod')
        self.assertIn('Libs/Tables/rpg/FactionTree__mod.xml', merged)

    def test_non_enemy_template_is_rejected(self):
        with self.assertRaisesRegex(ValueError, 'not a native public enemy'):
            faction_patch(ET.fromstring('<Faction Name="civilian"/>'), 'civilian', 'test', 1001, 'camp')


if __name__ == '__main__': unittest.main()
