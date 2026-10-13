import sys
from pathlib import Path
import unittest
import xml.etree.ElementTree as E
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from character_job_items import reservation_contract,register_item,bind_reservation
from campaign_entity_links import append_links,native_guid


class JobItemTests(unittest.TestCase):
    def fixture(self):
        job=E.fromstring('<Entity EntityId="1" EntityGuid="00000001-0000-0000" Pos="10,20,30"><EntityLinks>'
            '<Link Name="tool" TargetId="3"/><Link Name="schedulerReservedItem[\'use\',\'job_tool\']" TargetId="2"/></EntityLinks></Entity>')
        point=E.fromstring('<Entity EntityId="2" EntityClass="TagPoint"><EntityLinks><Link TargetId="3" Name=""/></EntityLinks></Entity>')
        slot=E.fromstring('<Entity EntityId="3" EntityClass="ItemSlot"><Properties guidItemClassId="tool-id" '
            'soclass_SmartObjectHelpers="tool-helper" guidSmartObjectType="native-default"/></Entity>')
        return job,reservation_contract(job,{'2':point,'3':slot})[0]

    def source(self):
        return E.fromstring('<Entity EntityId="8" EntityGuid="18" EntityClass="ItemSlot" Pos="1,2,3">'
            '<Properties guidItemClassId="tool-id" vectorPIMatRow4="0,0,1"/></Entity>')

    def test_promotes_visual_once_and_reserves_real_item_with_native_helper(self):
        job,contract=self.fixture();mission=E.Element('Objects');mission.append(job)
        E.SubElement(mission,'Entity',Name='glue_item_8',EntityClass='GeomEntity')
        source=self.source()
        slot,report=register_item(mission,source,{'8':source},contract,{'tool-id':'converted-id'})
        self.assertEqual(slot.get('Pos'),'1,2,4')
        self.assertEqual(slot.find('Properties').get('guidItemClassId'),'converted-id')
        self.assertEqual(report['removed_visuals'],['glue_item_8'])
        self.assertEqual(slot.find('Properties').get('soclass_SmartObjectHelpers'),'tool-helper')
        again,_=register_item(mission,source,{'8':source},contract,{'tool-id':'converted-id'})
        self.assertIs(again,slot)
        links=bind_reservation(mission,job,slot,contract)
        data=append_links(None,links,allow_untagged=True)
        self.assertEqual(len(E.fromstring(data).findall('WaitingLinks/WaitingLink')),3)
        self.assertEqual(append_links(data,links,allow_untagged=True),data)
        with self.assertRaises(ValueError):append_links(None,links)

    def test_reuses_existing_player_pickup_and_preserves_ownership(self):
        job,contract=self.fixture();mission=E.Element('Objects');mission.append(job)
        source=self.source()
        existing=E.SubElement(mission,'Entity',EntityGuid=native_guid(0x18),EntityId='8',EntityClass='ItemSlot',Pos='9,8,7')
        E.SubElement(existing,'Properties',guidItemClassId='tool-id',bOnlyNPC='0',bOwnedByHome='1')
        slot,_=register_item(mission,source,{'8':source},contract,{'tool-id':'tool-id'})
        self.assertIs(slot,existing)
        self.assertEqual(slot.get('Pos'),'9,8,7')
        self.assertEqual(slot.find('Properties').get('bOwnedByHome'),'1')

    def test_missing_item_definition_or_wrong_tool_is_not_silently_substituted(self):
        _,contract=self.fixture();source=self.source()
        with self.assertRaisesRegex(ValueError,'Unregistered'):register_item(E.Element('Objects'),source,{},contract,{})
        source.find('Properties').set('guidItemClassId','another-tool')
        with self.assertRaisesRegex(ValueError,'does not match'):register_item(E.Element('Objects'),source,{},contract,{})

    def test_slot_with_placed_tool_uses_placed_transform_and_avoids_duplicate(self):
        job,contract=self.fixture();mission=E.Element('Objects');mission.append(job);source=self.source()
        E.SubElement(E.SubElement(source,'EntityLinks'),'Link',Name='SlotLink',TargetId='9')
        placed=E.fromstring('<Entity EntityId="9" EntityGuid="19" EntityClass="PickableItem" Pos="5,6,7">'
            '<Properties guidItemClassId="tool-id" bOnlyNPC="1"/></Entity>')
        for i in ('8','9'):E.SubElement(mission,'Entity',Name='glue_item_'+i)
        slot,report=register_item(mission,source,{'8':source,'9':placed},contract,{'tool-id':'tool-id'})
        self.assertEqual(slot.get('Pos'),'5,6,7')
        self.assertEqual(slot.find('Properties').get('bOnlyNPC'),'1')
        self.assertEqual(len(report['removed_visuals']),2)


if __name__=='__main__':unittest.main()
