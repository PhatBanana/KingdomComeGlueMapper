import sys
from pathlib import Path
import unittest
import xml.etree.ElementTree as E
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from campaign_dependency_adapters import EntityAdapter
from campaign_dependencies import DependencyImporter
from campaign_entity_links import native_guid
from campaign_trigger_areas import write_areas
from quest_import import ast
from campaign_link_types import convert_world_links


def record(text):
    e=E.fromstring(text)
    return dict(source='mission.xml',attributes=dict(e.attrib),entity=ast(e))


class WorkItemTests(unittest.TestCase):
    def fixtures(self):
        return {'slot':record('<Entity EntityId="1" EntityGuid="0000000000000001" EntityClass="ItemSlot" '
            'Name="arbitrary-tool" Pos="1,2,3"><EntityLinks><Link Name="SlotLink" TargetId="2" '
            'TargetGuid="0000000000000002"/></EntityLinks><Properties guidItemClassId="tool" bSpawnOnStart="1" '
            'bSlotMagnetism="1"><Script esHand="Right" Misc=""/></Properties></Entity>'),
            'pickup':record('<Entity EntityId="2" EntityGuid="0000000000000002" EntityClass="PickableItem" '
            'Name="physical-tool" Pos="4,5,6"><Properties guidItemClassId="tool" bOnlyNPC="1" fHealth="0.8"/></Entity>')}

    def importer(self,records):
        adapter=EntityAdapter(dict(entities=records),E.fromstring('<Root/>'),write_areas([],1),1)
        return DependencyImporter({'entities':adapter},{'items':{'tool':'native-tool'}})

    def test_pickup_and_slot_become_one_persistent_tool(self):
        i=self.importer(self.fixtures())
        self.assertEqual(i.ensure('entities',native_guid(2)),native_guid(1))
        self.assertEqual(i.ensure('entities',native_guid(1)),native_guid(1))
        self.assertEqual(len(i.files),1)
        e=E.fromstring(next(iter(i.files.values())))
        self.assertEqual(e.get('Pos'),'4,5,6')
        self.assertEqual(e.find('Properties').get('guidItemClassId'),'native-tool')
        self.assertEqual(e.find('Properties').get('bSaveBorrowedItem'),'1')
        self.assertEqual(e.find('Properties').get('bOnlyNPC'),'1')
        self.assertEqual(e.find('Properties').get('ItemHealth'),'0.8')

    def test_mismatched_item_cannot_register_either_identity(self):
        records=self.fixtures()
        records['pickup']['entity']['children'][0]['attributes']['guidItemClassId']='other'
        i=self.importer(records)
        self.assertIsNone(i.ensure('entities',native_guid(2)))
        self.assertFalse(i.files)

    def test_guid_only_tool_link_registers_the_physical_item_alias(self):
        records = self.fixtures()
        del records['slot']['entity']['children'][0]['children'][0]['attributes']['TargetId']
        i = self.importer(records)
        self.assertEqual(i.ensure('entities',native_guid(2)), native_guid(1))
        self.assertEqual(len(i.files), 1)

    def test_disagreeing_link_id_does_not_register_slot(self):
        records = self.fixtures()
        records['slot']['entity']['children'][0]['children'][0]['attributes']['TargetId'] = '99'
        i = self.importer(records)
        self.assertIsNone(i.ensure('entities', native_guid(1)))
        self.assertIn('GUID and ID disagree', i.jobs[('entities',native_guid(1))]['error'])

    def test_slot_link_consumed_only_with_verified_item_alias(self):
        records = self.fixtures()
        i = self.importer(records)
        i.ensure('entities', native_guid(2))
        world = dict(entities=records, links=[dict(
            **{'from':'slot','to':'pickup'}, source_link={'Name':'SlotLink'})])
        links, report = convert_world_links(world, i, {native_guid(1)})
        self.assertEqual(links, [])
        self.assertEqual(report['pending'], [])
        self.assertEqual(report['resolved'][0]['consumed_by'], 'native tool-slot item ownership')
        i.jobs[('entities',native_guid(2))]['evidence'] = {}
        _, report = convert_world_links(world, i, {native_guid(1)})
        self.assertEqual(len(report['pending']), 1)

    def test_unlinked_slot_preserves_local_item_transform(self):
        records=self.fixtures();records.pop('pickup')
        records['slot']['entity']['children'].pop(0)
        records['slot']['entity']['children'][0]['attributes']['vectorPIMatRow4']='0,0,2'
        i=self.importer(records)
        self.assertEqual(i.ensure('entities',native_guid(1)),native_guid(1))
        self.assertEqual(E.fromstring(next(iter(i.files.values()))).get('Pos'),'1,2,5')


if __name__=='__main__':unittest.main()
