import sys
from pathlib import Path
import unittest
import xml.etree.ElementTree as E

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from campaign_dialogue_world import area_references, merge_areas
from campaign_trigger_areas import TriggerArea, read_areas, write_areas


class DialogueWorldTests(unittest.TestCase):
    def test_discovers_expanded_area_conditions_without_reading_string_contents_as_code(self):
        model = dict(functions={'inYard': "IsActorInside('yard')[1]"}, topics={'x':dict(sequences=[
            dict(entry={'entry_condition': "inYard AND var('IsActorInside') == 1"}, effects=[])])})
        self.assertEqual(area_references([model]), {'yard'})

    def test_world_vertices_and_existing_entities_are_preserved_and_merge_is_idempotent(self):
        shape = TriggerArea(32, 4, ((100,200,30),(105,200,30),(105,206,30)))
        native = write_areas([TriggerArea(10,2,((1,1,1),(2,2,2)))], 77)
        source = write_areas([shape], 88)
        entity = E.fromstring('<Entity Name="yard" EntityClass="TriggerArea" EntityGuid="0000000000000020" Pos="100,200,30" Rotate="0,0,0,1"/>')
        mission = b'<Objects><Entity Name="existing" EntityId="7" EntityGuid="0000000a-0000-0000"/></Objects>'
        changed, data, report = merge_areas(mission,native,source,[entity],{'yard'})
        self.assertEqual(read_areas(data)['export_version'],77)
        self.assertEqual(read_areas(data)['areas'][1].points,shape.points)
        self.assertEqual(E.tostring(E.fromstring(changed)[0]),E.tostring(E.fromstring(mission)[0]))
        again, second, receipts = merge_areas(changed,data,source,[entity],{'yard'})
        self.assertEqual((changed,data),(again,second))
        self.assertTrue(receipts[0]['reused'])

    def test_missing_or_ambiguous_sources_fail(self):
        native = write_areas([],1)
        entity = E.fromstring('<Entity Name="yard" EntityClass="TriggerArea" EntityGuid="0000000000000020"/>')
        for records in ([],[entity,entity],[entity]):
            with self.assertRaises(ValueError):
                merge_areas(b'<Objects/>',native,native,records,{'yard'})


if __name__ == '__main__': unittest.main()
