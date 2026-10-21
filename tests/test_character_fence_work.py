import copy
import hashlib
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
import xml.etree.ElementTree as E
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'tools'))
import character_fence_work as fence
import test_character_city_work as fixture
import test_character_work_capabilities as capabilities
from campaign_entity_links import guid_value, native_guid
from character_person_activity import validate_scheduler_targets


PROGRAM = b'''<BehaviorTrees><BehaviorTree name="repair_home_fence"><Root><ReserveBehavior
 reserveFrom="fence" behaviorName="repairFence"><GraphSearch Origin="__area.id" depth="1"
 EdgePruning="parent" includeOrigin="false" AllowedEdges="" SubGraph="">
 <CategoryFilter categories="Fence"/><HasBehaviorFilter BehaviorList="repairFence" FilterChoice="Requestable"/>
 <Nodalyzer/></GraphSearch><CallBehavior Target="fence" BehaviorName="repairFence"/>
 </ReserveBehavior></Root></BehaviorTree></BehaviorTrees>'''


class FenceWorkTests(unittest.TestCase):
    def prepared(self):
        files, schedules = fixture.CityWorkTests().prepared()
        mission = E.fromstring(files['objects_mission0.xml'])
        mission.find("Entity[@Name='person']").set('EntityClass', 'NPC')
        files['objects_mission0.xml'] = E.tostring(mission)
        entry = schedules['person'][0]
        entry['behavior'] = dict(tree_file='final/sa_home.xml', tree_name='housework')
        entry['target_links'] = []
        return files, schedules

    def native(self):
        props = E.Element('Properties', guidSmartObjectType='native', soclass_SmartObjectHelpers=fence.FAMILY)
        activity = E.fromstring('''<S_ActivityLink PositioningDelegate="0" TargetGuid="8"><Parameters
            BehaviorName="use" ProvidedRole="use" AllowedGenders="1" TimeOfDayStart="0" TimeOfDayEnd="1440"/></S_ActivityLink>''')
        leaf = E.fromstring('''<C_SmartHub EntityGuid="8"><PostSearchData><SmartHubPostSearchData>
            <SchedulerEffect><EffectSoil Role="use" SoilRate="2.000000"/></SchedulerEffect>
            </SmartHubPostSearchData></PostSearchData></C_SmartHub>''')
        return props, activity, leaf

    def points(self):
        return [dict(EntityGuid='FF', Pos='20,30,40', Rotate='1,0,0,0', source_helper='first', remaining_helpers=['second'])]

    def test_authored_helper_transform_respects_rotation_and_scale(self):
        point = E.Element('Entity', Pos='10,20,30', Rotate='0,0,0,1', Scale='2,3,4')
        helper = E.Element('Helper', pos='1,2,3', rot='1,0,0,0')
        placed = fence.placement(point, helper)
        self.assertEqual(placed['Pos'], '8,14,42')
        self.assertEqual(placed['Rotate'], '0,0,0,1')
        self.assertNotIn('Scale', placed)
        self.assertEqual(point.get('Pos'), '10,20,30')

    def test_source_contract_rejects_changed_depth_or_reservation(self):
        fence.selection_contract(PROGRAM)
        for old, new in [(b'depth="1"', b'depth="2"'), (b'reserveFrom="fence"', b'reserveFrom="other"')]:
            with self.assertRaises(ValueError): fence.selection_contract(PROGRAM.replace(old, new))

    def test_source_only_uses_linked_fences_and_preserves_remaining_positions(self):
        root = E.fromstring('<Objects><Entity EntityId="3" EntityGuid="3" EntityClass="SmartObjectHolder" Pos="10,20,30">'
            f'<Properties guidSmartObjectType="{fence.SOURCE_TEMPLATE}" sWH_AI_EntityCategory="Fence" soclasses_SmartObjectHelpers="Fence"/>'
            '</Entity><Entity EntityId="4" EntityClass="TagPoint"/></Objects>')
        helpers = E.fromstring('<Objects/>')
        for name, pos in [('first', '1,0,0'), ('second', '2,0,0')]:
            E.SubElement(helpers, 'Helper', className='Fence', name=name, pos=pos, rot='1,0,0,0',
                         description="Animation('RepairFenceHammer','');")
        reader = lambda *_: dict(fence=dict(data=PROGRAM), helpers=dict(data=E.tostring(helpers)))
        entry = dict(area=dict(EntityId='1'), target_links=[dict(Name='', TargetId='3'),
            dict(Name='', TargetId='3'), dict(Name='parent', TargetId='missing'), dict(Name='', TargetId='4')])
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)/'source.pak'
            with zipfile.ZipFile(path, 'w') as z: z.writestr('objects_mission0.xml', E.tostring(root))
            with zipfile.ZipFile(path) as z: points = fence.resolve(entry, z, None, reader)
        self.assertEqual(len(points), 1)
        self.assertEqual(points[0]['Pos'], '11,20,30')
        self.assertEqual(points[0]['remaining_helpers'], ['second'])

    def test_pool_preserves_clock_soil_role_and_single_resource_identity(self):
        files, schedules = self.prepared()
        mission = E.fromstring(files['objects_mission0.xml']); scheduler = E.fromstring(files['tables/ai/scheduler.xml'])
        entry = schedules['person'][0]
        arrival = mission.find("Entity[@Name='gm_schedule_person_"+entry['arrival']['EntityId']+"']")
        E.SubElement(E.SubElement(mission.find("Entity[@Name='person']"), 'EntityLinks'), 'Link', Name='_,use', TargetGuid=arrival.get('EntityGuid'))
        with patch.object(fence, 'native_contract', return_value=self.native()):
            job, links = fence.bind(mission, scheduler, 'person', schedules['person'][0], self.points(), None)
        validate_scheduler_targets(scheduler)
        pool = scheduler.find("Schedulers/C_SmartHub[@EntityGuid='"+str(guid_value(job.get('EntityGuid')))+"']")
        activity = pool.find('Links/S_ActivityLink'); p = activity.find('Parameters')
        self.assertEqual((p.get('TimeOfDayStart'),p.get('TimeOfDayEnd')), ('300','720'))
        self.assertEqual(p.get('ProvidedRole'), 'use')
        leaf = scheduler.find("Schedulers/C_SmartHub[@EntityGuid='"+activity.get('TargetGuid')+"']")
        self.assertIsNotNone(leaf.find('.//EffectSoil'))
        self.assertIn('+Soil[use,2]', [l[2] for l in links])
        self.assertEqual(mission.find("Entity[@Name='person']/EntityLinks/Link[@TargetGuid='"+job.get('EntityGuid')+"']").get('Name'), '_')

    def test_two_workers_share_one_fence_and_conflicting_geometry_is_rejected(self):
        files, schedules = self.prepared(); entry = schedules['person'][0]
        mission = E.fromstring(files['objects_mission0.xml']); scheduler = E.fromstring(files['tables/ai/scheduler.xml'])
        actor = copy.deepcopy(mission.find("Entity[@Name='person']"))
        actor.set('Name','other'); actor.set('EntityGuid',native_guid(999)); actor.set('EntityId','999'); mission.append(actor)
        job = copy.deepcopy(mission.find("Entity[@Name='gm_schedule_person_"+entry['arrival']['EntityId']+"']"))
        old_id = str(guid_value(job.get('EntityGuid')))
        guid = native_guid(int.from_bytes(hashlib.sha256(('schedule-arrival/'+actor.get('EntityGuid')+'/'+entry['arrival']['EntityGuid']).encode()).digest()[:8], 'little'))
        job.set('Name','gm_schedule_other_'+entry['arrival']['EntityId']); job.set('EntityGuid',guid);job.set('EntityId','1000');mission.append(job)
        rows=scheduler.find('Schedulers'); owner=copy.deepcopy(rows.find("C_SmartHub[@EntityGuid='1']"));owner.set('EntityGuid','999')
        for link in owner.findall('Links/S_ActivityLink'): link.set('TargetGuid',str(guid_value(guid)))
        rows.append(owner);leaf=copy.deepcopy(rows.find("C_SmartHub[@EntityGuid='"+old_id+"']"));leaf.set('EntityGuid',str(guid_value(guid)));rows.append(leaf)
        with patch.object(fence,'native_contract',return_value=self.native()):
            fence.bind(mission,scheduler,'person',entry,self.points(),None)
            wrong=self.points();wrong[0]['Pos']='999,0,0'
            with self.assertRaisesRegex(ValueError,'Conflicting shared'): fence.bind(mission,scheduler,'other',entry,wrong,None)
            fence.bind(mission,scheduler,'other',entry,self.points(),None)
        self.assertEqual(sum(e.get('Name','').startswith('gm_schedule_fence_') for e in mission),1)
        validate_scheduler_targets(scheduler)

    def test_unrelated_or_female_schedule_is_never_replaced(self):
        for change in ('female', 'owner', 'guid'):
            files, schedules = self.prepared()
            mission = E.fromstring(files['objects_mission0.xml']); scheduler = E.fromstring(files['tables/ai/scheduler.xml'])
            if change == 'female': mission.find("Entity[@Name='person']").set('EntityClass', 'NPC_Female')
            if change == 'owner': scheduler.find('Schedulers')[0].set('EntityGuid', '999')
            if change == 'guid': mission.find("Entity[@Name='person']").set('EntityGuid', native_guid(999))
            before = E.tostring(mission)
            with patch.object(fence, 'native_contract', return_value=self.native()):
                with self.assertRaisesRegex(ValueError, 'non-owned'):
                    fence.bind(mission, scheduler, 'person', schedules['person'][0], self.points(), None)
            self.assertEqual(E.tostring(mission), before)

    def test_upgrade_is_repeatable_and_retains_explicit_pending_phases(self):
        files, schedules = self.prepared()
        program = E.Element('BehaviorTrees'); tree = capabilities.source(); tree.set('name','housework'); program.append(tree)
        reader = lambda *_: {'home': {'data': E.tostring(program)}}
        context = unittest.mock.MagicMock(); context.__enter__.return_value = reader
        archive = unittest.mock.Mock(filename='C:/game/Data/Levels/map/level.pak')
        with patch.object(fence, 'RetailSourceReader', return_value=context), patch.object(fence, 'resolve', return_value=self.points()), patch.object(fence, 'native_contract', return_value=self.native()):
            result, report = fence.upgrade(files, schedules, archive, None)
            again, repeated = fence.upgrade(result, schedules, archive, None)
            self.assertEqual(result, again); self.assertEqual(repeated, [])
            self.assertIn('hangingOut', report[0]['pending']); self.assertFalse(report[0]['runtime_verified'])
            altered = dict(files, **{'tables/ai/scheduler.xml': files['tables/ai/scheduler.xml'].replace(b'300', b'301')})
            with self.assertRaisesRegex(ValueError, 'clock'): fence.upgrade(altered, schedules, archive, None)


if __name__ == '__main__': unittest.main()
