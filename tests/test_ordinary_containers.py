import copy
import sys
from pathlib import Path
import unittest
import xml.etree.ElementTree as ET

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'tools'))
from container_audit import inventory_policy, source_guid
from ordinary_containers import eligibility, register
from region_travel import guid


class OrdinaryContainersTests(unittest.TestCase):
    def setUp(self):
        self.record = dict(source_id='12', kind='chest', protected_roles=[], hidden=False,
            inventory_status='no_authored_inventory', phase={}, link_definitions=['owner'],
            model='objects/chest_03/chest.cga', position=[1,2,3], rotation=[1,0,0,0], scale=[1,1,1],
            lock={'bLocked':'1','bCanLockPick':'1','bLockDifficultyOverride':'0'},
            source_properties='<Properties><Animation anim_Open="open" anim_Close="close"/></Properties>')
        self.files = {'objects_mission0.xml': b'<Objects><Entity EntityId="30582" Name="glue_item_12"/><Entity EntityId="3" Name="keep"/></Objects>',
                      'waitinglinks.xml': b'unchanged links', 'whdata_0': b'unchanged souls'}

    def test_no_authored_inventory_is_distinct_from_converted_loot(self):
        for identifier in ('0', '', '00000000-0000-0000-0000-000000000000'):
            self.assertEqual(inventory_policy(identifier,{})['status'], 'no_authored_inventory')
        self.assertEqual(source_guid('123'),0x123)
        self.assertEqual(source_guid('00000123-0000-0000'),0x123)

    def test_protected_and_unconverted_contracts_are_rejected(self):
        for change in ({'hidden':True}, {'protected_roles':['merchant_stock']},
                       {'link_definitions':['masterStash']}, {'inventory_status':'requires_conversion'},
                       {'phase':{'bChangeAfterPlayerInteract':'1'}}, {'lock':{'guidItemClassId':'key'}}):
            record = dict(self.record, **change)
            self.assertIsNotNone(eligibility(record))
            with self.assertRaises(ValueError): register(self.files,[record],{},guid)

    def test_unowned_empty_storage_preserves_placement_animation_and_lock(self):
        before = copy.deepcopy(self.files)
        result, report = register(self.files,[self.record],{self.record['model']:'converted.cga'},guid)
        node = ET.fromstring(result['objects_mission0.xml']).find("Entity[@Name='gm_container_12']")
        self.assertEqual(node.get('EntityId'),'30584')  # Skip reserved player 0x7777.
        self.assertEqual(node.get('Pos'),'1,2,3')
        self.assertIsNone(node.find('EntityLinks'))
        props=node.find('Properties')
        self.assertEqual(props.get('bOwnedByHome'),'0')
        self.assertEqual(props.find('Database').get('sGeneratedInventory'),'')
        self.assertEqual(props.find('Database').get('nDestockPeriodDays'),'0')
        self.assertEqual(props.find('Lock').get('fLockDifficulty'),'.8')
        self.assertEqual(props.find('Lock').get('bLocked'),'1')
        self.assertEqual(props.find('Animation').get('anim_Open'),'open')
        self.assertEqual(result['waitinglinks.xml'],before['waitinglinks.xml'])
        self.assertEqual(self.files,before)
        self.assertEqual(report['converted'],1)
        root=ET.fromstring(result['objects_mission0.xml'])
        self.assertIsNone(root.find("Entity[@Name='glue_item_12']"))
        self.assertIsNotNone(root.find("Entity[@Name='keep']"))
        with self.assertRaises(ValueError): register(result,[self.record],{self.record['model']:'converted.cga'},guid)

    def test_missing_static_and_duplicate_selection_fail_closed(self):
        with self.assertRaises(ValueError): register(self.files,[self.record,self.record],{},guid)
        files=dict(self.files, objects_mission0_xml=b'')
        files['objects_mission0.xml']=b'<Objects/>'
        with self.assertRaises(ValueError): register(files,[self.record],{},guid)


if __name__=='__main__': unittest.main()
