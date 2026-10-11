from pathlib import Path
import struct
import sys
import unittest
import xml.etree.ElementTree as E
import numpy as np

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from door_locks import convert_properties, difficulty_rules
from door_skin import align_internal_origin
from character_skin_upgrade import CompiledSkin
from clothing_regions import read_chunks, write_chunks
from test_character_upgrade import sample_skin
from world_doors import lower_helper
from door_keys import SourceKeyAdapter
from campaign_dependencies import ImportPlan

CONTRACT=dict(helper='DoorRight',animation_set='VillageRight',smart_object='native-door')


class DoorLockTests(unittest.TestCase):
    def source(self):
        return E.fromstring('''<Properties object_Model="objects/doors/lvl2_door_01_right.cdf"
          esInteriorType="home" fKeepOpenFrom="6" fKeepOpenUntil="22" soclasses_SmartObjectHelpers="DoorRight">
          <Lock fLockDifficulty="0.9" bLockDifficultyOverride="0" bLocked="1" bCanLockPick="0"
                esLockTypes="key/key" bLockReversed="1" guidItemClassId="source-key" bNeverLock="0"/>
          <Physics bPhysicalize="0"/></Properties>''')

    def test_model_difficulty_replaces_unused_authored_value(self):
        rules=difficulty_rules('function AnimDoor:GenerateLockDifficulty()\n["doors/lvl2_door_01"] = 6\nfor nameSnippet, difficulty')
        props,report=convert_properties(self.source(),'converted_right.cdf',CONTRACT,rules)
        lock=props.find('Lock')
        self.assertEqual(lock.get('fLockDifficulty'),'0.3')
        self.assertEqual(lock.get('bCanLockPick'),'0')
        self.assertEqual(lock.get('guidItemClassId'),'source-key')
        self.assertEqual(lock.get('bLockReversed'),'1')
        self.assertEqual(lock.get('bLocked'),'1')
        self.assertEqual(report['owner'],'unknown')
        self.assertEqual(lock.get('bDoLockOnMissingHomeArea'),'0')
        self.assertEqual(lock.get('bCanUnlockWithDynamicKey'),'0')
        self.assertIsNone(props.get('esInteriorType'))

    def test_override_and_never_lock(self):
        source=self.source();source.find('Lock').set('bLockDifficultyOverride','1')
        source.find('Lock').set('bNeverLock','1')
        props,_=convert_properties(source,'converted_right.cdf',CONTRACT,{})
        lock=props.find('Lock')
        self.assertEqual(lock.get('fLockDifficulty'),'0.9')
        self.assertEqual(lock.get('esLockTypes'),'none/none')
        self.assertEqual(lock.get('bLocked'),'0')
        self.assertEqual(lock.get('bLockOutside'),'0')
        self.assertEqual(source.find('Lock').get('bLocked'),'1')

    def test_unlocked_source_stays_unlocked(self):
        source=self.source();source.find('Lock').set('bLocked','0')
        props,_=convert_properties(source,'converted_right.cdf',CONTRACT,{})
        self.assertEqual(props.find('Lock').get('bLocked'),'0')

    def test_internal_origin_repair_does_not_move_render_geometry(self):
        original=sample_skin();chunks=read_chunks(original)
        internal=next(c for c in chunks if c.kind==0x2005);data=bytearray(internal.data)
        for offset in range(44,len(data),64):
            p=struct.unpack_from('<3f',data,offset)
            struct.pack_into('<3f',data,offset,p[0]+.05,p[1]-.01,p[2]+.02)
        damaged=write_chunks(chunks,{internal.id:bytes(data)})
        repaired,delta=align_internal_origin(damaged)
        self.assertTrue(np.allclose(CompiledSkin(repaired).vertices,CompiledSkin(original).vertices))
        self.assertTrue(np.allclose(delta,[-.05,.01,-.02]))
        struct.pack_into('<f',data,44,123)
        with self.assertRaisesRegex(ValueError,'rigid origin'):
            align_internal_origin(write_chunks(chunks,{internal.id:bytes(data)}))

    def test_lowered_rear_approach_keeps_native_lock_and_animation_helpers(self):
        source=E.fromstring('<Root><Helper className="DoorLeft_backHelperLower" name="Back" pos=".6,.7,-.36" rot="0,0,0,1"/></Root>')
        native=E.fromstring('<Root><Class name="DoorLeft"/><Helper className="DoorLeft" name="Back" pos=".6,.7,0" rot="0,0,0,1"/><Helper className="DoorLeft" name="Lock" pos=".8,0,1"/></Root>')
        collections=E.fromstring('<Root><Collection HelperSetName="DoorLeft"><Animation Name="Open"/></Collection></Root>')
        name,collection=lower_helper('DoorLeft_backHelperLower',source,native,collections)
        self.assertEqual(native.find(f"Helper[@className='{name}'][@name='Back']").get('pos'),'.6,.7,-.36')
        self.assertEqual(native.find(f"Helper[@className='{name}'][@name='Lock']").get('pos'),'.8,0,1')
        self.assertEqual(collection.get('HelperSetName'),name)
        self.assertIsNotNone(collection.find('Animation'))

    def test_source_key_and_misc_key_use_native_key_category_and_original_guid(self):
        for category in ('key','misc'):
            rows={n:{} for n in SourceKeyAdapter.FIELDS}
            rows['pickable_item']={'weight':'0','price':'0'}
            rows[category]={category+'_type_id':'1',category+'_subtype_id':'1'}
            identity='12345678-1234-1234-1234-123456789abc'
            result,files,_=SourceKeyAdapter(None,'worlddoors').convert(identity,
                ImportPlan(source=dict(category=category,rows=rows)),{})
            row=E.fromstring(next(iter(files.values()))).find('ItemClasses/MiscItem')
            self.assertEqual(result,identity);self.assertEqual(row.get('Id'),identity)
            self.assertEqual(row.get('Type'),'4');self.assertEqual(row.get('IconId'),'key_general')
            self.assertIsNone(row.get('SubType'))


if __name__=='__main__':unittest.main()
