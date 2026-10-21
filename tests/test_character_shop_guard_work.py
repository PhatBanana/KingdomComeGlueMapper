import copy
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
import xml.etree.ElementTree as E
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'tools'))
import character_shop_guard_work as work
from character_schedule_jobs import bind_jobs, population_work_supports
from character_schedule_world import bind_arrivals, baseline_schedule_names, resolve_arrivals
from character_person_activity import validate_scheduler_targets
from campaign_entity_links import native_guid, guid_value
import seating_animations
import test_character_schedule_world as fixtures


class ShopGuardWorkTests(unittest.TestCase):
    def native(self, target):
        (target/'Data/Levels/trosecko').mkdir(parents=True)
        table = '''<database><SmartEntityTemplate DatabaseId="lean"><BehaviorTemplates>
          <SmartBehaviorTemplate Name="use" InitialState="Enabled" MaxInstances="1">
          <TreeLocation FileName="world/lean.xml" TreeName="use"/>
          </SmartBehaviorTemplate></BehaviorTemplates></SmartEntityTemplate></database>'''
        with zipfile.ZipFile(target/'Data/Tables.pak', 'w') as z: z.writestr(work.TABLE, table)
        with zipfile.ZipFile(target/'Data/Scripts.pak', 'w') as z:
            z.writestr('AI/world/lean.xml', '''<BehaviorTrees><BehaviorTree name="use"><Root>
              <MoveParamsDecorator><EntityContextElement context="speech_readyForSwitchDialog">
              <UnstanceAction unstance="LeaningBack" locationObject="$__object.id"/>
              </EntityContextElement></MoveParamsDecorator></Root></BehaviorTree></BehaviorTrees>''')
        with zipfile.ZipFile(target/'Data/Levels/trosecko/level.pak', 'w') as z:
            z.writestr('objects_mission0.xml', '''<Objects><Entity EntityId="5" EntityGuid="00000005-0000-0000"
              EntityClass="DetailMovementSmartObject"><Properties guidSmartObjectType="lean"
              soclass_SmartObjectHelpers="leaning_back"/></Entity></Objects>''')
            z.writestr('tables/ai/scheduler.xml', '''<database><Schedulers><C_SmartHub EntityGuid="6"><Links>
              <S_ActivityLink TargetGuid="5" PositioningDelegate="0"><Parameters BehaviorName="use"
              BehaviorOverride="false" AllowedGenders="0" TimeOfDayStart="0" TimeOfDayEnd="1440"/>
              </S_ActivityLink></Links></C_SmartHub><C_SmartHub EntityGuid="5"/></Schedulers></database>''')
            z.writestr(seating_animations.HELPERS, '''<SmartObjectAnimationCollections>
              <Collection HelperSetName="leaning_back"><SmartObjectHelperSetAnimationCollection HashValue="123"/>
              </Collection></SmartObjectAnimationCollections>''')

    def prepared(self, repeated=False):
        files, schedules, activity = fixtures.ScheduleWorldTests().fixture()
        entry = schedules['person'][0]
        entry['behavior'] = dict(tree_file=work.SOURCE[0], tree_name=work.SOURCE[1])
        entry['area'] = dict(EntityGuid='20')
        entry['shop_guard_work'] = dict(points=[entry['arrival'],
            dict(EntityId='10', EntityGuid='1A', Pos='80,90,100', Rotate='1,0,0,0')])
        if repeated: schedules['person'].append(dict(entry, start_minute=1200, end_minute=1440))
        with patch('character_schedule_world.native_wait_activity', return_value=(activity, None)):
            files, _ = bind_arrivals(files, schedules, None)
        return files, schedules

    def test_native_contract_rejects_nonexclusive_or_unusable_posts(self):
        with tempfile.TemporaryDirectory() as tmp:
            target=Path(tmp); self.native(target)
            props, activity = work.native_contract(target)
            self.assertEqual(props.get('soclass_SmartObjectHelpers'), 'leaning_back')
            self.assertEqual(activity.find('Parameters').get('AllowedGenders'), '0')
            with zipfile.ZipFile(target/'Data/Scripts.pak', 'w') as z:
                z.writestr('AI/world/lean.xml', '<BehaviorTrees><BehaviorTree name="use"><Root/></BehaviorTree></BehaviorTrees>')
            with self.assertRaisesRegex(ValueError, 'lifecycle'): work.native_contract(target)
            with zipfile.ZipFile(target/'Data/Tables.pak') as z: table=z.read(work.TABLE)
            with zipfile.ZipFile(target/'Data/Tables.pak', 'w') as z:
                z.writestr(work.TABLE, table.replace(b'MaxInstances="1"', b'MaxInstances="-1"'))
            with self.assertRaisesRegex(ValueError, 'exclusive occupancy'): work.native_contract(target)

    def test_source_clock_shared_post_identity_and_animation_registration(self):
        files, schedules = self.prepared(repeated=True)
        with tempfile.TemporaryDirectory() as tmp:
            target=Path(tmp); self.native(target)
            with zipfile.ZipFile(target/'Data/Levels/trosecko/level.pak') as z:
                result, report=bind_jobs(files,schedules,z,target,{})
                result, animations=seating_animations.install(result,z)
            rows=E.fromstring(result['tables/ai/scheduler.xml'])
            validate_scheduler_targets(rows)
            links=rows.find("Schedulers/C_SmartHub[@EntityGuid='1']/Links")
            self.assertEqual([(l.find('Parameters').get('TimeOfDayStart'),l.find('Parameters').get('TimeOfDayEnd'))
                              for l in links],[('300','720'),('1200','1440')])
            self.assertTrue(all(l.find('Parameters').get('BehaviorName') is None for l in links))
            hub=rows.find("Schedulers/C_SmartHub[@EntityGuid='"+links[0].get('TargetGuid')+"']")
            self.assertEqual(len(hub.find('Links')),2)
            self.assertTrue(all(l.find('Parameters').get('TimeOfDayEnd')=='1440' for l in hub.find('Links')))
            self.assertEqual(report[0]['intervals'],[[300,720],[1200,1440]])
            self.assertFalse(report[0]['runtime_verified'])
            self.assertEqual(animations['families'],['leaning_back'])
            animation_rows=E.fromstring(result[seating_animations.ANIMATIONS]).findall('.//SmartObjectAnimations')
            self.assertEqual(len(animation_rows),2)
            self.assertEqual({r.get('Hash') for r in animation_rows},{'123'})
            self.assertIn(b'>_<',result['waitinglinks.xml'])
            self.assertIn(b'>home<',result['waitinglinks.xml'])
            self.assertFalse(baseline_schedule_names(result,['person']))
            with zipfile.ZipFile(target/'Data/Levels/trosecko/level.pak') as z:
                with self.assertRaisesRegex(ValueError,'importer-owned'):bind_jobs(result,schedules,z,target,{})

    def test_second_actor_reuses_posts_and_conflicts_do_not_publish(self):
        files,schedules=self.prepared()
        with tempfile.TemporaryDirectory() as tmp:
            target=Path(tmp);self.native(target)
            mission=E.fromstring(files['objects_mission0.xml']);rows=E.fromstring(files['tables/ai/scheduler.xml'])
            original=copy.deepcopy(next(e for e in mission if e.get('Name','').startswith('gm_schedule_')))
            _,_,first=work.bind(mission,rows,'person',schedules['person'][0],target)
            original.set('Name','gm_schedule_other_9');original.set('EntityGuid',native_guid(90));original.set('EntityId','90')
            mission.append(original)
            E.SubElement(rows.find('Schedulers'),'C_SmartHub',EntityGuid='90')
            actor=E.SubElement(rows.find('Schedulers'),'C_SmartHub',EntityGuid='91')
            link=E.SubElement(E.SubElement(actor,'Links'),'S_ActivityLink',TargetGuid='90')
            E.SubElement(link,'Parameters',BehaviorName='use',TimeOfDayStart='800',TimeOfDayEnd='900')
            second_entry=copy.deepcopy(schedules['person'][0])
            bad=copy.deepcopy(second_entry);bad['shop_guard_work']['points'][0]['Pos']='0,0,0'
            with self.assertRaisesRegex(ValueError,'Conflicting shared'):work.bind(mission,rows,'other',bad,target)
            _,_,second=work.bind(mission,rows,'other',second_entry,target)
            self.assertEqual(first['posts'],second['posts'])
            for post in first['posts']:
                self.assertEqual(len(rows.findall("Schedulers/C_SmartHub[@EntityGuid='"+str(guid_value(post['EntityGuid']))+"']")),1)
            validate_scheduler_targets(rows)

    def source(self, directory):
        path=Path(directory)/'source.pak'
        mission=E.fromstring('''<Objects><Entity EntityId="9" EntityGuid="19" Name="post" EntityClass="SmartObjectHolder"
          Pos="1,2,3"><Properties soclasses_SmartObjectHelpers="LeaningSpot">
          <Script Misc="leanBack:true|leanLeft:false|leanRight:false"/></Properties></Entity></Objects>''')
        mission[0].find('Properties').set('guidSmartObjectType',work.SOURCE_TEMPLATE)
        with zipfile.ZipFile(path,'w') as z:z.writestr('objects_mission0.xml',E.tostring(mission))
        program=E.fromstring('''<BehaviorTrees><BehaviorTree name="guard"><Root><GraphSearch
          Origin="__area.id" depth="1" selection="true" includeOrigin="false" EdgePruning="parent,inventory"
          AllowedEdges="" SubGraph="" AllowSubtraph="false"><LinkTagFilter tag="guardWork" prune="true"/>
          <HasBehaviorFilter BehaviorList="use" Source="Child" prune="true"/><Nodalyzer Child="workPlace"/>
          </GraphSearch><CallBehavior Target="workPlace" BehaviorName="use"/></Root></BehaviorTree></BehaviorTrees>''')
        entry=dict(behavior=dict(tree_file=work.SOURCE[0],tree_name=work.SOURCE[1]),area=dict(EntityId='1'),
            target_links=[dict(Name='guardWork,Lean',TargetId='9'),dict(Name='inside',TargetId='missing'),
                          dict(Name='guardWork,parent',TargetId='missing')])
        return path,program,entry,mission

    def test_source_posts_not_shop_arrival_and_alignment_is_used(self):
        with tempfile.TemporaryDirectory() as tmp:
            path,program,entry,_=self.source(tmp)
            reader=lambda *_:{'work':dict(data=E.tostring(program))}
            def aligned(point,*_):
                point.set('Pos','4,5,6');point.set('Rotate','0,0,0,1');return point
            with zipfile.ZipFile(path) as z,patch('character_shop_guard_work.native_placement',side_effect=aligned) as alignment:
                result=resolve_arrivals(dict(resolved=[entry]),z,source=tmp,reader=reader,target=tmp)[0]
                self.assertEqual(result['arrival']['Pos'],'4,5,6')
                self.assertEqual(len(result['shop_guard_work']['points']),1)
                alignment.assert_called_once()
                program.find('.//GraphSearch').set('depth','2')
                with self.assertRaisesRegex(ValueError,'selection contract'):work.resolve(entry,z,tmp,reader,tmp)

    def test_unsupported_orientation_fails_instead_of_replacing_source_job(self):
        with tempfile.TemporaryDirectory() as tmp:
            path,program,entry,mission=self.source(tmp)
            mission[0].find('Properties/Script').set('Misc','leanBack:true|leanLeft:true|leanRight:false')
            with zipfile.ZipFile(path,'w') as z:z.writestr('objects_mission0.xml',E.tostring(mission))
            with zipfile.ZipFile(path) as z:
                with self.assertRaisesRegex(ValueError,'Unsupported source shop guard post'):
                    work.resolve(entry,z,tmp,lambda *_:{'work':dict(data=E.tostring(program))},tmp)
        self.assertTrue(population_work_supports(dict(behavior=dict(tree_file='FINAL\\sa_shop2.xml',tree_name='guard'))))
        self.assertFalse(population_work_supports(dict(behavior=dict(tree_file=work.SOURCE[0],tree_name='merchant'))))


if __name__=='__main__':unittest.main()
