import sys
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'tools'))
from character_person import shop_role_operations


def person(entity_class):
    return {'actor': ET.Element('Entity', EntityClass=entity_class)}


class ShopRoleTests(unittest.TestCase):
    def test_shopkeepers_get_native_haggle_and_ending_roles_by_sex(self):
        self.assertEqual([name for name, _ in shop_role_operations(person('NPC'))],
                         ['addShopRoles_essential_man', 'addShopRoles_ending_man'])
        self.assertEqual([name for name, _ in shop_role_operations(person('NPC_Female'))],
                         ['addShopRoles_essential_woman', 'addShopRoles_ending_woman'])

    def test_operations_take_no_attributes(self):
        for cls in ('NPC', 'NPC_Female'):
            self.assertTrue(all(attributes == {} for _, attributes in shop_role_operations(person(cls))))


if __name__ == '__main__':
    unittest.main()
