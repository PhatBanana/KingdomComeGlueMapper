from pathlib import Path
import sys
import unittest
import xml.etree.ElementTree as ET

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from character_person_shop import route_idle_through_work
from campaign_entity_links import guid_value
from region_travel import guid
from seating_animations import install, HELPERS, ANIMATIONS
from test_cooking_pots import archive
from lean_alignment import align


class ActivityContractTests(unittest.TestCase):
    def test_lean_alignment_preserves_authored_world_helper_not_object_origin(self):
        source = b'<SmartObjects><Helper className="LeaningSpot" name="align" pos="0,0.242,0" rot="1,0,0,0"/></SmartObjects>'
        native = b'<SmartObjects><Helper className="leaning_right" name="leaning_right" pos="0,0,0" rot="1,0,0,0"/></SmartObjects>'
        point = ET.Element('Entity', Pos='10,20,30', Rotate='0.7071067811865476,0,0,0.7071067811865476')
        converted = align(point, source, native, 'leaning_right')
        for actual, expected in zip(map(float, converted.get('Pos').split(',')), (9.758,20,30)):
            self.assertAlmostEqual(actual, expected)
        self.assertEqual(point.get('Pos'), '10,20,30')
        with self.assertRaises(ValueError): align(point, source, native, 'leaning_left')

    def test_shop_routing_preserves_executable_idle_and_position_delegate(self):
        npc = ET.Element('Entity', EntityGuid=guid('test/npc'))
        hub = ET.Element('Entity', EntityGuid=guid('test/hub'))
        actor_id = str(guid_value(npc.get('EntityGuid')))
        hub_id = str(guid_value(hub.get('EntityGuid')))
        root = ET.fromstring(f'''<database><Schedulers>
          <C_SmartHub EntityGuid="{actor_id}"><Links>
          <S_ActivityLink TargetGuid="42" PositioningDelegate="99">
          <Parameters BehaviorName="schedulerWait" Priority="0" TimeOfDayStart="0" TimeOfDayEnd="1440"/>
          </S_ActivityLink></Links></C_SmartHub><C_SmartHub EntityGuid="42"/>
          </Schedulers></database>''')
        original = ET.tostring(root.find('.//S_ActivityLink'))
        route_idle_through_work(root, npc, hub)
        route = root.find('.//S_ActivityLink')
        self.assertEqual(route.get('TargetGuid'), hub_id)
        self.assertEqual(route.get('PositioningDelegate'), '0')
        self.assertNotIn('BehaviorName', route.find('Parameters').attrib)
        leaf = root.find(f"Schedulers/C_SmartHub[@EntityGuid='{hub_id}']/Links/S_ActivityLink")
        self.assertEqual(ET.tostring(leaf), original)
        with self.assertRaisesRegex(ValueError, 'Expected native schedulerWait'):
            route_idle_through_work(root, npc, hub)

    def test_leaning_gets_helpers_and_location_validation_without_foreign_bake(self):
        identity = guid('test/lean')
        files = {'objects_mission0.xml': f'''<Objects><Entity Name="gmtravel_rattay_lean"
          EntityClass="DetailMovementSmartObject" EntityGuid="{identity}" Pos="10,20,30">
          <Properties soclass_SmartObjectHelpers="leaning_right"/></Entity></Objects>'''.encode(),
          HELPERS: b'<SmartObjectAnimationCollections><Collection HelperSetName="keep"/></SmartObjectAnimationCollections>',
          ANIMATIONS: b'<database><SmartObjectAnimationss><SmartObjectAnimations EntityGuid="123" Hash="77"/></SmartObjectAnimationss></database>'}
        donor = {HELPERS: b'<SmartObjectAnimationCollections><Collection HelperSetName="leaning_right"><Animation Fragment="Leaning_Right_In"/></Collection></SmartObjectAnimationCollections>'}
        with archive(donor) as native:
            result, report = install(files, native)
            again, _ = install(result, native)
        self.assertEqual(result, again)
        self.assertEqual(report['families'], ['leaning_right'])
        collections = ET.fromstring(result[HELPERS])
        self.assertIsNotNone(collections.find("Collection[@HelperSetName='keep']"))
        rows = ET.fromstring(result[ANIMATIONS])
        row = rows.find(f".//SmartObjectAnimations[@EntityGuid='{guid_value(identity)}']")
        self.assertEqual(row.get('AllowRuntimeAnimValidationFallback'), 'true')
        self.assertEqual(row.get('Hash'), '0')
        self.assertEqual(row.find('SmartObjectTransform').get('Position'), '10,20,30')
        self.assertEqual(rows.find(".//SmartObjectAnimations[@EntityGuid='123']").get('Hash'), '77')


if __name__ == '__main__': unittest.main()
