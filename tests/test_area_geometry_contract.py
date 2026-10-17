import sys
from pathlib import Path
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from area_geometry_contract import normalize
from campaign_trigger_areas import TriggerArea,write_areas,read_areas

class AreaGeometryTests(unittest.TestCase):
    def fixture(self):
        blob=write_areas([TriggerArea(n,4,((0,0,0),(1,0,0),(0,1,0))) for n in (1,2)],7)
        mission=b'<Objects><Entity EntityGuid="00000001-0000-0000" EntityClass="TriggerArea"/><Entity Name="work" EntityGuid="00000002-0000-0000" EntityClass="SmartAreaShape"><Area><Points><Point Pos="0,0,0"/></Points></Area></Entity></Objects>'
        return blob,mission

    def test_retains_trigger_geometry_and_removes_only_smart_duplicate(self):
        blob,mission=self.fixture();result,removed=normalize(blob,mission)
        self.assertEqual([a.guid for a in read_areas(result)['areas']],[1])
        self.assertEqual(read_areas(result)['areas'][0],read_areas(blob)['areas'][0])
        self.assertEqual(read_areas(result)['export_version'],7)
        self.assertEqual(removed,[{'guid':2,'name':'work'}])
        self.assertEqual(normalize(result,mission,validate_only=True),(result,[]))

    def test_validation_rejects_double_registration(self):
        with self.assertRaisesRegex(ValueError,'also registered'):normalize(*self.fixture(),validate_only=True)

    def test_missing_inline_shape_or_entity_is_not_silently_removed(self):
        blob,mission=self.fixture()
        with self.assertRaisesRegex(ValueError,'without inline'):normalize(blob,mission.replace(b'<Area>',b'<Other>').replace(b'</Area>',b'</Other>'))
        with self.assertRaisesRegex(ValueError,'no entity'):normalize(blob,b'<Objects/>')
