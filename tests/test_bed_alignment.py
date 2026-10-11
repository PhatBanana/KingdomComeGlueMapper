from pathlib import Path
import sys
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from bed_alignment import alignment
from cooking_pots import rotate

SOURCE=b'''<SmartObjects><Helper className="Bed" name="sittingLeft" pos="0,-0.48,0" rot="1,0,0,0"/>
<Helper className="Bed" name="sittingRight" pos="0,0.48,0" rot="0,0,0,1"/></SmartObjects>'''
NATIVE=b'''<SmartObjects><Helper className="Bed_1Place_High" name="sittingLeft" pos="0.48,0,0" rot="0.7071068,0,0,0.7071068"/>
<Helper className="Bed_1Place_High" name="sittingRight" pos="-0.48,0,0" rot="0.7071068,0,0,-0.7071068"/></SmartObjects>'''

class BedAlignmentTests(unittest.TestCase):
    def test_both_sitting_sides_match_source_positions(self):
        offset,q=alignment(SOURCE,NATIVE)
        for p,expected in [((.48,0,0),(0,-.48,0)),((-.48,0,0),(0,.48,0))]:
            actual=rotate(q,p)
            for i in range(3):self.assertAlmostEqual(actual[i]+offset[i],expected[i],places=6)
        forward=rotate(q,(0,1,0))
        self.assertAlmostEqual(forward[0],1,places=6)
    def test_incompatible_helper_spacing_is_rejected(self):
        with self.assertRaises(ValueError):alignment(SOURCE,NATIVE.replace(b'-0.48',b'-0.9'))
    def test_missing_helper_is_rejected(self):
        with self.assertRaises(ValueError):alignment(SOURCE,b'<SmartObjects/>')

if __name__=='__main__':unittest.main()
