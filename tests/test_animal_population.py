import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
import xml.etree.ElementTree as E
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from animal_population_sources import populations, world, transform, PROXIMITY
from animal_native_templates import habitat, horse_activity
from animal_population import convert, validate, place_flocks, place_horses, owned_state, MANIFEST
from campaign_entity_links import native_guid, guid_value
from campaign_trigger_areas import write_areas, read_areas
from upgrade_map import xml
from wildlife import apply


def source_site(radius='8', count='3'):
    e = E.fromstring(f'''<Entity EntityId="1" EntityGuid="ABC" Name="cows" EntityClass="SmartObjectHolder" Pos="10,20,30" Scale="2,2,2">
      <Properties guidSmartObjectType="{PROXIMITY}"/><EntityLinks>
      <Link Name="animalSpawn[amount({count}),class(Cow),radius({radius}),respawn(28h)]" TargetId="2" TargetGuid="DEF"/>
      </EntityLinks></Entity>''')
    return {'1':e, '2':E.fromstring('<Entity EntityId="2" EntityGuid="DEF" Name="ecosystem" EntityClass="TagPoint" Pos="1000,2000,3000"/>')}


def native_world(actor_class='AnimalSpawner'):
    # The home has a foreign scheduler dependency. It must be replaced by the
    # new habitat binding rather than pulling a native household into KCD1.
    mission = E.fromstring(f'''<Objects>
      <Entity EntityId="11" EntityGuid="0000000b-0000-0000" EntityClass="{actor_class}">
        <Properties guidSoul="native-cow"/>
        <EntityLinks><Link Name="spawnArea" TargetId="12"/>
          <Link Name="home" TargetId="13"/></EntityLinks></Entity>
      <Entity EntityId="12" EntityGuid="0000000c-0000-0000" EntityClass="TriggerArea"/>
      <Entity EntityId="13" EntityGuid="0000000d-0000-0000" EntityClass="SchedulerHub"/>
    </Objects>''')
    scheduler = E.fromstring('''<Table><Schedulers>
      <C_SmartHub EntityGuid="11" Position="999,888,777"><Links>
        <S_ActivityLink TargetGuid="12" PositioningDelegate="12"><Parameters TimeOfDayStart="0" TimeOfDayEnd="1440"/></S_ActivityLink>
      </Links></C_SmartHub>
      <C_SmartHub EntityGuid="12" IgnoreDeadEnds="false" StupidHub="false"/>
      <C_SmartHub EntityGuid="13"><Links><S_ActivityLink TargetGuid="999"/></Links></C_SmartHub>
    </Schedulers></Table>''')
    return mission, scheduler


def baseline():
    return {'objects_mission0.xml': b'<Objects><Entity Name="scenery" EntityClass="GeomEntity"/><Entity EntityId="9" EntityGuid="00000009-0000-0000" Name="keep"/></Objects>',
            'tables/ai/scheduler.xml': b'<Table><Schedulers><C_SmartHub EntityGuid="9"/></Schedulers></Table>',
            'triggerareas.fubar': write_areas([], 1),
            'waitinglinks.xml': b'<StaticLinksInfo version="1"><WaitingLinks/></StaticLinksInfo>',
            'whdata_0': b'<WHLevelData><SoulList><Souls/></SoulList></WHLevelData>'}


class AnimalSources(unittest.TestCase):
    def test_regional_link_spawns_at_owner_and_radius_is_world_units(self):
        sites, excluded = populations(source_site(), {'1', '2'})
        self.assertEqual(len(sites), 1)
        self.assertEqual(sites[0]['position'], (10, 20, 30))
        self.assertEqual(sites[0]['radius'], 8)
        self.assertEqual(sites[0]['count'], 3)
        self.assertAlmostEqual(sites[0]['respawn_days'], 28/24)
        self.assertFalse(excluded)

    def test_non_spawner_reference_is_not_a_second_population(self):
        entities = source_site()
        duplicate = copy.deepcopy(entities['1'])
        duplicate.set('EntityId', '3');duplicate.set('EntityGuid', '123')
        duplicate.find('Properties').set('guidSmartObjectType', 'regional-controller')
        entities['3'] = duplicate
        sites, excluded = populations(entities, {'1','2','3'})
        self.assertEqual(len(sites), 1)
        self.assertIn('regional reference', excluded[0]['reason'])

    def test_preserves_old_self_edge_without_summing_alternatives(self):
        entities = source_site()
        E.SubElement(entities['1'].find('EntityLinks'), 'Link', TargetId='1', TargetGuid='0',
                     Name='animalSpawn[amount(1),class(Cow),radius(7.2),respawn(8h)]')
        sites, excluded = populations(entities, {'1','2'})
        self.assertEqual(sites[0]['count'], 1)
        self.assertEqual(len(excluded[0]['alternatives']), 1)

    def test_source_missing_or_mismatched_dependency_is_an_error(self):
        entities = source_site();entities.pop('2')
        with self.assertRaisesRegex(ValueError, 'Missing animal ecosystem'): populations(entities, {'1'})
        entities = source_site();entities['2'].set('EntityGuid','123')
        with self.assertRaisesRegex(ValueError, 'identity mismatch'): populations(entities, {'1'})

    def test_zero_radius_or_malformed_source_is_reported_not_invented(self):
        for radius in ('0','18,2'):
            sites, excluded = populations(source_site(radius), {'1','2'})
            self.assertFalse(sites)
            self.assertTrue(excluded[0]['requires_adapter'])
        sites, excluded = populations(source_site(count='0'), {'1','2'})
        self.assertFalse(sites);self.assertFalse(excluded[0]['requires_adapter'])

    def test_world_profiles_do_not_activate_all_quest_animals(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp)/'source.pak'
            with zipfile.ZipFile(path,'w') as z:
                z.writestr('objects_mission0.xml','<Objects><Entity EntityClass="Horse" EntityId="1" EntityGuid="1"/></Objects>')
                z.writestr('Layers/base.xml','<Objects><Entity EntityClass="Dog" EntityId="2" EntityGuid="2" Layer="town_state0{abc}"/></Objects>')
                z.writestr('Layers/Opening.xml','<Objects><Entity EntityClass="Cow" EntityId="3" EntityGuid="3" Layer="opening"/></Objects>')
                z.writestr('Layers/later.xml','<Objects><Entity EntityClass="Cow" EntityId="4" EntityGuid="4" Layer="later"/></Objects>')
                z.writestr('whdata_1','<Root><GameProfile><Name>opening</Name><GameLayers><GameLayer>Opening</GameLayer></GameLayers></GameProfile></Root>')
            with zipfile.ZipFile(path) as z:
                _, active = world(z, ('opening',))
                self.assertEqual(active, {'1','2','3'})
                with self.assertRaisesRegex(ValueError, 'Missing or ambiguous'): world(z, ('missing',))

    def test_parent_transform_is_baked_once(self):
        entities = source_site()
        entities['1'].set('ParentId','2')
        e = transform(entities['1'], entities)
        self.assertEqual(e.get('Pos'), '1010,2020,3030')
        self.assertIsNone(e.get('ParentId'))
        self.assertEqual(transform(e, entities).get('Pos'), e.get('Pos'))


class AnimalNetworks(unittest.TestCase):
    def test_horse_activity_is_native_and_keeps_authored_destinations(self):
        mission=E.fromstring('''<Objects><Entity EntityClass="SmartObjectHolder" EntityId="1"
            EntityGuid="00000001-0000-0000" Pos="900,800,700"><Properties guidSmartObjectType="native-horse-work">
            <Script Misc="exact:true"/></Properties></Entity></Objects>''')
        scheduler=E.fromstring('''<Table><Schedulers><C_SmartHub EntityGuid="2"><Links>
            <S_ActivityLink TargetGuid="1" PositioningDelegate="0"><Parameters BehaviorName="grazing"
            TimeOfDayStart="0" TimeOfDayEnd="1440"/></S_ActivityLink></Links></C_SmartHub>
            <C_SmartHub EntityGuid="1" IgnoreDeadEnds="false" StupidHub="false" Position="900,800,700"/>
            </Schedulers></Table>''')
        horse=E.fromstring('''<Entity EntityClass="Horse" EntityId="10" EntityGuid="ABC" Name="horse"
            Pos="10,20,30" Rotate="1,0,0,0" Scale="1,1,1"><Properties bMountIsLegal="1"/></Entity>''')
        point=E.fromstring('<Entity EntityClass="TagPoint" EntityId="11" Pos="12,22,30"/>')
        link=E.Element('Link',Name='horseHome',TargetId='11')
        changed,report=place_horses(baseline(),[(horse,[link])],{'10':horse,'11':point},
            [('native',mission,scheduler)],'native-horse-work')
        objects=E.fromstring(changed['objects_mission0.xml'])
        actor=next(e for e in objects if e.get('Name')=='horse')
        self.assertEqual(actor.get('EntityGuid'),native_guid(0xABC))
        self.assertEqual(actor.get('Pos'),'10,20,30')
        work=next(e for e in objects if e.get('EntityClass')=='SmartObjectHolder')
        self.assertEqual(work.get('Pos'),'12,22,30')
        self.assertEqual(work.find('Properties').get('guidSmartObjectType'),'native-horse-work')
        self.assertEqual(work.find('Properties/Script').get('Misc'),'exact:true')
        activity=E.fromstring(changed['tables/ai/scheduler.xml']).find('Schedulers/C_SmartHub/Links')
        activity=next(E.fromstring(changed['tables/ai/scheduler.xml']).iter('S_ActivityLink'))
        self.assertEqual(activity.get('TargetGuid'),str(guid_value(work.get('EntityGuid'))))
        rows=E.fromstring(changed['tables/ai/scheduler.xml']).find('Schedulers')
        leaf=next(r for r in rows if r.get('EntityGuid')==activity.get('TargetGuid'))
        self.assertEqual(leaf.tag,'C_SmartHub')
        self.assertEqual(leaf.get('Position'),'12,22,30')
        self.assertEqual(leaf.get('IgnoreDeadEnds'),'false')
        self.assertEqual(len(leaf),0)
        guids={e.get('EntityGuid') for e in objects if e.get('EntityId') not in (None,'9')}
        receipt=dict(owned_guids=sorted(guids),owned_state=owned_state(changed,guids))
        validate(changed,receipt)
        # Entity and waiting-link existence passed the old validator. Retail
        # nevertheless dereferences a null activity node without this row.
        rows.remove(leaf)
        broken=dict(changed)
        root=E.Element('Table');root.append(rows);broken['tables/ai/scheduler.xml']=xml(root)
        receipt['owned_state']=owned_state(broken,guids)
        with self.assertRaisesRegex(ValueError,'Missing animal scheduler registration'):
            validate(broken,receipt)
        # A native template without its leaf record is not a usable template.
        native_rows=scheduler.find('Schedulers');saved=native_rows[-1];native_rows.remove(saved)
        with self.assertRaisesRegex(ValueError,'Missing native horse'):
            horse_activity(mission,scheduler,'native-horse-work')
        native_rows.append(saved)
        scheduler.find('.//Parameters').set('RequiredContext','nativeQuestOnly')
        with self.assertRaisesRegex(ValueError,'Missing native horse'):horse_activity(mission,scheduler,'native-horse-work')

    def test_home_does_not_import_foreign_household_scheduler(self):
        mission, scheduler = native_world()
        template = habitat(mission, scheduler, soul='native-cow')
        self.assertIn('13', template['entities'])
        self.assertIn('13', template['rows'])
        self.assertFalse(template['rows']['13'].findall('Links/S_ActivityLink'))
        self.assertEqual(template['entities']['13'].find('EntityLinks/Link').get('Name'), 'home_area')
        self.assertEqual(template['entities']['13'].find('EntityLinks/Link').get('TargetId'), '12')
        scheduler.find('Schedulers/C_SmartHub/Links/S_ActivityLink').set('TargetGuid','404')
        with self.assertRaisesRegex(ValueError, 'No self-contained'): habitat(mission,scheduler,soul='native-cow')

    def test_direct_actor_keeps_source_identity_transform_and_territory(self):
        m,s = native_world('Dog');template=habitat(m,s,actor_class='Dog')
        site=dict(guid='ABC',name='source_dog',species='Dog',position=(10,20,30),count=1,
            radius=0,respawn_days=0,actor=True,rotation='0,0,0,1',scale='1,1,1',
            area=dict(height=12,points=((1,2,3),(7,2,3),(7,8,3))))
        changed, report=apply(baseline(), [site], {'Dog':template})
        actor=next(e for e in E.fromstring(changed['objects_mission0.xml']) if e.get('Name')=='source_dog')
        self.assertEqual(actor.get('EntityGuid'), native_guid(0xABC))
        self.assertEqual(actor.get('Rotate'),'0,0,0,1')
        self.assertIsNone(actor.find('Properties').get('AnimalCount'))
        self.assertEqual(read_areas(changed['triggerareas.fubar'])['areas'][0].points, site['area']['points'])
        self.assertEqual(report[0]['spawn_name'],'source_dog')
        owned={e.get('EntityGuid') for e in E.fromstring(changed['objects_mission0.xml'])
               if e.get('EntityId') not in (None,'9')}
        receipt=dict(owned_guids=sorted(owned),owned_state=owned_state(changed,owned))
        validate(changed,receipt)
        home=next(e for e in E.fromstring(changed['objects_mission0.xml'])
                  if e.find("EntityLinks/Link[@Name='home_area']") is not None)
        scheduler=E.fromstring(changed['tables/ai/scheduler.xml'])
        registration=next(r for r in scheduler.find('Schedulers')
                          if r.get('EntityGuid')==str(guid_value(home.get('EntityGuid'))))
        scheduler.find('Schedulers').remove(registration)
        broken=dict(changed);broken['tables/ai/scheduler.xml']=xml(scheduler)
        receipt['owned_state']=owned_state(broken,owned)
        with self.assertRaisesRegex(ValueError,'Missing animal scheduler registration'):
            validate(broken,receipt)

    def test_missing_native_home_registration_is_not_silently_dropped(self):
        m,s=native_world();s.find('Schedulers').remove(s.find('Schedulers')[-1])
        with self.assertRaisesRegex(ValueError,'Missing native animal home scheduler'):
            habitat(m,s,soul='native-cow')

    def test_scheduler_target_must_be_registered_even_if_entity_exists(self):
        files=baseline();mission=E.fromstring(files['objects_mission0.xml'])
        E.SubElement(mission,'Entity',EntityId='10',EntityGuid=native_guid(10),Name='animal',EntityClass='Horse')
        E.SubElement(mission,'Entity',EntityId='11',EntityGuid=native_guid(11),Name='existing_target',EntityClass='SmartObjectHolder')
        files['objects_mission0.xml']=xml(mission)
        files['tables/ai/scheduler.xml']=b'<Table><Schedulers><C_SmartHub EntityGuid="10"><Links><S_ActivityLink TargetGuid="11"/></Links></C_SmartHub></Schedulers></Table>'
        guids={native_guid(10)}
        receipt=dict(owned_guids=list(guids),owned_state=owned_state(files,guids))
        with self.assertRaisesRegex(ValueError,'Unregistered animal scheduler target'):
            validate(files,receipt)

    def test_native_flock_defaults_replace_legacy_models_and_preserve_water_depth(self):
        with tempfile.TemporaryDirectory() as temp:
            target=Path(temp);(target/'Data').mkdir()
            with zipfile.ZipFile(target/'Data/Scripts.pak','w') as z:
                z.writestr('Scripts/Entities/Boids/Fish.lua','-- native class')
            fish=E.fromstring('''<Entity EntityClass="Fish" EntityId="1" EntityGuid="ABC" Name="fish" Pos="10,20,-3" Rotate="1,0,0,0" Scale="1,1,1">
              <Properties object_Model="legacy.cdf"><Boid nCount="7"/><Options Radius="6"/></Properties>
              <Area SphereRadius="30"><Entities><Entity Id="1"/></Entities></Area></Entity>''')
            changed,_=place_flocks(baseline(),[fish],target)
            e=list(E.fromstring(changed['objects_mission0.xml']))[-1]
            self.assertEqual(e.get('Pos'),'10,20,-3')
            self.assertEqual(e.find('Properties/Boid').get('nCount'),'7')
            self.assertNotIn(b'legacy.cdf',changed['objects_mission0.xml'])
            self.assertEqual(e.find('Area/Entities/Entity').get('Id'),e.get('EntityId'))

    def test_conversion_resume_is_idempotent_and_detects_damaged_managed_records(self):
        with tempfile.TemporaryDirectory() as temp:
            source=Path(temp)/'source';target=Path(temp)/'target'
            folder=source/'Data/Levels/rataje';folder.mkdir(parents=True)
            (target/'Data').mkdir(parents=True)
            with zipfile.ZipFile(target/'Data/Scripts.pak','w'): pass
            root=E.Element('Objects');root.extend(source_site().values())
            with zipfile.ZipFile(folder/'level.pak','w') as z:z.writestr('objects_mission0.xml',xml(root))
            m,s=native_world()
            catalog=({'animal_cattle_cow':'native-cow'},None,[('native',m,s)])
            with patch('animal_population.native_catalog',return_value=catalog):
                changed,report=convert(baseline(),source,target)
                self.assertEqual(len(report['populations_added']),1)
                # A receipt round trip must not turn a valid stage into a mismatch.
                again,receipt=convert(changed,source,target)
                self.assertEqual(changed,again)
                self.assertFalse(receipt['runtime_verified'])
                self.assertEqual(E.fromstring(changed['objects_mission0.xml'])[0].get('Name'),'scenery')
                broken=dict(changed);doc=E.fromstring(broken['objects_mission0.xml'])
                doc[-1].set('Pos','99,99,99');broken['objects_mission0.xml']=xml(doc)
                with self.assertRaisesRegex(ValueError,'Managed animal'):convert(broken,source,target)
                broken=dict(changed);broken['triggerareas.fubar']=write_areas([],1)
                with self.assertRaisesRegex(ValueError,'binary geometry'):validate(broken,report)
                broken=dict(changed);broken['waitinglinks.xml']=baseline()['waitinglinks.xml']
                with self.assertRaisesRegex(ValueError,'waiting link'):validate(broken,report)

    def test_existing_service_horse_identity_is_preserved(self):
        with tempfile.TemporaryDirectory() as temp:
            source=Path(temp)/'source';target=Path(temp)/'target'
            folder=source/'Data/Levels/rataje';folder.mkdir(parents=True)
            (target/'Data').mkdir(parents=True)
            with zipfile.ZipFile(target/'Data/Scripts.pak','w'):pass
            with zipfile.ZipFile(folder/'level.pak','w') as z:
                z.writestr('objects_mission0.xml','<Objects><Entity EntityClass="Horse" EntityId="1" EntityGuid="ABC" Name="sale_horse" Pos="1,2,3"/></Objects>')
            files=baseline();m=E.fromstring(files['objects_mission0.xml'])
            horse=E.SubElement(m,'Entity',Name='managed_service_horse',EntityClass='Horse',EntityGuid=native_guid(0xABC),EntityId='10')
            E.SubElement(horse,'Properties',custom='service-contract')
            files['objects_mission0.xml']=xml(m)
            with patch('animal_population.native_catalog',return_value=({},None,[])):
                changed,r=convert(files,source,target)
            self.assertEqual(len(r['existing_actors']),1)
            self.assertFalse(r['horses'])
            self.assertEqual(changed['objects_mission0.xml'],files['objects_mission0.xml'])


if __name__ == '__main__': unittest.main()
