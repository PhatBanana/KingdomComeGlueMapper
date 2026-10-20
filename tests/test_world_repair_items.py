"""Repair kits keep their typed gameplay fields and resolve enum semantics."""
from pathlib import Path
import sys
import unittest
import xml.etree.ElementTree as E
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from test_campaign_dependencies import Tables
from world_item_definitions import WorldItemAdapter

IDENTITY='00000000-0000-0000-0000-000000000123'


class RepairItemTests(unittest.TestCase):
    def adapter(self):
        tables=Tables({'item/item':[dict(item_id=IDENTITY,item_category_id='13')],
            'item/item_category':[dict(item_category_id='13',item_category_name='ointment_item')],
            'item/ointment_item':[dict(item_id=IDENTITY,efficiency='0.5',ointment_item_type_id='1',ointment_item_subtype_id='2')],
            'item/ointment_item_type':[dict(ointment_item_type_id='1',ointment_item_type_name='repairkit')],
            'item/ointment_item_subtype':[dict(ointment_item_subtype_id='2',ointment_item_subtype_name='clothes')]})
        target={'ointment_item_type':[dict(ointment_item_type_id='7',ointment_item_type_name='repairkit')],
                'ointment_item_subtype':[dict(ointment_item_subtype_id='9',ointment_item_subtype_name='clothes')]}
        return WorldItemAdapter(tables,'containeritems',{}, {},native_tool_types=target)

    def test_repair_item_maps_names_not_ordinals_and_preserves_efficiency(self):
        adapter=self.adapter();plan=adapter.plan(IDENTITY)
        identity,files,evidence=adapter.convert(IDENTITY,plan,dict(assets={},strings={}))
        row=E.fromstring(next(iter(files.values()))).find('ItemClasses')[0]
        self.assertEqual((row.tag,row.get('Type'),row.get('SubType'),row.get('Efficiency')),
                         ('Ointment','7','9','0.5'))
        self.assertEqual(identity,IDENTITY)
        self.assertEqual(len(evidence['item_type_mappings']),2)

    def test_unknown_repair_type_blocks_conversion_instead_of_generic_loot(self):
        adapter=self.adapter();adapter.native_tool_types['ointment_item_subtype']=[]
        with self.assertRaisesRegex(ValueError,'native item type'):adapter.plan(IDENTITY)

    def test_repair_kit_icon_uses_matching_native_type_not_unrelated_ointment(self):
        adapter=self.adapter()
        for identity,kind,subtype,icon,model in [('a','1','1','wrong','valid.cgf'),
                ('b','7','9','placeholder','objects/preproduction/traffic_cone/test.cgf'),
                ('c','7','9','tailor','valid.cgf')]:
            adapter.native[identity]=E.Element('Ointment',Id=identity,Type=kind,SubType=subtype,IconId=icon,Model=model)
        plan=adapter.plan(IDENTITY)
        self.assertEqual(plan.source['presentation_template']['IconId'],'tailor')


if __name__=='__main__':unittest.main()
