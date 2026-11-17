"""Selling poses for keepers with several merchantPoints, the bathhouse abbess and innkeepers."""
from pathlib import Path
import sys
import tempfile
import unittest
import xml.etree.ElementTree as E
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'tools'))
from character_market_jobs import resolve, supports
from character_inn_work import choose, lean_side, supports as inn_supports
from source_merchant_upgrade import service_role

SHOP = dict(tree_file='final/sa_shop2.xml', tree_name='merchant')
ABBESS = dict(tree_file='Final\\sa_bathhouse.xml', tree_name='Abbess')
INN = dict(tree_file='final/sa_pub_v3.xml', tree_name='Innkeeper')


def run(entities, links, behavior=SHOP):
    mission = E.Element('Objects')
    for identity, kind, pos in entities:
        E.SubElement(mission, 'Entity', EntityId=identity, EntityClass=kind, Pos=pos, Name='e' + identity)
    entry = dict(area=dict(EntityId='99'), behavior=behavior,
                 target_links=[dict(Name=name, TargetId=identity) for name, identity in links])
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp)/'level.pak'
        with zipfile.ZipFile(path, 'w') as z: z.writestr('objects_mission0.xml', E.tostring(mission))
        with zipfile.ZipFile(path) as z: return resolve(entry, z)


class MerchantPoints(unittest.TestCase):
    def test_single_point_is_unchanged(self):
        result = run([('1', 'TagPoint', '1,1,1')], [('merchantPoint', '1')])
        self.assertEqual(result['arrival']['Pos'], '1,1,1')
        self.assertNotIn('market_alternates', result)

    def test_shop_marker_linked_as_merchant_point_is_not_a_pose(self):
        result = run([('1', 'Shop', '1,1,1'), ('2', 'TagPoint', '2,2,2'), ('3', 'TagPoint', '3,3,3')],
                     [('merchantPoint', '1'), ('merchantPoint', '2'), ('inside', '3')])
        self.assertEqual(result['arrival']['Pos'], '2,2,2')
        self.assertEqual([a['EntityId'] for a in result['market_alternates']], ['1'])

    def test_several_poses_keep_the_area_arrival(self):
        result = run([('1', 'TagPoint', '1,1,1'), ('2', 'TagPoint', '2,2,2')],
                     [('merchantPoint', '1'), ('merchantPoint', '2'), ('inside', '2')])
        self.assertEqual(result['arrival']['Pos'], '2,2,2')
        self.assertEqual([a['EntityId'] for a in result['market_alternates']], ['1'])

    def test_several_poses_without_an_arrival_pose_stay_unresolved(self):
        with self.assertRaisesRegex(ValueError, 'area arrival, found 0'):
            run([('1', 'TagPoint', '1,1,1'), ('2', 'TagPoint', '2,2,2'), ('3', 'TagPoint', '3,3,3')],
                [('merchantPoint', '1'), ('merchantPoint', '2'), ('inside', '3')])

    def test_only_shop_markers_have_no_pose(self):
        with self.assertRaisesRegex(ValueError, 'converted point contract'):
            run([('1', 'Shop', '1,1,1'), ('2', 'Shop', '2,2,2')], [('merchantPoint', '1'), ('merchantPoint', '2')])
        with self.assertRaisesRegex(ValueError, 'converted point contract'):
            run([('1', 'Shop', '1,1,1')], [('merchantPoint', '1')])

    def test_missing_point_still_fails(self):
        with self.assertRaisesRegex(ValueError, 'authored merchant selling point'):
            run([('1', 'TagPoint', '1,1,1')], [('inside', '1')])


class Abbess(unittest.TestCase):
    def test_abbess_sells_at_her_work_spot(self):
        self.assertTrue(supports(dict(behavior=ABBESS)))
        result = run([('1', 'TagPoint', '1,1,1'), ('2', 'TagPoint', '2,2,2')],
                     [('abbessWorkSpot', '1'), ('inside', '2'), ('merchantPoint', '2')], ABBESS)
        self.assertEqual(result['arrival']['Pos'], '1,1,1')
        self.assertTrue(result['market_work'])

    def test_abbess_needs_exactly_one_work_spot(self):
        with self.assertRaisesRegex(ValueError, 'authored merchant selling point'):
            run([('1', 'TagPoint', '1,1,1'), ('2', 'TagPoint', '2,2,2')],
                [('abbessWorkSpot', '1'), ('abbessWorkSpot', '2')], ABBESS)
        with self.assertRaisesRegex(ValueError, 'authored merchant selling point'):
            run([('1', 'TagPoint', '1,1,1')], [('inside', '1')], ABBESS)


class Innkeeper(unittest.TestCase):
    def test_only_the_innkeeper_tree_is_an_inn_job(self):
        self.assertTrue(inn_supports(dict(behavior=INN)))
        self.assertFalse(inn_supports(dict(behavior=dict(INN, tree_name='Bartender'))))
        self.assertFalse(supports(dict(behavior=INN)))

    def test_lean_side_comes_from_the_authored_flags(self):
        point = E.fromstring('<Entity><Properties><Script Misc="leanBack:false|leanLeft:true|leanRight:false"/></Properties></Entity>')
        self.assertEqual(lean_side(point), 'leaning_left')
        point.find('Properties/Script').set('Misc', 'leanBack:true|leanLeft:false|leanRight:true')
        self.assertEqual(lean_side(point), 'leaning_back')
        point.find('Properties/Script').set('Misc', 'leanBack:false|leanLeft:true|leanRight:true')
        with self.assertRaisesRegex(ValueError, 'source lean direction'): lean_side(point)

    def test_pub_owned_spot_nearest_the_arrival_wins(self):
        spot = lambda identity, pos: (E.Element('Entity', EntityId=identity), E.Element('Entity', Pos=pos))
        street, inside_far, inside_near = spot('1', '0,0,0'), spot('2', '9,0,0'), spot('3', '4,0,0')
        self.assertEqual(choose([street, inside_far, inside_near], (0, 0, 0), {'1'})[0].get('EntityId'), '3')
        self.assertEqual(choose([street, inside_far, inside_near], (0, 0, 0))[0].get('EntityId'), '1')
        self.assertEqual(choose([street], (0, 0, 0), {'1'})[0].get('EntityId'), '1')

    def test_shop_role_follows_the_work_kind(self):
        self.assertEqual(service_role([dict(inn_work={})]), 'innkeeper')
        self.assertEqual(service_role([dict(market_work=True)]), 'seller')
        with self.assertRaisesRegex(ValueError, 'Mixed'):
            service_role([dict(inn_work={}), dict(market_work=True)])


if __name__ == '__main__':
    unittest.main()
