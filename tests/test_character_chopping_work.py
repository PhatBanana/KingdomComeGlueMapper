import copy
from pathlib import Path
import sys
import unittest
from unittest.mock import patch, MagicMock, Mock
import xml.etree.ElementTree as E

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'tools'))
import character_chopping_work as work
import character_chopping_source as source
from character_chopping_native import graph, relocate
import test_character_fence_work as fence_fixture
from campaign_entity_links import native_guid, guid_value, append_links
from character_person_activity import validate_scheduler_targets


def native():
    roles = {}
    for i, role in enumerate(('job', 'pivot', 'collect', 'unload', 'chopBasket', 'axe', 'log', 'half', 'collectBasket', 'unloadBasket', 'reservation', 'basket'), 200):
        cls = 'TagPoint' if role == 'reservation' else ('ItemSlot' if role in ('chopBasket','axe','log','half','collectBasket','unloadBasket','basket') else 'SmartObjectHolder')
        e = E.Element('Entity', EntityClass=cls, EntityId=str(i), EntityGuid=native_guid(i), Pos='0,0,0', Rotate='1,0,0,0')
        E.SubElement(e, 'Properties', bSaved_by_game='0'); roles[role] = e
    for role, category, family in [('pivot','Pivot','chopping'),('collect','','wood_big'),('unload','','wood_small'),('chopBasket','BasketSlot','Basket_empty'),('axe','Axe','ChoppingAxe')]:
        roles[role].find('Properties').attrib.update(sWH_AI_EntityCategory=category, soclass_SmartObjectHelpers=family)
    for role in ('basket','chopBasket','collectBasket','unloadBasket'):
        roles[role].find('Properties').set('guidItemClassId','basket')
        if role != 'basket': roles[role].find('Properties').set('bSpawnOnStart','0')
    for role in ('axe','log','half'):
        roles[role].find('Properties').set('guidItemClassId',role)
        if role != 'axe': roles[role].find('Properties').set('bInvisibleContent','1')
    roles['job'].find('Properties').set('guidSmartObjectType','native-chop')
    edges = [('job','pivot','chopping'),('job','chopBasket','chopping'),('job','collect','collect'),('job','unload','setAside'),
        ('job','job','+Soil[use,4]'),('job','reservation',"schedulerReservedItem['use','camper_woodChopping']"),
        ('reservation','basket',''),('pivot','axe','axeSlot'),('pivot','log','logSlot'),('pivot','half','logHalfSlot'),
        ('collect','collectBasket','slot'),('unload','unloadBasket','basket')]
    for a,b,name in edges:
        links = roles[a].find('EntityLinks')
        if links is None: links = E.SubElement(roles[a],'EntityLinks')
        E.SubElement(links,'Link',Name=name,TargetId=roles[b].get('EntityId'),TargetGuid=roles[b].get('EntityGuid'))
    roles, reservation = graph(roles['job'],{e.get('EntityId'):e for e in roles.values()})
    _, activity, terminal = fence_fixture.FenceWorkTests().native()
    activity.find('Parameters').set('AllowedGenders','0')
    terminal.find('.//EffectSoil').set('SoilRate','4.000000')
    return dict(roles=roles,reservation=reservation,activity=activity,terminal=terminal)


def station():
    nodes = {}
    for i, role in enumerate(('basket','axe','log'), 300):
        e = E.Element('Entity',EntityClass='ItemSlot',EntityId=str(i),EntityGuid=format(i,'X'),Pos='10,20,30',Rotate='1,0,0,0')
        E.SubElement(e,'Properties',guidItemClassId=('oldaxe' if role=='axe' else role),bSpawnOnStart='1')
        nodes[role] = e
    return dict(identity='source-block',contacts={k:dict(Pos='10,20,30',Rotate='1,0,0,0') for k in ('chopping','collect','setAside')},
        entities={e.get('EntityId'):e for e in nodes.values()}, **nodes)


ITEMS = {v:v for v in ('basket','axe','oldaxe','log','half')}


class ChoppingTests(unittest.TestCase):
    def prepared(self):
        files,schedules = fence_fixture.FenceWorkTests().prepared()
        return E.fromstring(files['objects_mission0.xml']), E.fromstring(files['tables/ai/scheduler.xml']), schedules['person'][0]

    def bind(self,m,s,e,st=None,c=None):
        return work.bind(m,s,'person',e,{(300,720)},st or station(),c or native(),ITEMS)

    def test_complete_native_graph_and_clock(self):
        m,s,e=self.prepared(); before=E.tostring(m.find("Entity[@Name='person']"))
        job,point,links,items,changed=self.bind(m,s,e)
        self.assertTrue(changed); self.assertEqual(before,E.tostring(m.find("Entity[@Name='person']")))
        validate_scheduler_targets(s)
        nodes={x.get('EntityId'):x for x in m}
        roles,reservation=graph(point,nodes)
        self.assertEqual(len(roles),12)
        self.assertEqual(roles['axe'].find('Properties').get('guidItemClassId'),'axe')
        self.assertEqual(roles['basket'].find('Properties').get('bSpawnOnStart'),'1')
        for r in ('collectBasket','chopBasket','unloadBasket'):
            self.assertEqual(roles[r].find('Properties').get('bSpawnOnStart'),'0')
        row=s.find("Schedulers/C_SmartHub[@EntityGuid='"+str(guid_value(job.get('EntityGuid')))+"']")
        p=row.find('Links/S_ActivityLink/Parameters')
        self.assertEqual((p.get('TimeOfDayStart'),p.get('TimeOfDayEnd')),('300','720'))
        encoded=E.fromstring(append_links(None,links,allow_untagged=True))
        self.assertEqual(len(encoded.findall('.//WaitingLink')),len(links))
        self.assertEqual(items[1]['source_item'],'oldaxe')

    def test_preserves_existing_fence_pool(self):
        m,s,e=self.prepared(); fixture=fence_fixture.FenceWorkTests()
        with patch.object(fence_fixture.fence,'native_contract',return_value=fixture.native()):
            job,_=fence_fixture.fence.bind(m,s,'person',e,fixture.points(),None)
        hub=s.find("Schedulers/C_SmartHub[@EntityGuid='"+str(guid_value(job.get('EntityGuid')))+"']")
        old=E.tostring(hub.find('Links')[0]);self.bind(m,s,e)
        self.assertEqual(old,E.tostring(hub.find('Links')[0]));self.assertEqual(len(hub.find('Links')),2)
        validate_scheduler_targets(s)

    def test_repeatable_shared_workplace(self):
        m,s,e=self.prepared(); self.bind(m,s,e)
        before=(E.tostring(m),E.tostring(s))
        result=self.bind(m,s,e)
        self.assertFalse(result[-1]); self.assertEqual(before,(E.tostring(m),E.tostring(s)))
        other=copy.deepcopy(station());other['contacts']['collect']['Pos']='100,20,30'
        with self.assertRaisesRegex(ValueError,'Conflicting shared'): self.bind(m,s,e,other)

    def test_foreign_owner_and_changed_clock_are_rejected_before_edits(self):
        for field in ('owner','clock','female'):
            m,s,e=self.prepared()
            if field=='owner':m.find("Entity[@Name='person']").set('EntityGuid',native_guid(999))
            if field=='clock':s.find('.//S_ActivityLink/Parameters').set('TimeOfDayStart','301')
            if field=='female':m.find("Entity[@Name='person']").set('EntityClass','NPC_Female')
            before=E.tostring(m)
            with self.assertRaises(ValueError):self.bind(m,s,e)
            self.assertEqual(before,E.tostring(m))

    def test_foreign_pool_activity_is_not_overwritten(self):
        m,s,e=self.prepared();self.bind(m,s,e)
        next(x for x in m if x.get('Name','').endswith('_job')).set('Name','quest-owned')
        with self.assertRaisesRegex(ValueError,'Foreign activity'):self.bind(m,s,e)

    def test_native_missing_links_and_duplicate_slots_are_rejected(self):
        for mode in ('missing','spawn','external'):
            c=native();roles=c['roles'];root=roles['job']
            if mode=='missing':root.find('EntityLinks').remove(root.find("EntityLinks/Link[@Name='collect']"))
            if mode=='spawn':roles['collectBasket'].find('Properties').set('bSpawnOnStart','1')
            if mode=='external':E.SubElement(roles['axe'],'EntityLinks').append(E.Element('Link',Name='foreign',TargetId='9999'))
            with self.assertRaises(ValueError):graph(root,{x.get('EntityId'):x for x in roles.values()})

    def test_missing_item_definition_does_not_mutate(self):
        m,s,e=self.prepared();before=E.tostring(m)
        with self.assertRaisesRegex(ValueError,'Missing native'):
            work.bind(m,s,'person',e,{(300,720)},station(),native(),{})
        self.assertEqual(before,E.tostring(m))

    def test_relocation_preserves_native_relative_offsets(self):
        origin=E.Element('Entity',Pos='5,5,5',Rotate='1,0,0,0')
        e=E.Element('Entity',Pos='6,7,8',Rotate='1,0,0,0')
        out=relocate(e,origin,dict(Pos='10,20,30',Rotate='0,0,0,1'))
        self.assertEqual(out.get('Pos'),'9,18,33');self.assertEqual(out.get('Rotate'),'0,0,0,1')
        self.assertEqual(e.get('Pos'),'6,7,8')

    def test_source_binding_does_not_accept_unrelated_lab_program(self):
        class Tables:
            def get(self,name):
                if name == 'ai/sa_behaviour_tag':
                    return dict(rows=[dict(sa_behaviour_tag_id='tag',sa_behaviour_tag_name='choppingWood',tree_file='_ml/lab.xml',tree_name='choppingWood')])
                return dict(rows=[dict(sa_smart_area_id='area',sa_behaviour_tag_id='tag')])
        self.assertFalse(source.source_contract(dict(area_template=dict(sa_smart_area_id='area')),Tables(),None))

    def test_corrupt_existing_tool_is_rejected_on_repeat_upgrade(self):
        m,s,e=self.prepared();self.bind(m,s,e)
        axe=next(x for x in m if x.find('Properties') is not None and x.find('Properties').get('guidItemClassId')=='axe')
        self.assertTrue(axe.get('Name').startswith('gm_job_item_'))
        axe.set('Pos','999,0,0')
        with self.assertRaisesRegex(ValueError,'Conflicting shared'):self.bind(m,s,e)

    def test_source_selection_rejects_deeper_or_inventory_queries(self):
        program=E.Element('BehaviorTrees'); root=E.SubElement(E.SubElement(program,'BehaviorTree',name='pickWoodBasket'),'Root')
        reserve=E.SubElement(root,'ReserveBehavior',reserveFrom='chopBlock',behaviorName='woodChopping')
        sequence=E.SubElement(E.SubElement(E.SubElement(reserve,'Search'),'ReserveBehaviorSearch'),'Sequence')
        for category,child,prune in [('ChopBlock','chopBlock','parent'),('woodForSplitting','t_logPile','parent,inventory'),('choppedWood','t_choppedWood','parent,inventory')]:
            query=E.SubElement(sequence,'GraphSearch',Origin='__area.id',depth='1',EdgePruning=prune,includeOrigin='false',AllowedEdges='',SubGraph='',SetOperationChoice='Intersection|And')
            E.SubElement(query,'CategoryFilter',categories=category,Child=child)
            if category=='ChopBlock':E.SubElement(query,'HasBehaviorFilter',BehaviorList='woodChopping',FilterChoice='Requestable')
        E.SubElement(reserve,'CallBehavior',Target='chopBlock',BehaviorName='woodChopping')
        source.selection_contract(program)
        sequence[1].set('depth','2')
        with self.assertRaisesRegex(ValueError,'query changed'):source.selection_contract(program)
        sequence[1].set('depth','1');sequence[1].set('EdgePruning','parent')
        with self.assertRaisesRegex(ValueError,'query changed'):source.selection_contract(program)

    def test_upgrade_visits_every_eligible_worker_and_shares_the_workstation(self):
        files, schedules = fence_fixture.FenceWorkTests().prepared()
        mission = E.fromstring(files['objects_mission0.xml'])
        scheduler = E.fromstring(files['tables/ai/scheduler.xml'])
        entry = schedules['person'][0]
        actor = copy.deepcopy(mission.find("Entity[@Name='person']"))
        original_actor = actor.get('EntityGuid')
        actor.set('Name', 'another_worker'); actor.set('EntityGuid', native_guid(999)); actor.set('EntityId', '999')
        mission.append(actor)
        job = copy.deepcopy(mission.find("Entity[@Name='gm_schedule_person_"+entry['arrival']['EntityId']+"']"))
        original_job = job.get('EntityGuid')
        new_guid = work.identity('schedule-arrival/'+actor.get('EntityGuid')+'/'+entry['arrival']['EntityGuid'])
        job.set('Name', 'gm_schedule_another_worker_'+entry['arrival']['EntityId'])
        job.set('EntityGuid', new_guid); job.set('EntityId', '1000'); mission.append(job)
        rows = scheduler.find('Schedulers')
        for old, new in ((original_actor, actor.get('EntityGuid')), (original_job, new_guid)):
            row = copy.deepcopy(next(r for r in rows if r.get('EntityGuid') == str(guid_value(old))))
            row.set('EntityGuid', str(guid_value(new)))
            for link in row.findall('Links/S_ActivityLink'):
                if link.get('TargetGuid') == str(guid_value(original_job)): link.set('TargetGuid', str(guid_value(new_guid)))
            rows.append(row)
        schedules['another_worker'] = copy.deepcopy(schedules['person'])
        files.update({'objects_mission0.xml':E.tostring(mission), 'tables/ai/scheduler.xml':E.tostring(scheduler)})
        import test_character_work_capabilities as capabilities
        program = E.Element('BehaviorTrees'); tree = capabilities.source(); tree.set('name','housework'); program.append(tree)
        E.SubElement(tree.find('.//IfElseCondition/Else'), 'Expression', expressions="$houseworks[2].name = 'choppingWood'")
        reader = lambda *_: dict(home=dict(data=E.tostring(program)), warehouse=dict(data=b'<Trees/>'), helpers=dict(data=b'<Helpers/>'))
        context = MagicMock(); context.__enter__.return_value = reader
        with patch.object(work,'RetailSourceReader',return_value=context), patch.object(work,'source_contract',return_value=True), \
                patch.object(work,'resolve',return_value=station()), patch.object(work,'native_contract',return_value=native()):
            result, report = work.upgrade(files,schedules,Mock(filename='C:/game/Data/Levels/map/level.pak'),None,ITEMS)
            again, repeated = work.upgrade(result,schedules,Mock(filename='C:/game/Data/Levels/map/level.pak'),None,ITEMS)
        self.assertEqual({r['person'] for r in report},{'person','another_worker'})
        self.assertTrue(all(r['extension_only'] for r in report))
        self.assertEqual(result,again); self.assertEqual(repeated,[])
        jobs=[e for e in E.fromstring(result['objects_mission0.xml']) if e.get('Name','').startswith('gm_schedule_chopping_') and e.get('Name').endswith('_job')]
        self.assertEqual(len(jobs),1)
        validate_scheduler_targets(E.fromstring(result['tables/ai/scheduler.xml']))


if __name__=='__main__':unittest.main()
