"""Regression checks for native pickups and source identity preservation."""
from contextlib import contextmanager
import tempfile
from pathlib import Path
import sys
import unittest
import xml.etree.ElementTree as E
import zipfile
import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from world_item_inventory import collect, item_id
from world_item_placements import convert,placement_transform,rotation
from static_assets import character_definition
from world_item_definitions import native_item_registry, WorldItemAdapter
from campaign_dependencies import ImportPlan


def entity(identity='1', cls='PickableItem', **props):
    e=E.Element('Entity',EntityId=identity,EntityGuid=f'{int(identity):016x}',EntityClass=cls,
                Name='source_'+identity,Pos='1,2,3')
    E.SubElement(e,'Properties',dict(guidItemClassId='ITEM ',**props))
    return e


@contextmanager
def archive(nodes):
    root=E.Element('root');root.extend(nodes)
    with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1]) as tmp:
        path=Path(tmp)/'level.pak'
        with zipfile.ZipFile(path,'w') as z:z.writestr('objects_mission0.xml',E.tostring(root))
        with zipfile.ZipFile(path) as z:yield z


class WorldItemsTests(unittest.TestCase):
    def test_retired_native_placeholder_is_imported_with_distinct_reusable_identity(self):
        identity = '36235c05-a733-484b-872d-eecdc245a7de'
        bad = E.Element('NPCTool', Id=identity, Name='sausage_smoked',
                        Model='preproduction/traffic_cone/traffic_cone')
        native = {identity:bad}
        self.assertNotIn(identity, native_item_registry(native))
        adapter = WorldItemAdapter(None, 'worlditems', native, {})
        rows = {name:{} for name in adapter.FIELDS}
        rows.update(item={}, pickable_item={'model':'props/food/sausage.cgf'},
                    npc_tool={'npc_tool_type_id':'1'})
        plan = ImportPlan([], dict(category='npc_tool', rows=rows))
        target, files, evidence = adapter.convert(identity, plan,
            {'assets':{'objects/props/food/sausage.cgf':'objects/converted/sausage.cgf'},'strings':{}})
        self.assertNotEqual(target,identity)
        row = E.fromstring(next(iter(files.values()))).find('ItemClasses')[0]
        self.assertEqual(row.get('Model'),'converted/sausage.cgf')
        self.assertTrue(evidence['replaced_native_placeholder'])
        native[target] = row
        self.assertEqual(native_item_registry(native)[identity], target)

    def test_pickup_classification_deduplicates_slots_and_preserves_restrictions(self):
        placed=entity();slot=entity('2','ItemSlot')
        E.SubElement(E.SubElement(slot,'EntityLinks'),'Link',Name='SlotLink',TargetId='1')
        npc=entity('3',bOnlyNPC='true');disabled=entity('4','ItemSlot',bSpawnOnStart='0')
        inactive=entity('5');inactive.set('Layer','quest_state1')
        with archive([placed,slot,npc,disabled,inactive]) as z:
            _,p,audit=collect(z)
        self.assertEqual([p['entity'].get('EntityId') for p in p],['1'])
        self.assertEqual(p[0]['item_id'],'item')
        self.assertEqual(audit['restriction_counts'],dict(slot_has_placed_item=1,source_npc_only=1,source_slot_not_initially_spawned=1))
        self.assertEqual(len(audit['inactive']),1)

    def test_native_slots_replace_only_matching_visuals_and_keep_source_guid(self):
        source=entity();record=dict(entity=source,item_id='item',position=(1,2,3),rotation=(1,0,0,0),scale=(1,1,1))
        files={'objects_mission0.xml':b'<root><Entity Name="glue_item_1" EntityId="20"/><Entity Name="keep" EntityId="21"/></root>',
               'whdata_0':b'unchanged'}
        result,report=convert(files,[record],{'item':'native-item'})
        r=E.fromstring(result['objects_mission0.xml']);slot=r.find("Entity[@EntityClass='ItemSlot']")
        self.assertEqual(slot.get('EntityGuid'),'00000001-0000-0000')
        self.assertEqual(slot.find('Properties').get('guidItemClassId'),'native-item')
        self.assertEqual(slot.find('Properties').get('nRestockPeriodDays'),'0')
        self.assertEqual(slot.find('Properties').get('bSaveBorrowedItem'),'1')
        self.assertIsNone(r.find("Entity[@Name='glue_item_1']"));self.assertIsNotNone(r.find("Entity[@Name='keep']"))
        self.assertEqual(result['whdata_0'],b'unchanged');self.assertEqual(report['visuals_replaced'],1)
        with self.assertRaisesRegex(ValueError,'already installed'):convert(result,[record],{'item':'native-item'})

    def test_missing_item_definition_does_not_remove_visual(self):
        source=entity();record=dict(entity=source,item_id='item',position=(1,2,3),rotation=(1,0,0,0),scale=(1,1,1))
        files={'objects_mission0.xml':b'<root><Entity Name="glue_item_1" EntityId="20"/></root>'}
        original=dict(files)
        with self.assertRaisesRegex(ValueError,'Unregistered'):convert(files,[record],{})
        self.assertEqual(files,original)

    def test_slot_local_offset_rotates_with_parent(self):
        e=entity('1','ItemSlot',vectorPIMatRow4='2,0,0')
        half=2**-.5
        p,q,s=placement_transform(dict(entity=e,position=(10,20,30),rotation=(half,0,0,half),scale=(2,2,2)))
        np.testing.assert_allclose(p,(10,24,30),atol=1e-8)
        np.testing.assert_allclose(rotation(np.diag([1,-1,-1])),(0,1,0,0))
        with self.assertRaisesRegex(ValueError,'non-rigid'):rotation(np.diag([2,1,1]))

    def test_empty_bow_bone_socket_is_retained_but_bound_geometry_is_rejected(self):
        for binding in ('',' Binding="objects/arrow.cgf"'):
            text='<CharacterDefinition><Model File="objects/bow.chr"/><AttachmentList><Attachment Type="CA_BONE" AName="Arrow" BoneName="Bow_Arrow"'+binding+'/></AttachmentList></CharacterDefinition>'
            with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1]) as tmp:
                path=Path(tmp)/'bow.pak'
                with zipfile.ZipFile(path,'w') as z:z.writestr('objects/bow.cdf',text)
                z=zipfile.ZipFile(path)
                self.addCleanup(z.close)
                index={'objects/bow.cdf':(z,z.getinfo('objects/bow.cdf'))};emitted={}
                if binding:
                    with self.assertRaisesRegex(ValueError,'non-skin'):character_definition(index,emitted,lambda x:x,lambda x:b'mesh','objects/bow.cdf','objects/test.cdf')
                else:
                    character_definition(index,emitted,lambda x:x,lambda x:b'mesh','objects/bow.cdf','objects/test.cdf')
                    socket=E.fromstring(emitted['objects/test.cdf']).find('AttachmentList/Attachment')
                    self.assertEqual(socket.get('BoneName'),'Bow_Arrow')
                z.close()


if __name__=='__main__':unittest.main()
