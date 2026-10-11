import sys
from pathlib import Path
import tempfile
import unittest
import xml.etree.ElementTree as ET

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from character_female_body import complete_source_body
from merchant_stash import apply_stash_placement


class StableVisualTests(unittest.TestCase):
    def test_complete_body_uses_matching_source_family_for_any_actor(self):
        source = 'objects/characters/humans/body/s2_body.skin'
        complete = source.replace('s2_body.skin', 's2_body_v2.skin')
        self.assertEqual(complete_source_body(source, {complete}), complete)
        self.assertEqual(complete_source_body(source.upper(), {complete}), complete)
        # Bespoke bodies and male imports must not be substituted.
        for name in ('s2_body_tereza.skin', 's1_body.skin'):
            self.assertEqual(complete_source_body(name, {}), name)
        with self.assertRaises(ValueError):
            complete_source_body(source, {})

    def test_stash_uses_authored_placement_without_losing_shop_stock_or_identity(self):
        stash = ET.fromstring('<Entity Pos="1,2,30" EntityGuid="stable-id"><Properties><Database sGeneratedInventory="shop-stock"/><Lock bLocked="1"/></Properties><EntityLinks><Link Name="shop"/></EntityLinks></Entity>')
        authored = ET.fromstring('<Entity Pos="4,5,6" Rotate="1,0,0,0"><Properties object_Model="objects/chest.cga" fUseDistance="2.5"><Animation anim_Open="open"/><Physics bRigidBody="1" bPhysicalize="1"/></Properties></Entity>')
        apply_stash_placement(stash, authored, 'objects/imported/')
        self.assertEqual(stash.get('Pos'), '4,5,6')
        self.assertEqual(stash.get('EntityGuid'), 'stable-id')
        self.assertEqual(stash.find('Properties/Database').get('sGeneratedInventory'), 'shop-stock')
        self.assertEqual(stash.find('Properties').get('object_Model'), 'objects/imported/chest.cga')
        self.assertIsNotNone(stash.find('EntityLinks/Link'))
        self.assertEqual(stash.find('Properties/Physics').get('bRigidBody'), '0')


if __name__ == '__main__':
    unittest.main()
