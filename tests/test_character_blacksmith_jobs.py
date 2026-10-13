import math
from pathlib import Path
import sys
import unittest
import xml.etree.ElementTree as E

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from character_blacksmith_jobs import workstation_transform,pose,vector
from character_job_items import reservation_contract,register_item


class WorkstationTests(unittest.TestCase):
    def entity(self,position):return E.Element('Entity',Pos=position)

    def test_rigid_workshop_rotation_preserves_distances(self):
        old=[self.entity('0,0,1'),self.entity('2,0,1')]
        new=[self.entity('10,20,4'),self.entity('10,22,4')]
        q,t,errors=workstation_transform(old,new)
        for a,b in zip(old,new):self.assertLess(math.dist(vector(pose(a,q,t)),vector(b)),1e-9)
        self.assertLess(max(errors),1e-9)
        self.assertAlmostEqual(math.dist(vector(pose(old[0],q,t)),vector(pose(old[1],q,t))),2)

    def test_incompatible_layout_is_rejected_without_scaling_actors(self):
        with self.assertRaisesRegex(ValueError,'cannot fit'):
            workstation_transform([self.entity('0,0,0'),self.entity('2,0,0')],
                                  [self.entity('0,0,0'),self.entity('4,0,0')])
        with self.assertRaisesRegex(ValueError,'Degenerate'):
            workstation_transform([self.entity('0,0,0')]*2,[self.entity('0,0,0')]*2)

    def test_native_hand_content_slots_do_not_require_legacy_pickup_helpers(self):
        job=E.fromstring('<Entity><EntityLinks><Link Name="schedulerReservedItem[\'use\',\'tool\']" TargetId="2"/></EntityLinks></Entity>')
        point=E.fromstring('<Entity EntityClass="TagPoint"><EntityLinks><Link TargetId="3" Name=""/></EntityLinks></Entity>')
        slot=E.fromstring('<Entity EntityClass="ItemSlot"><Properties guidItemClassId="tool"/></Entity>')
        contract=reservation_contract(job,{'2':point,'3':slot})[0]
        mission=E.fromstring('<Objects><Entity EntityId="1"/></Objects>')
        source=E.fromstring('<Entity EntityId="9" EntityGuid="123" EntityClass="ItemSlot" Pos="1,2,3"><Properties guidItemClassId="tool"/></Entity>')
        out,_=register_item(mission,source,{'9':source},contract,{'tool':'tool'})
        self.assertNotIn('soclass_SmartObjectHelpers',out.find('Properties').attrib)
        E.tostring(mission) # No None XML attributes from an absent native helper.


if __name__=='__main__':unittest.main()
