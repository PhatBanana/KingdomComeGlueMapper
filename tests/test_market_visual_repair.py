import unittest
import xml.etree.ElementTree as E
from market_visual_repair import owned_layers, pose


class MarketLayers(unittest.TestCase):
    def fixture(self):
        mission=E.fromstring('<Objects><Entity Name="gm_schedule_anyone_42"><Properties guidSmartObjectType="seller"/></Entity></Objects>')
        areas={'a':E.fromstring('<Entity EntityClass="SmartAreaShape" EntityId="4" Layer="shop{abc}"><EntityLinks><Link Name="merchantPoint" TargetId="42"/></EntityLinks></Entity>'),
               'b':E.fromstring('<Entity EntityClass="SmartAreaShape" EntityId="5" Layer="inactive{def}"><EntityLinks><Link Name="merchantPoint" TargetId="43"/></EntityLinks></Entity>')}
        layers=E.fromstring('<Layers><Layer Name="shop{abc}" Id="8"/><Layer Name="inactive{def}" Id="9"/></Layers>')
        return mission,areas,layers

    def test_only_registered_sellers_own_restored_layers(self):
        mission,areas,layers=self.fixture()
        self.assertEqual(set(owned_layers(mission,areas,layers,'seller')),{8})
        self.assertEqual(owned_layers(mission,areas,layers,'other'),{})

    def test_ambiguous_point_fails(self):
        mission,areas,layers=self.fixture()
        areas['b'].find('EntityLinks/Link').set('TargetId','42')
        with self.assertRaisesRegex(ValueError,'ambiguous'):owned_layers(mission,areas,layers,'seller')

    def test_existing_initial_layer_is_not_duplicated(self):
        mission,areas,layers=self.fixture()
        areas['a'].set('Layer','town_state0{abc}')
        layers[0].set('Name','town_state0{abc}')
        self.assertEqual(owned_layers(mission,areas,layers,'seller'),{})

    def test_transform_retains_authored_rotation_and_scale(self):
        p,q,s=pose((0,-3,0,100,2,0,0,200,0,0,4,30))
        self.assertEqual(p,(100,200,30))
        self.assertEqual(s,(2,3,4))
        self.assertAlmostEqual(q[0],2**-.5)
        self.assertAlmostEqual(q[3],2**-.5)

    def test_shear_fails_instead_of_moving_geometry(self):
        with self.assertRaises(ValueError):pose((1,1,0,0,0,1,0,0,0,0,1,0))
