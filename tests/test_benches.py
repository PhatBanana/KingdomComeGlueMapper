from pathlib import Path
import sys
import unittest
import xml.etree.ElementTree as E

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from benches import convert
from campaign_entity_links import guid_value
from region_travel import guid
from test_cooking_pots import archive


class BenchTests(unittest.TestCase):
    def build(self, previous=None, area=(10,20,30,10), incremental=False):
        source = b'''<Objects><Entity EntityId="1" EntityClass="SmartObjectHolder" Pos="10,20,30" Rotate="0.707106781,0,0,0.707106781">
          <Properties soclasses_SmartObjectHelpers="Bench_2Place"><Script Misc="hasTable:true"/></Properties></Entity>
          <Entity EntityId="2" EntityClass="SmartObjectHolder" Pos="1000,0,0"><Properties soclasses_SmartObjectHelpers="Bench_2Place"/></Entity></Objects>'''
        helpers = b'''<SmartObjects><Helper className="Bench_2Place" name="Place0" pos="-0.35,0,0" description="Category(Sit);"/>
          <Helper className="Bench_2Place" name="Place1" pos="0.35,0,0" description="Category(Sit);"/></SmartObjects>'''
        native = E.Element('Objects'); animations = E.Element('SmartObjectAnimationCollections')
        for i, suffix in enumerate(('Right', 'Left', 'Low')):
            key = str(100+i*2); target = str(101+i*2)
            family = 'Sit_1Place_Bench_Low' if suffix == 'Low' else 'Sit_1Place_Bench_Low_Table_'+suffix
            e = E.SubElement(native, 'Entity', EntityId=key, EntityClass='StanceSmartObject', Pos='0,0,0')
            E.SubElement(e, 'Properties', soclass_SmartObjectHelpers=family, bOwnedByHome='1')
            links = E.SubElement(e, 'EntityLinks'); E.SubElement(links, 'Link', Name='', TargetId=target)
            E.SubElement(links, 'Link', Name='oppositeNeighbor', TargetId='999')
            trigger = E.SubElement(native, 'Entity', EntityId=target, EntityClass='ActionTrigger', Pos='0,0,0.45')
            E.SubElement(E.SubElement(trigger, 'Properties'), 'Click', UseMessage='@ui_use_sit')
            E.SubElement(animations, 'Collection', HelperSetName=family)
        files = {'objects_mission0.xml': b'<Objects><Entity Name="original_bench_geometry" EntityId="1"/></Objects>',
                 'tables/ai/smartobjectanimations.xml': b'<database><SmartObjectAnimationss version="1"><SmartObjectAnimations EntityGuid="999" Hash="123"/></SmartObjectAnimationss></database>'}
        with archive({'objects_mission0.xml': source}) as src, archive({'objects_mission0.xml': E.tostring(native),
                'smartobjecthelpersetanimations.xml': E.tostring(animations)}) as target:
            return convert(previous or files, src, target, helpers, guid, area, incremental=incremental)

    def test_expanding_test_area_adds_only_missing_seats(self):
        original, _ = self.build()
        expanded, report = self.build(original, area=None, incremental=True)
        self.assertEqual(report['converted_benches'], 1)
        self.assertEqual(report['records'][0]['source_id'], '2')
        before = list(E.fromstring(original['objects_mission0.xml']))
        after = list(E.fromstring(expanded['objects_mission0.xml']))
        self.assertEqual([E.tostring(e) for e in before], [E.tostring(e) for e in after[:len(before)]])
        again, report = self.build(expanded, area=None, incremental=True)
        self.assertEqual(report['places'], 0)
        self.assertEqual(again['objects_mission0.xml'], expanded['objects_mission0.xml'])
        root = E.fromstring(expanded['objects_mission0.xml'])
        root.remove(next(e for e in root if e.get('EntityClass') == 'ActionTrigger'))
        expanded['objects_mission0.xml'] = E.tostring(root)
        with self.assertRaisesRegex(ValueError, 'Incomplete seating'):
            self.build(expanded, area=None, incremental=True)

    def test_source_seat_positions_native_roles_and_geometry(self):
        files, report = self.build()
        self.assertEqual(report['converted_benches'], 1)
        self.assertEqual(report['places'], 2)
        nodes = list(E.fromstring(files['objects_mission0.xml']))
        self.assertEqual(nodes[0].get('Name'), 'original_bench_geometry')
        seats = [e for e in nodes if e.get('EntityClass') == 'StanceSmartObject']
        self.assertEqual({e.get('Pos') for e in seats}, {'10,19.65,30','10,20.35,30'})
        ids = {e.get('EntityId'):e.get('EntityGuid') for e in nodes}
        for seat in seats:
            self.assertEqual(seat.find('Properties').get('bOwnedByHome'), '0')
            self.assertEqual({l.get('Name') for l in seat.findall('EntityLinks/Link')}, {'','neighbor','withTable'})
        for node in nodes:
            for link in node.findall('EntityLinks/Link'):
                self.assertEqual(ids[link.get('TargetId')], link.get('TargetGuid'))

    def test_animation_contract_has_helpers_and_fresh_local_validation(self):
        files, _ = self.build()
        helpers = E.fromstring(files['smartobjecthelpersetanimations.xml'])
        self.assertEqual(len(helpers), 2)
        table = E.fromstring(files['tables/ai/smartobjectanimations.xml'])
        self.assertIsNotNone(table.find("SmartObjectAnimationss/SmartObjectAnimations[@EntityGuid='999'][@Hash='123']"))
        for seat in E.fromstring(files['objects_mission0.xml']):
            if seat.get('EntityClass') != 'StanceSmartObject': continue
            row = table.find(f"SmartObjectAnimationss/SmartObjectAnimations[@EntityGuid='{guid_value(seat.get('EntityGuid'))}']")
            self.assertEqual(row.get('AllowRuntimeAnimValidationFallback'), 'true')
            self.assertEqual(row.find('SmartObjectTransform').get('Position'), seat.get('Pos'))
            self.assertIsNone(row.find('Animations')) # No Trosky baked positions or DropReasons.


if __name__ == '__main__': unittest.main()
