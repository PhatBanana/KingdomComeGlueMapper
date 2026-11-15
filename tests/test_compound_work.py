from pathlib import Path
import sys
import unittest
from unittest.mock import patch
import xml.etree.ElementTree as E

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'tools'))
import character_compound_work as work
import character_work_adapters as registry
from campaign_entity_links import native_guid
from character_schedule_world import bind_arrivals
from character_person_activity import validate_scheduler_targets
import test_character_schedule_world as fixtures

Q = '&quot;{}&quot;'.format
SEARCH = ('<GraphSearch Origin="'+Q('t_compoundWorkplace')+'" depth="'+Q('1')+'" SubGraph="'+Q('compWork')+'">'
          '<LinkDataFilter condition="'+Q('$compWork.srcBeh == $__behaviorName')+'"/></GraphSearch>')
CALL = '<CallBehavior Target="'+Q('t_chosenWorkplace')+'" BehaviorName="'+Q('$t_chosenWork.behavior')+'"/>'
CORE = '<BehaviorTree name="{}"><Root><Behavior><Sequence>'+SEARCH+CALL+'</Sequence></Behavior></Root></BehaviorTree>'
WRAP = '<BehaviorTree name="{}"><Root><Behavior><IncludeTree File="'+Q('{}')+'" Name="'+Q('{}')+'"/></Behavior></Root></BehaviorTree>'
FILES = {
    'final/sa_compoundwork.xml': '<B>'+CORE.format('CompoundWork')+CORE.format('CompoundWork2_main')
        + WRAP.format('CompoundWorkLODGuarded', 'final/sa_compoundwork.xml', 'CompoundWork')
        + WRAP.format('CompoundWork2', 'final/sa_compoundWork.xml', 'CompoundWork2_main')
        + '<BehaviorTree name="carry"><Root><Behavior><Move/></Behavior></Root></BehaviorTree></B>',
    'final/sa_compoundworkcamp.xml': '<B>'+WRAP.format('CompoundWorkCamping', 'final/sa_compoundWork.xml', 'CompoundWork2_main')+'</B>',
    'final/sa_host.xml': '''<B><BehaviorTree name="onUpdate"><Root><Behavior><Sequence>
        <GraphSearch depth="&quot;1&quot;"><CategoryFilter categories="&quot;Tub&quot;"/><NegationOp><Child0>
          <LinkTagFilter tag="&quot;compWork&quot;"/></Child0></NegationOp></GraphSearch>
        <ForEach><AddLink From="&quot;this.id&quot;" Tag="&quot;compWork&quot;"
          Data="&quot;behavior('goBathe'), sourceSelf(true), srcBeh('Customer')&quot;"/></ForEach>
        <GraphSearch depth="&quot;1&quot;"><CategoryFilter categories="&quot;Seat&quot;"/><NegationOp><Child0>
          <LinkTagFilter tag="&quot;compWork&quot;"/></Child0></NegationOp></GraphSearch>
        <ForEach><Selector><Sequence><ReadMessage/><AddLink From="&quot;this.id&quot;" Tag="&quot;compWork&quot;"
          Data="&quot;behavior('goSit'), sourceSelf(true), srcBeh('Barber'), justIdle(true), capacity($size.size)&quot;"/>
        </Sequence></Selector></ForEach></Sequence></Behavior></Root></BehaviorTree>
      <BehaviorTree name="goSit"><Root><Behavior><Selector><Success/><CallBehavior Target="&quot;t_chosenWorkplace&quot;"
        BehaviorName="&quot;use&quot;"/></Selector></Behavior></Root><EditorData><Root><Behavior><Selector>
        <CallBehavior/></Selector></Behavior></Root></EditorData></BehaviorTree>
      <BehaviorTree name="work_data"><Root><Behavior><Expression expressions="&quot;$t_behaviorData.moveToOutside = true&quot;"/>
        </Behavior></Root></BehaviorTree>
      <BehaviorTree name="still_data"><Root><Behavior><Expression expressions="&quot;t_behaviorData.moveToArea = false&quot;"/>
        </Behavior></Root></BehaviorTree></B>''',
    'libs/ai/typedefinitions.xml': '''<T><Type name="compoundWork"><Member name="behavior">use</Member>
        <Member name="sourceSelf">false</Member><Member name="capacity">1</Member><Member name="srcBeh">use</Member>
        <Member name="justIdle">false</Member></Type></T>''',
}


class Lookup:
    def __init__(self, area=None, objects=None):
        self.area, self.objects = area or {}, objects or {}

    def trees(self, path):
        return E.fromstring(FILES[path.replace('\\', '/').lower()])

    def area_behaviors(self, template):
        return self.area

    def object_behaviors(self, template):
        return self.objects.get(template, {})


def thing(identity, cls='SmartObjectHolder', category='', helper='', template='', links=()):
    node = E.Element('Entity', EntityId=identity, EntityGuid='{'+identity+'}', EntityClass=cls, Name='e'+identity, Pos='1,2,3')
    E.SubElement(node, 'Properties', sWH_AI_EntityCategory=category, soclasses_SmartObjectHelpers=helper,
                 guidSmartObjectType=template)
    edges = E.SubElement(node, 'EntityLinks')
    for target, name in links:
        E.SubElement(edges, 'Link', TargetId=target, Name=name)
    return node


def bench(identity, category='Seat'):
    return thing(identity, category=category, helper='Bench_2Place_noTable', template='bench')


def entry(tree_name, tag, links, file='final/sa_compoundwork.xml'):
    return dict(behavior=dict(tree_file=file, tree_name=tree_name, sa_behaviour_tag_name=tag),
                binding=dict(sa_smart_area_id='area'), area=dict(EntityId='1', Name='area'), target_kind='smart_area',
                target_links=[dict(TargetId=t, Name=n) for t, n in links], start_minute=480, end_minute=720)


class RecognitionTests(unittest.TestCase):
    def test_rows_are_claimed_and_verified_against_their_core(self):
        lookup = Lookup()
        for identity, core in work.SOURCES.items():
            self.assertEqual(work.supports(entry(identity[1], 'x', [], identity[0])), identity in work.CLAIMED)
            self.assertTrue(work.recognize(lookup, identity, core))
        self.assertFalse(work.supports(entry('CompoundWork2', 'x', [])))
        self.assertTrue(work.recognize(lookup, ('final/sa_compoundWork.xml', 'CompoundWork2')))
        self.assertFalse(work.recognize(lookup, ('final/sa_compoundwork.xml', 'carry')))
        self.assertFalse(work.recognize(lookup, ('final/sa_compoundwork.xml', 'carry'), ('final/sa_compoundwork.xml', 'CompoundWork')))
        self.assertFalse(work.recognize(lookup, ('final/sa_compoundwork.xml', 'missing')))

    def test_nameless_includes_name_no_core(self):
        # Retail area trees mix named and nameless IncludeTree nodes (sas_dlouhej).
        tree = E.fromstring('<BehaviorTree name="w"><Root><Behavior><Sequence><IncludeTree File="'+Q('a.xml')+'"/>'
                            '<IncludeTree File="'+Q('b.xml')+'" Name="'+Q('x')+'"/></Sequence></Behavior></Root></BehaviorTree>')
        self.assertEqual(work.includes(tree, 'final/w.xml'), {('b.xml', 'x')})

    def test_core_needs_requested_behaviour_selection_and_chosen_call(self):
        self.assertTrue(work.is_core(E.fromstring(CORE.format('x'))))
        self.assertFalse(work.is_core(E.fromstring(CORE.format('x').replace('$__behaviorName', "'use'"))))
        self.assertFalse(work.is_core(E.fromstring(CORE.format('x').replace('$t_chosenWork.behavior', 'use'))))

    def test_authored_edges_use_type_defaults_and_requested_tag(self):
        defaults = work.work_defaults(Lookup().trees('Libs/AI/typedefinitions.xml'))
        links = [dict(TargetId='2', Name="compWork[srcBeh('Camping')],Seat"), dict(TargetId='3', Name='compWork,Lean'),
                 dict(TargetId='4', Name="compWork[behavior('carry'),srcBeh('Varlet'),sourceSelf(true)]"),
                 dict(TargetId='5', Name='inside'), dict(TargetId='6', Name='')]
        self.assertEqual([(l['TargetId'], w['behavior'], w['sourceSelf']) for l, w in work.link_works(links, defaults, 'Camping')],
                         [('2', 'use', 'false')])
        self.assertEqual([l['TargetId'] for l, _ in work.link_works(links, defaults, 'use')], ['3'])
        self.assertEqual([(w['behavior'], w['sourceSelf']) for _, w in work.link_works(links, defaults, 'Varlet')], [('carry', 'true')])

    def test_dynamic_rules_pair_each_added_edge_with_its_category_query(self):
        trees, defaults = Lookup().trees('final/sa_host.xml'), work.work_defaults(Lookup().trees('Libs/AI/typedefinitions.xml'))
        rules = work.dynamic_rules(trees, defaults, 'Barber')
        self.assertEqual([(c, w['behavior'], w['sourceSelf'], w['justIdle']) for c, w in rules], [('Seat', 'goSit', 'true', 'true')])
        self.assertEqual([c for c, _ in work.dynamic_rules(trees, defaults, 'Customer')], ['Tub'])
        self.assertEqual(work.dynamic_rules(trees, defaults, 'Other'), [])


class ResolveTests(unittest.TestCase):
    def resolve(self, item, world, lookup):
        by_id = {e.get('EntityId'): e for e in world}
        def targets(archive, request, entities, provenance):
            known = {e.get('EntityId') for e in entities}
            return [*entities, *(by_id[l.get('TargetId')] for l in request.findall('EntityLinks/Link')
                                 if l.get('TargetId') not in known)]
        with patch.object(work, 'read', return_value='<Objects/>'), \
             patch.object(work, 'resolve_link_targets', side_effect=targets), \
             patch.object(work, 'world_entity', side_effect=lambda a, e, es: e), \
             patch.object(work.area_wait, 'arrival_point', side_effect=lambda e, a, o: dict(EntityId='in', overrides=o)):
            return work.resolve(item, None, 'src', 'reader', lookup=lookup)

    def test_camp_flattens_group_objects_and_reports_other_works(self):
        world = [bench('2'), thing('3', category='sitGround', helper='sitGround', template='ground'),
                 thing('4', template='group', links=[('5', 'compWork'), ('6', 'compWork,Lean'), ('7', "compWork[srcBeh('Other')]")]),
                 bench('5'), thing('6', category='Lean', helper='LeaningSpot'), bench('7'), bench('8'),
                 thing('9', cls='TagPoint')]
        item = entry('CompoundWorkCamping', 'Camping', [('2', "compWork[srcBeh('Camping')],Seat"),
            ('3', "compWork[srcBeh('Camping')]"), ('4', "compWork[srcBeh('Camping')]"), ('8', "compWork[srcBeh('Guarding')]"),
            ('9', 'inside')], 'final/sa_compoundworkcamp.xml')
        lookup = Lookup(objects=dict(group=dict(use=('final/sa_compoundWork.xml', 'CompoundWork2')),
                                     bench=dict(use=('final/so_bench.xml', 'use'))))
        with patch.object(Lookup, 'trees', side_effect=lambda p: E.fromstring(FILES.get(p.replace('\\', '/').lower(), '<B/>'))):
            result = self.resolve(item, world, lookup)
        contract = result['compound_work']
        self.assertEqual([s['EntityId'] for s in contract['seats']], ['2', '5'])
        self.assertEqual([(p['behavior'], p['target_helper']) for p in contract['pending']],
                         [('use', 'sitGround'), ('use', 'LeaningSpot')])
        self.assertEqual((result['arrival']['EntityId'], contract['requested']), ('in', 'Camping'))

    def test_run_time_seat_edges_follow_the_host_rule_and_outside_arrival(self):
        world = [bench('2'), bench('3', 'Embroider'), bench('4', 'HealSeat'),
                 thing('5', category='Tub', helper='tub'), thing('6', cls='TagPoint')]
        item = entry('CompoundWorkLODGuarded', 'work', [('2', ''), ('3', ''), ('4', ''), ('5', ''), ('6', 'inside')])
        host = dict(goSit=('final/sa_host.xml', 'goSit'), work_data=('final/sa_host.xml', 'work_data'))
        FILES_BACKUP = FILES['final/sa_host.xml']
        FILES['final/sa_host.xml'] = FILES_BACKUP.replace("srcBeh('Barber')", "srcBeh('work')")
        try:
            result = self.resolve(item, world, Lookup(area=host))
        finally:
            FILES['final/sa_host.xml'] = FILES_BACKUP
        self.assertEqual([s['EntityId'] for s in result['compound_work']['seats']], ['2'])
        self.assertEqual(result['arrival']['overrides'], dict(moveToOutside=True))

    def test_carry_chores_are_a_contract_failure_not_idle_work(self):
        world = [thing('2', cls='SmartAreaShape'), thing('3', cls='TagPoint'), bench('4')]
        item = entry('CompoundWork', 'Varlet', [('2', "compWork[behavior('pickWoodBasket'),srcBeh('Varlet'),capacity(1)]"),
            ('3', "compWork[behavior('Varlet_carry'),srcBeh('Varlet'),sourceSelf(true)]"),
            ('4', "compWork[behavior('use'),srcBeh('Maid'),justIdle(true)]")])
        lookup = Lookup(area=dict(Varlet_carry=('final/sa_compoundwork.xml', 'carry')))
        with self.assertRaisesRegex(ValueError, 'no convertible work; pending: Varlet_carry@TagPoint, pickWoodBasket@SmartAreaShape'):
            self.resolve(item, world, lookup)

    def test_area_without_move_arrives_at_the_work_and_changed_tree_fails(self):
        item = entry('CompoundWork', 'still', [('2', "compWork[srcBeh('still')]")])
        result = self.resolve(item, [bench('2')], Lookup(area=dict(still_data=('final/sa_host.xml', 'still_data'))))
        self.assertEqual(result['arrival']['EntityId'], '2')
        changed = {'final/sa_compoundwork.xml': FILES['final/sa_compoundwork.xml'].replace('$__behaviorName', 'x')}
        with patch.dict(FILES, changed), self.assertRaisesRegex(ValueError, 'Unsupported source compound work'):
            self.resolve(item, [bench('2')], Lookup())


class BindTests(unittest.TestCase):
    def prepared(self, seats=('9',)):
        files, schedules, activity = fixtures.ScheduleWorldTests().fixture()
        mission = E.fromstring(files['objects_mission0.xml'])
        for index in (0, 1):
            seat = E.SubElement(mission, 'Entity', Name=f'gm_bench_9_{index}_StanceSmartObject', EntityId=str(10+index),
                                EntityGuid=native_guid(10+index), EntityClass='StanceSmartObject', Pos='1,2,3')
            E.SubElement(seat, 'Properties', guidSmartObjectType='seat', soclass_SmartObjectHelpers='Sit_1Place_Bench_Low')
        files['objects_mission0.xml'] = E.tostring(mission)
        item = schedules['person'][0]
        item['behavior'] = dict(tree_file='final/sa_compoundwork.xml', tree_name='CompoundWork')
        item['area'] = dict(EntityGuid='20')
        item['compound_work'] = dict(requested='Camping', seats=[dict(EntityId=s) for s in seats],
                                     pending=[dict(behavior='use', target_helper='sitGround', target_class='SmartObjectHolder')])
        with patch('character_schedule_world.native_wait_activity', return_value=(activity, None)):
            files, _ = bind_arrivals(files, schedules, None)
        native = E.fromstring('''<S_ActivityLink PositioningDelegate="0" TargetGuid="0"><Parameters AllowedGenders="0"
            BehaviorName="use" BehaviorOverride="false" Priority="0" TimeOfDayEnd="1440" TimeOfDayStart="0"/></S_ActivityLink>''')
        return E.fromstring(files['objects_mission0.xml']), E.fromstring(files['tables/ai/scheduler.xml']), item, native

    def test_arrival_becomes_a_hub_over_converted_shared_seats(self):
        mission, scheduler, item, native = self.prepared(seats=('9', '77'))
        with patch('character_city_benches.native_contract', return_value=('seat', native)):
            job, waiting, report = work.bind(mission, scheduler, 'person', item, None)
        self.assertEqual((job.get('EntityClass'), job.find('Properties').attrib), ('SchedulerHub', dict(bSaved_by_game='0')))
        self.assertEqual(len(waiting), 2)
        self.assertEqual([s['name'] for s in report['target_seats']],
                         ['gm_bench_9_0_StanceSmartObject', 'gm_bench_9_1_StanceSmartObject'])
        self.assertEqual([s['EntityId'] for s in report['unconverted_seats']], ['77'])
        self.assertEqual(report['interval'], [item['start_minute'], item['end_minute']])
        self.assertIn('use on sitGround', report['pending'])
        rows = scheduler.find('Schedulers')
        hub = next(r for r in rows if r.find('Links') is not None and r.tag == 'C_SmartHub'
                   and any(l.find('Parameters').get('BehaviorName') == 'use' for l in r.findall('Links/S_ActivityLink')))
        clocks = {(l.find('Parameters').get('TimeOfDayStart'), l.find('Parameters').get('TimeOfDayEnd'))
                  for l in hub.findall('Links/S_ActivityLink')}
        self.assertEqual(clocks, {(str(item['start_minute']), str(item['end_minute']))})
        validate_scheduler_targets(scheduler)

    def test_missing_conversion_or_foreign_holder_is_a_contract_failure(self):
        mission, scheduler, item, native = self.prepared(seats=('77',))
        with self.assertRaisesRegex(ValueError, 'no converted seat: 77'):
            work.bind(mission, scheduler, 'person', item, None)
        mission, scheduler, item, native = self.prepared()
        next(e for e in mission if e.get('Name', '').startswith('gm_schedule_')).find('Properties').set('guidSmartObjectType', 'x')
        with self.assertRaisesRegex(ValueError, 'importer-owned'):
            work.bind(mission, scheduler, 'person', item, None)

    def test_registry_row(self):
        self.assertEqual(registry.adapter_for(entry('CompoundWorkLODGuarded', 'x', []))[0].key, 'compound_work')
        # Seatless castle-varlet chores stay "adapter missing" residue.
        self.assertIsNone(registry.adapter_for(entry('CompoundWork', 'x', [])))


if __name__ == '__main__':
    unittest.main()
