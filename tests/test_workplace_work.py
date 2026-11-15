import io
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
import xml.etree.ElementTree as E
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'tools'))
import character_workplace_work as work
import character_work_adapters as registry
import test_character_city_work as fixture
from campaign_entity_links import guid_value
from character_person_activity import validate_scheduler_targets

Q = '&quot;'


def wrapper(name='tanner', expression=None, template='commonWorkplace', file='final/sa_tannery.xml'):
    expression = expression or ("$t_workplace_params.useCategories = 'tanner_tub,tanner_log', &#10;"
        "$t_workplace_params.cleanCategories = 'tanner_tub', &#10;$t_workplace_params.breakChance = 0.333, &#10;"
        "$t_workplace_params.breakDuration = '20s', &#10;$t_workplace_params.breakVariation = '40s'")
    return (f'''<BehaviorTrees><BehaviorTree name="{name}"><Root>
      <OnInit><IncludeTree File="{Q}{file}{Q}" Name="{Q}{name}_setParams{Q}"/></OnInit>
      <Behavior><IncludeTree File="{Q}final/sa_templates.xml{Q}" Name="{Q}{template}{Q}"/></Behavior></Root></BehaviorTree>
      <BehaviorTree name="{name}_setParams"><Root><Behavior><Expression expressions="{expression}"/></Behavior></Root>
      </BehaviorTree></BehaviorTrees>''').encode()


TEMPLATE = f'''<BehaviorTrees><BehaviorTree name="commonWorkplace"><Root><OnInit><Sequence>
  <GraphSearch Origin="{Q}__area.id{Q}" depth="{Q}1{Q}" EdgePruning="{Q}parent,inventory{Q}" includeOrigin="{Q}false{Q}">
   <CategoryFilter categories="{Q}$t_workplace_params.useCategories{Q}" Source="{Q}Child{Q}"/>
   <Nodalyzer Quantifiers="{Q}ForAll{Q}"/></GraphSearch></Sequence></OnInit>
  <Behavior><Sequence><ReserveBehavior><Search><GraphSearch><CategoryFilter categories="{Q}Seat,Lean{Q}"/></GraphSearch></Search>
   </ReserveBehavior><CallBehavior Target="{Q}workspots_value{Q}" BehaviorName="{Q}use{Q}"/></Sequence></Behavior>
  </Root></BehaviorTree></BehaviorTrees>'''.encode()


def station(name, animation, body=None):
    body = body or f'<IncludeTree File="{Q}final/so_templates.xml{Q}" Name="{Q}objectNewHelpers{Q}"/>'
    return (f'''<BehaviorTrees><BehaviorTree name="use"><Root>
      <OnInit><IncludeTree File="{Q}final/{name}.xml{Q}" Name="{Q}setParams{Q}"/></OnInit><Behavior>{body}</Behavior></Root>
      </BehaviorTree><BehaviorTree name="setParams"><Root><Behavior><Expression expressions="$t_object_params.behaviorName = 'x', &#10; &#10;$t_object_params.animationIn = '{animation}In', &#10;$t_object_params.animationLoop = '{animation}', &#10;$t_object_params.animationOut = '{animation}Out', &#10;$t_object_params.clearHandsOnStart = true, &#10;$t_object_params.slot_right_itemClassId = 'AA-01',"/>
      </Behavior></Root></BehaviorTree><BehaviorTree name="use_default"><Root><Behavior>
      <Wait duration="{Q}20s{Q}" variation="{Q}30s{Q}"/></Behavior></Root></BehaviorTree></BehaviorTrees>''').encode()


def table(rows):
    return ('<database><table><rows>' + ''.join('<row ' + ' '.join(f'{k}="{v}"' for k, v in r.items()) + '/>'
                                                 for r in rows) + '</rows></table></database>').encode()


SOURCES = {
    'libs/ai/final/sa_tannery.xml': wrapper(),
    'libs/ai/final/sa_templates.xml': TEMPLATE,
    'libs/ai/final/so_tub.xml': station('so_tub', 'TannerWashing'),
    'libs/ai/final/so_desk.xml': station('so_desk', 'Transcribing',
        f'<CallBehavior Target="{Q}chair{Q}" BehaviorName="{Q}use{Q}"/>'),
    'libs/tables/ai/so_smart_object.xml': table([
        dict(so_smart_object_id='T-TUB', so_smart_object_name='so_tub'),
        dict(so_smart_object_id='T-DESK', so_smart_object_name='so_desk')]),
    'libs/tables/ai/so_behaviour_tag.xml': table([
        dict(so_behaviour_tag_id='1', so_behaviour_tag_name='use', tree_file='final/so_tub.xml', tree_name='use'),
        dict(so_behaviour_tag_id='2', so_behaviour_tag_name='use', tree_file='final/so_desk.xml', tree_name='use')]),
    'libs/tables/ai/so_smart_object2so_behaviour_tag.xml': table([
        dict(so_behaviour_tag_id='1', so_smart_object_id='t-tub'), dict(so_behaviour_tag_id='2', so_smart_object_id='t-desk')]),
    'libs/smartobjects.xml': b'''<SmartObjectsLibrary>
      <Helper className="wash" name="other" pos="9,9,9" rot="1,0,0,0" description=""/>
      <Helper className="wash" name="entry" pos="1,0,0" rot="0,0,0,1"
        description="Animation('TannerWashingIn':'');Animation('TannerWashing':'');"/></SmartObjectsLibrary>''',
}


def reader(sources=SOURCES):
    def read(source, files):
        return {label: dict(data=sources[entry.lower()]) for label, (pak, entry) in files.items()}
    return read


MISSION = '''<Mission>
  <Entity EntityId="1" EntityGuid="A1" EntityClass="TagPoint" Name="in" Pos="5,5,5"/>
  <Entity EntityId="2" EntityGuid="A2" EntityClass="SmartObjectHolder" Name="tub" Pos="10,20,30" Rotate="1,0,0,0">
    <EntityLinks><Link TargetId="5" Name=""/></EntityLinks>
    <Properties sWH_AI_EntityCategory="tanner_tub" guidSmartObjectType="T-TUB" soclasses_SmartObjectHelpers="wash"/></Entity>
  <Entity EntityId="3" EntityGuid="A3" EntityClass="SmartObjectHolder" Name="desk" Pos="1,1,1">
    <Properties sWH_AI_EntityCategory="tanner_log" guidSmartObjectType="T-DESK" soclasses_SmartObjectHelpers=""/></Entity>
  <Entity EntityId="4" EntityGuid="A4" EntityClass="SmartObjectHolder" Name="seat" Pos="2,2,2">
    <Properties sWH_AI_EntityCategory="Seat"/></Entity>
  <Entity EntityId="5" EntityGuid="A5" EntityClass="ItemSlot" Name="stick" Pos="11,20,31" Rotate="1,0,0,0">
    <EntityLinks><Link TargetId="6" Name="SlotLink"/></EntityLinks><Properties guidItemClassId="AA-01"/></Entity>
  <Entity EntityId="6" EntityGuid="A6" EntityClass="PickableItem" Name="item" Pos="11,20,31"><Properties/></Entity>
  <Entity EntityId="7" EntityGuid="A7" EntityClass="SmartObjectHolder" Name="owned" Pos="3,3,3">
    <Properties sWH_AI_EntityCategory="tanner_tub" guidSmartObjectType="T-TUB" soclasses_SmartObjectHelpers="wash"/></Entity>
</Mission>'''


def archive():
    blob = io.BytesIO()
    with zipfile.ZipFile(blob, 'w') as z:
        z.writestr('objects_mission0.xml', MISSION)
    return zipfile.ZipFile(blob)


def entry(links=None):
    return dict(behavior=dict(tree_file='final\\SA_Tannery.xml', tree_name='tanner'), area=dict(EntityId='90', EntityGuid='B0'),
        target_links=links if links is not None else [dict(TargetId='1', Name='inside'), dict(TargetId='2', Name=''),
            dict(TargetId='3', Name=''), dict(TargetId='4', Name='Seat'), dict(TargetId='7', Name='parent')],
        start_minute=480, end_minute=1020)


class SourceContractTests(unittest.TestCase):
    def test_supports_only_registered_wrapper_identities(self):
        self.assertTrue(work.supports(entry()))
        self.assertFalse(work.supports(dict(behavior=dict(tree_file='final/sa_tannery.xml', tree_name='tanner_cleanup'))))
        self.assertFalse(work.supports(dict(behavior=dict(tree_file='final/sa_study.xml', tree_name='scribe'))))
        self.assertEqual(registry.adapter_for(entry())[0].key, 'workplace_work')

    def test_parameters_are_parsed_from_the_expression(self):
        params = work.wrapper_params(wrapper(), 'final/sa_tannery.xml', 'tanner')
        self.assertEqual(params, dict(useCategories=['tanner_tub', 'tanner_log'], cleanCategories=['tanner_tub'],
                                      breakChance=0.333, breakDuration='20s', breakVariation='40s'))

    def test_retail_expression_quirks(self):
        # bailiff omits a comma before a newline; architect ends with a comma and has no break record.
        missing = ("$t_workplace_params.useCategories = 'inspection,table_writing', &#10;"
                   "$t_workplace_params.breakChance = 1.0 &#10;$t_workplace_params.breakDuration = '10s',")
        params = work.wrapper_params(wrapper(expression=missing), 'final/sa_tannery.xml', 'tanner')
        self.assertEqual((params['breakChance'], params['breakDuration'], params['breakVariation']), (1.0, '10s', None))
        self.assertEqual(params['cleanCategories'], [])
        empty = "$t_workplace_params.useCategories = 'Stonemason', &#10;$t_workplace_params.cleanCategories = '',"
        self.assertEqual(work.wrapper_params(wrapper(expression=empty), 'final/sa_tannery.xml', 'tanner')['cleanCategories'], [])

    def test_rejects_trees_that_are_not_wrappers(self):
        for blob in (wrapper(template='commonWorkplace_cleanup'), wrapper(name='other'),
                     wrapper(expression="$t_workplace_params.breakChance = 1.0")):
            with self.assertRaises(ValueError):
                work.wrapper_params(blob, 'final/sa_tannery.xml', 'tanner')

    def test_template_contract_reads_break_categories_and_rejects_changes(self):
        self.assertEqual(work.template_contract(TEMPLATE), dict(break_categories=['Seat', 'Lean']))
        with self.assertRaisesRegex(ValueError, 'selection'):
            work.template_contract(TEMPLATE.replace(b'parent,inventory', b'parent'))
        with self.assertRaisesRegex(ValueError, 'calls'):
            work.template_contract(TEMPLATE.replace(b'workspots_value', b'other'))

    def test_object_contract_separates_plain_animation_from_compound_programs(self):
        plain = work.object_contract(SOURCES['libs/ai/final/so_tub.xml'], 'final/so_tub.xml', 'use')
        self.assertEqual(plain['animation'], ['TannerWashingIn', 'TannerWashing', 'TannerWashingOut'])
        self.assertEqual((plain['default_wait'], plain['tool_items']), (['20s', '30s'], ['aa-01']))
        compound = work.object_contract(SOURCES['libs/ai/final/so_desk.xml'], 'final/so_desk.xml', 'use')
        self.assertEqual(compound, 'compound use program (CallBehavior chair.use)')


class ResolveTests(unittest.TestCase):
    def test_resolves_linked_stations_contact_pose_tools_and_reports_the_rest(self):
        source = entry()
        with archive() as z:
            result = work.resolve(source, z, 'game', reader())
        self.assertNotIn('workplace_work', source)
        resolved = result['workplace_work']
        self.assertEqual(result['arrival']['EntityId'], '1')
        self.assertEqual(resolved['source'], ['final/sa_tannery.xml', 'tanner'])
        self.assertEqual(resolved['break_spots'], dict(Seat=1))
        # The parent-edge tub (7) is pruned like the source GraphSearch does.
        self.assertEqual([s['source']['EntityId'] for s in resolved['stations']], ['2'])
        tub = resolved['stations'][0]
        self.assertEqual(tub['program'], dict(template='so_leatherTanningTub', behavior='stirLeather'))
        self.assertEqual((tub['pose']['Pos'], tub['pose']['Rotate']), ('11,20,30', '0,0,0,1'))
        self.assertEqual(tub['tools'], [dict(EntityId='5', EntityGuid='A5', Pos='11,20,31', Rotate='1,0,0,0',
                                             item='aa-01', visuals=['5', '6'])])
        self.assertEqual([(p['category'], p['reason']) for p in resolved['pending']],
                         [('tanner_log', 'so_desk: compound use program (CallBehavior chair.use)')])
        self.assertIsNotNone(registry.resolve(source, archive(), 'game', reader()))

    def test_station_becomes_the_arrival_without_an_inside_point(self):
        with archive() as z:
            result = work.resolve(entry([dict(TargetId='2', Name='')]), z, 'game', reader())
        self.assertEqual(result['arrival'], result['workplace_work']['stations'][0]['pose'])

    def test_unconvertible_workplaces_raise_for_residue(self):
        with archive() as z:
            with self.assertRaisesRegex(ValueError, 'compound use program'):
                work.resolve(entry([dict(TargetId='3', Name='')]), z, 'game', reader())
            with self.assertRaisesRegex(ValueError, 'no convertible work object linked'):
                work.resolve(entry([dict(TargetId='4', Name='Seat')]), z, 'game', reader())
            with self.assertRaisesRegex(ValueError, 'contact helper'):
                work.resolve(entry([dict(TargetId='2', Name='')]), z, 'game',
                             reader(dict(SOURCES, **{'libs/smartobjects.xml': b'<SmartObjectsLibrary/>'})))
            with self.assertRaises(ValueError):
                work.resolve(entry(), z, None, None)


class BindTests(unittest.TestCase):
    def prepared(self, actor_class='NPC'):
        files, schedules = fixture.CityWorkTests().prepared()
        mission = E.fromstring(files['objects_mission0.xml'])
        mission.find("Entity[@Name='person']").set('EntityClass', actor_class)
        E.SubElement(mission, 'Entity', Name='glue_item_6', EntityId='900', EntityGuid='99')
        scheduler = E.fromstring(files['tables/ai/scheduler.xml'])
        item = schedules['person'][0]
        item.pop('city_work')
        item['behavior'] = dict(tree_file='final/sa_tannery.xml', tree_name='tanner')
        item['workplace_work'] = dict(source=['final/sa_tannery.xml', 'tanner'],
            params=dict(useCategories=['tanner_tub', 'tanner_log'], cleanCategories=['tanner_tub'], breakChance=0.333,
                        breakDuration='20s', breakVariation='40s'),
            break_spots=dict(Seat=1), pending=[dict(category='tanner_log', source=dict(EntityGuid='A3'), reason='compound')],
            stations=[self.station('A2', 'TannerWashing'), self.station('A8', 'TannerScraping', tools=[])])
        return mission, scheduler, item

    def station(self, guid, animation, tools=None):
        return dict(category='tanner_tub', source=dict(EntityId='2', EntityGuid=guid, Name='tub'),
            pose=dict(EntityId='2', EntityGuid=guid, Pos='11,20,30', Rotate='0,0,0,1'),
            animation=[animation+'In', animation, animation+'Out'], default_wait=['20s', '30s'],
            tools=[dict(EntityId='5', EntityGuid='A5', Pos='11,20,31', Rotate='1,0,0,0', item='aa-01', visuals=['5', '6'])]
                  if tools is None else tools,
            program=dict(template='so_leatherTanningTub', behavior='stirLeather'))

    def native(self, genders='0'):
        return dict(database_id='native-id', unstance='stirLeather', wait='30s', family='leatherTanningTub',
            fragments=['TannerWashingIn', 'TannerWashing', 'TannerWashingOut'], omitted_links=[],
            properties=E.Element('Properties', guidSmartObjectType='native-id', soclass_SmartObjectHelpers='leatherTanningTub'),
            activity=E.fromstring(f'''<S_ActivityLink PositioningDelegate="0" TargetGuid="8"><Parameters
                BehaviorName="stirLeather" BehaviorOverride="false" AllowedGenders="{genders}" TimeOfDayStart="0"
                TimeOfDayEnd="1440"/></S_ActivityLink>'''),
            terminal=E.Element('C_SmartHub', EntityGuid='8', IgnoreDeadEnds='false', StupidHub='false'),
            tools=[('stick', E.Element('Properties', guidItemClassId='native-stick'))])

    def bind(self, mission, scheduler, item, native=None, bodies=None):
        bodies = bodies or dict(male={'TannerWashingIn', 'TannerWashing', 'TannerWashingOut'}, female=set())
        with patch.object(work, 'cached_program', return_value=native or self.native()), \
                patch.object(work, 'body_fragments', return_value=bodies):
            return work.bind(mission, scheduler, 'person', item, 'target')

    def test_arrival_becomes_a_hub_over_one_shared_native_station(self):
        mission, scheduler, item = self.prepared()
        job, waiting, report = self.bind(mission, scheduler, item)
        self.assertEqual(job.get('EntityClass'), 'SchedulerHub')
        self.assertIsNone(job.find('Properties').get('guidSmartObjectType'))
        holder = mission.find("Entity[@Name='gm_schedule_workplace_a2']")
        self.assertEqual((holder.get('Pos'), holder.get('Rotate')), ('11,20,30', '0,0,0,1'))
        self.assertEqual(holder.find('Properties').get('guidSmartObjectType'), 'native-id')
        slot = mission.find("Entity[@Name='gm_workplace_tool_a5']")
        self.assertEqual((slot.get('EntityClass'), slot.get('Pos')), ('ItemSlot', '11,20,31'))
        self.assertEqual(slot.find('Properties').get('guidItemClassId'), 'native-stick')
        self.assertEqual(holder.find('EntityLinks/Link').attrib,
                         dict(Name='stick', TargetId=slot.get('EntityId'), TargetGuid=slot.get('EntityGuid')))
        self.assertIsNone(mission.find("Entity[@Name='glue_item_6']"))
        rows = scheduler.find('Schedulers')
        hub = next(r for r in rows if r.get('EntityGuid') == str(guid_value(job.get('EntityGuid'))))
        leaf = str(guid_value(holder.get('EntityGuid')))
        out = hub.findall('Links/S_ActivityLink')
        self.assertEqual([l.get('TargetGuid') for l in out], [leaf])
        self.assertEqual(out[0].find('Parameters').get('BehaviorName'), 'stirLeather')
        entering = [l for r in rows for l in r.findall('Links/S_ActivityLink')
                    if l.get('TargetGuid') == hub.get('EntityGuid')]
        self.assertTrue(entering and all('BehaviorName' not in l.find('Parameters').attrib for l in entering))
        self.assertEqual((out[0].find('Parameters').get('TimeOfDayStart'), out[0].find('Parameters').get('TimeOfDayEnd')),
            (entering[0].find('Parameters').get('TimeOfDayStart'), entering[0].find('Parameters').get('TimeOfDayEnd')))
        self.assertEqual(len([r for r in rows if r.get('EntityGuid') == leaf]), 1)
        validate_scheduler_targets(scheduler)
        self.assertIn((job.get('EntityGuid'), holder.get('EntityGuid'), '_,stirLeather'), waiting)
        self.assertIn((holder.get('EntityGuid'), slot.get('EntityGuid'), 'stick'), waiting)
        self.assertEqual(report['interval'], [item['start_minute'], item['end_minute']])
        self.assertEqual([s['native_template_id'] for s in report['stations']], ['native-id'])
        # The second station plays another animation than the native program: reported, not bound.
        self.assertTrue(any('A8' in p and 'TannerScraping' in p for p in report['pending']))
        self.assertTrue(any(p.startswith('source break at Seat x1') for p in report['pending']))
        self.assertTrue(any('cleanup of tanner_tub' in p for p in report['pending']))
        self.assertFalse(report['runtime_verified'])

    def test_second_worker_reuses_the_station_and_conflicts_are_rejected(self):
        mission, scheduler, item = self.prepared()
        self.bind(mission, scheduler, item)
        holder = mission.find("Entity[@Name='gm_schedule_workplace_a2']")
        count = len(list(mission))
        planned = work.identity('work/workplace/a2')
        self.assertEqual(holder.get('EntityGuid'), planned)
        other_mission, other_scheduler, other = self.prepared()
        other_mission.append(holder)
        other_scheduler.find('Schedulers').append(E.Element('C_SmartHub', EntityGuid=str(guid_value(planned))))
        self.bind(other_mission, other_scheduler, other)
        self.assertEqual(len(other_mission.findall("Entity[@Name='gm_schedule_workplace_a2']")), 1)
        self.assertIsNone(other_mission.find("Entity[@Name='gm_workplace_tool_a5']"))
        self.assertEqual(len(list(mission)), count)
        moved, scheduler, item = self.prepared()
        E.SubElement(moved, 'Entity', Name='gm_schedule_workplace_a2', EntityGuid=planned, EntityId='901', Pos='0,0,0')
        with self.assertRaisesRegex(ValueError, 'Conflicting native work station'):
            self.bind(moved, scheduler, item)
        self.assertFalse([e for e in moved if e.get('EntityClass') == 'SchedulerHub'])

    def test_no_usable_station_raises_before_mutation(self):
        for native, bodies, actor, message in (
                (self.native(), dict(male=set(), female=set()), 'NPC', 'no male body animation'),
                (self.native(genders='1'), dict(male=set(), female={'TannerWashingIn', 'TannerWashing', 'TannerWashingOut'}),
                 'NPC_Female', 'excludes female'),
                (dict(self.native(), fragments=['A', 'B', 'C']), None, 'NPC', 'source plays')):
            mission, scheduler, item = self.prepared(actor)
            before = E.tostring(mission), E.tostring(scheduler)
            with self.assertRaisesRegex(ValueError, message):
                self.bind(mission, scheduler, item, native, bodies)
            self.assertEqual((E.tostring(mission), E.tostring(scheduler)), before)

    def test_registry_binds_once_per_anchor(self):
        mission, scheduler, item = self.prepared()
        pools = {}
        with patch.object(work, 'cached_program', return_value=self.native()), \
                patch.object(work, 'body_fragments', return_value=dict(male={'TannerWashingIn', 'TannerWashing', 'TannerWashingOut'})):
            job, waiting, report, activity = registry.bind(mission, scheduler, 'person', item, 'target', pools)
            again = registry.bind(mission, scheduler, 'person', dict(item, start_minute=1, end_minute=2), 'target', pools)
        self.assertEqual(activity, '')
        self.assertEqual(report['intervals'], [[item['start_minute'], item['end_minute']], [1, 2]])
        self.assertEqual(again, (None, [], None, None))


if __name__ == '__main__':
    unittest.main()
