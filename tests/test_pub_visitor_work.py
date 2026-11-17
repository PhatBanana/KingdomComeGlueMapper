from pathlib import Path
import sys
import unittest
import xml.etree.ElementTree as E
sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'tools'))
import character_pub_visitor_work as work
import character_work_adapters as registry
from campaign_entity_links import guid_value
from character_schedule_world import ARRIVAL_TEMPLATE

SEAT_TEMPLATE = '57cbebae-c19a-443b-8945-999d8ee87955'

PUB = '''<BehaviorTrees>
<BehaviorTree name="PubVisitor"><Root><Behavior><Sequence>
  <GraphSearch Origin="&quot;__area.id&quot;" depth="&quot;1&quot;" EdgePruning="&quot;parent&quot;" includeOrigin="&quot;false&quot;" AllowedEdges="" SubGraph="">
    <CategoryFilter categories="&quot;pubTable&quot;"/>
    <NegationOp><Child0><LinkTagFilter tag="&quot;reserved&quot;"/></Child0></NegationOp>
    <Nodalyzer Quantifiers="&quot;ForAll&quot;" Child="&quot;tables&quot;"/>
  </GraphSearch>
  <GraphSearch Origin="&quot;__area.id&quot;" depth="&quot;1&quot;" EdgePruning="&quot;parent&quot;">
    <CategoryFilter categories="&quot;diceTable&quot;"/><Nodalyzer Quantifiers="&quot;ForAll&quot;"/>
  </GraphSearch>
  <Expression expressions="&quot;$t_nextBehavior.id = $__area.id \n$t_nextBehavior.name = 'Customer'&quot;"/>
  <CallBehavior Target="&quot;t_pubTable&quot;" BehaviorName="&quot;getBench&quot;"/>
</Sequence></Behavior></Root></BehaviorTree>
<BehaviorTree name="waitTillPubOpens"><Root><Behavior>
  <CallBehavior Target="&quot;__area.id&quot;" BehaviorName="&quot;PubVisitor&quot;"/>
</Behavior></Root></BehaviorTree>
</BehaviorTrees>'''

SEARCH = '''<GraphSearch Origin="&quot;__area.id&quot;" depth="&quot;1&quot;" EdgePruning="&quot;parent,inventory&quot;" includeOrigin="&quot;false&quot;">
  <LinkTagFilter tag="&quot;pub&quot;"/>
  <HasBehaviorFilter BehaviorList="&quot;PubVisitor&quot;" Source="&quot;Child&quot;"/>
  <Nodalyzer Quantifiers="&quot;Exists&quot;" Child="&quot;pub&quot;"/></GraphSearch>'''
COMPANION = ('<BehaviorTrees><BehaviorTree name="Visitor"><Root><OnInit>' + SEARCH + '</OnInit><Behavior><Sequence>'
             + SEARCH + '<CallBehavior Target="&quot;pub&quot;" BehaviorName="&quot;PubVisitor&quot;"/>' + SEARCH
             + '<CallBehavior Target="&quot;__area.id&quot;" BehaviorName="&quot;hangingOut&quot;"/>'
             '</Sequence></Behavior></Root></BehaviorTree></BehaviorTrees>')


def entry(tree_file, tree_name, **extra):
    return dict(behavior=dict(tree_file=tree_file, tree_name=tree_name), start_minute=600, end_minute=1200, **extra)


def documents():
    return {work.PUB_FILE: E.fromstring(PUB), 'final/sa_pubcomp.xml': E.fromstring(COMPANION)}


class RowTests(unittest.TestCase):
    def test_one_row_per_source_tree_identity(self):
        self.assertTrue(work.supports(entry('final/sa_pub_v3.xml', 'PubVisitor')))
        self.assertTrue(work.supports(entry('Final\\SA_Pub_v3.xml', 'waitTillPubOpens')))
        self.assertTrue(work.supports(entry('final/sa_pubcomp.xml', 'Visitor')))
        for other in (('final/sa_pub_v3.xml', 'Bartender'), ('final/sa_pub_v3.xml', 'Customer'),
                      ('final/sa_pubcomp.xml', 'PubVisitor'), ('final/sa_city.xml', 'Visitor')):
            self.assertFalse(work.supports(entry(*other)), other)
        self.assertEqual(len({(r.tree_file, r.tree_name) for r in work.ROWS}), len(work.ROWS))

    def test_registry_dispatches_to_this_module_under_its_key(self):
        claim = registry.adapter_for(entry('final/sa_pubcomp.xml', 'Visitor'))
        self.assertIsNotNone(claim)
        self.assertEqual((claim[0].module, claim[0].key), ('character_pub_visitor_work', work.KEY))

    def test_resolve_refuses_missing_source(self):
        with self.assertRaises(ValueError):
            work.resolve(entry('final/sa_pub_v3.xml', 'PubVisitor'), None, None, None)


class ContractTests(unittest.TestCase):
    def test_every_row_accepts_its_source_shape(self):
        for row in work.ROWS:
            work.source_contract(row, documents())

    def test_table_selection_cannot_widen(self):
        for path, key, value in (('.//GraphSearch', 'depth', '2'), ('.//GraphSearch', 'Origin', 'this.id'),
                                 ('.//GraphSearch', 'EdgePruning', 'parent,inventory'),
                                 ('.//GraphSearch', 'SubGraph', 'child'),
                                 ('.//LinkTagFilter', 'tag', 'other'), ('.//Nodalyzer', 'Quantifiers', 'Exists'),
                                 ('.//CallBehavior', 'BehaviorName', 'use'), ('.//Expression', 'expressions', '')):
            with self.subTest(path=path, key=key):
                docs = documents()
                docs[work.PUB_FILE].find("BehaviorTree[@name='PubVisitor']").find(path).set(key, value)
                with self.assertRaises(ValueError):
                    work.source_contract(work.ROWS[0], docs)

    def test_forwarder_must_stay_a_single_call_on_its_own_area(self):
        row = next(r for r in work.ROWS if r.contract == 'forwarder')
        docs = documents()
        docs[work.PUB_FILE].find("BehaviorTree[@name='waitTillPubOpens']//CallBehavior").set('Target', 'other')
        with self.assertRaises(ValueError):
            work.source_contract(row, docs)
        docs = documents()
        E.SubElement(docs[work.PUB_FILE].find("BehaviorTree[@name='waitTillPubOpens']/Root/Behavior"), 'Wait')
        with self.assertRaises(ValueError):
            work.source_contract(row, docs)

    def test_companion_must_follow_the_pub_link(self):
        row = next(r for r in work.ROWS if r.contract == 'companion')
        for path, key, value in (('.//Behavior//LinkTagFilter', 'tag', 'Home'),
                                 ('.//Behavior//HasBehaviorFilter', 'BehaviorList', 'Bartender'),
                                 ('.//Behavior//GraphSearch', 'depth', '-1'),
                                 ('.//Behavior//CallBehavior', 'BehaviorName', 'Customer')):
            with self.subTest(path=path):
                docs = documents()
                docs['final/sa_pubcomp.xml'].find(path).set(key, value)
                with self.assertRaises(ValueError):
                    work.source_contract(row, docs)

    def test_missing_tree_is_a_contract_failure(self):
        docs = documents()
        docs[work.PUB_FILE] = E.fromstring('<BehaviorTrees/>')
        with self.assertRaises(ValueError):
            work.source_contract(work.ROWS[0], docs)


class PubAreaTests(unittest.TestCase):
    def test_direct_rows_use_the_activity_area(self):
        e = entry('final/sa_pub_v3.xml', 'PubVisitor', area=dict(EntityId='1', Name='pub'),
                  target_links=[dict(Name='', TargetId='9')])
        self.assertEqual(work.pub_area(work.row_for(e), e, None, []),
                         (dict(EntityId='1', Name='pub'), [dict(Name='', TargetId='9')]))

    def companion(self, links, pub_class='SmartAreaShape'):
        pub = E.fromstring('<Entity EntityId="7" EntityClass="%s" Name="p"><EntityLinks>'
                           '<Link Name="" TargetId="70"/></EntityLinks></Entity>' % pub_class)
        other = E.fromstring('<Entity EntityId="8" EntityClass="TagPoint"/>')
        e = entry('final/sa_pubcomp.xml', 'Visitor', area=dict(EntityId='1'), target_links=links)
        return work.pub_area(work.row_for(e), e, None, [pub, other])

    def test_companion_follows_exactly_one_pub_link(self):
        area, links = self.companion([dict(Name='pub', TargetId='7'), dict(Name='inside', TargetId='8')])
        self.assertEqual(area['EntityId'], '7')
        self.assertEqual(links, [dict(Name='', TargetId='70')])
        for bad in ([dict(Name='inside', TargetId='8')],
                    [dict(Name='pub', TargetId='7'), dict(Name='pub', TargetId='8')],
                    [dict(Name='pub,parent', TargetId='7')]):
            with self.assertRaises(ValueError):
                self.companion(bad)
        with self.assertRaises(ValueError):
            self.companion([dict(Name='pub', TargetId='7')], pub_class='TagPoint')


def world(seat_names=('gm_bench_50_0_StanceSmartObject', 'gm_bench_50_1_StanceSmartObject',
                      'gm_bench_51_0_StanceSmartObject')):
    mission = E.Element('Mission')
    E.SubElement(mission, 'Entity', Name='bob', EntityClass='NPC', EntityGuid='00000000-0000-0001', EntityId='1')
    job = E.SubElement(mission, 'Entity', Name='gm_schedule_bob_50', EntityClass='SmartObjectHolder',
                       EntityGuid='00000000-0000-0002', EntityId='2', Pos='1,2,3')
    E.SubElement(job, 'Properties', guidSmartObjectType=ARRIVAL_TEMPLATE, bSaved_by_game='0')
    for index, name in enumerate(seat_names):
        seat = E.SubElement(mission, 'Entity', Name=name, EntityClass='StanceSmartObject',
                            EntityGuid='00000000-0000-00%02d' % (10+index), EntityId=str(10+index), Pos='0,0,0')
        E.SubElement(seat, 'Properties', guidSmartObjectType=SEAT_TEMPLATE,
                     soclass_SmartObjectHelpers='Sit_1Place_Bench_Low_Table_Right')
    scheduler = E.Element('database')
    rows = E.SubElement(scheduler, 'Schedulers')
    owner = E.SubElement(rows, 'C_SmartHub', EntityGuid=str(guid_value('00000000-0000-0001')))
    links = E.SubElement(owner, 'Links')
    for start, end in ((600, 1200),):
        link = E.SubElement(links, 'S_ActivityLink', PositioningDelegate='0',
                            TargetGuid=str(guid_value('00000000-0000-0002')))
        E.SubElement(link, 'Parameters', BehaviorName='use', BehaviorOverride='false',
                     TimeOfDayStart=str(start), TimeOfDayEnd=str(end))
    E.SubElement(rows, 'C_SmartHub', EntityGuid=str(guid_value('00000000-0000-0002')))
    return mission, scheduler


def native():
    link = E.Element('S_ActivityLink', PositioningDelegate='0', TargetGuid='0')
    E.SubElement(link, 'Parameters', BehaviorName='use', BehaviorOverride='false', AllowedGenders='0',
                 TimeOfDayStart='0', TimeOfDayEnd='1440')
    return SEAT_TEMPLATE, link


def resolved(seat_ids=('50', '51')):
    seats = [dict(EntityId=i, EntityGuid='aaaa-' + i, Pos='0,0,0') for i in seat_ids]
    return entry('final/sa_pub_v3.xml', 'PubVisitor', area=dict(EntityId='1'), target_links=[],
                 arrival=seats[0], **{work.KEY: dict(source=['final/sa_pub_v3.xml', 'PubVisitor'],
                 pub=dict(EntityId='1'), seats=seats, pending=['x'])})


class BindTests(unittest.TestCase):
    def test_arrival_becomes_a_hub_over_every_converted_place(self):
        mission, scheduler = world()
        job, waiting, report = work.bind(mission, scheduler, 'bob', resolved(), None, contract=native())
        self.assertEqual(job.get('EntityClass'), 'SchedulerHub')
        self.assertIsNone(job.find('Properties').get('guidSmartObjectType'))
        self.assertEqual([l.get('Name') for l in job.findall('EntityLinks/Link')], ['_,use']*3)
        rows = scheduler.find('Schedulers')
        hub = next(r for r in rows if r.get('EntityGuid') == str(guid_value('00000000-0000-0002')))
        out = hub.findall('Links/S_ActivityLink')
        self.assertEqual(len(out), 3)
        for link in out:
            p = link.find('Parameters')
            self.assertEqual((p.get('BehaviorName'), p.get('BehaviorOverride'), p.get('TimeOfDayStart'),
                              p.get('TimeOfDayEnd')), ('use', 'false', '600', '1200'))
            self.assertEqual(len([r for r in rows if r.get('EntityGuid') == link.get('TargetGuid')]), 1)
        incoming = rows[0].find('Links/S_ActivityLink/Parameters')
        self.assertIsNone(incoming.get('BehaviorName'))
        self.assertEqual(len(waiting), 3)
        self.assertEqual(report['interval'], [600, 1200])
        self.assertEqual(report['job'], 'native_pub_seat')
        self.assertEqual(report['pending'], ['x'])
        self.assertFalse(report['runtime_verified'])

    def test_unconverted_benches_are_reported_not_invented(self):
        mission, scheduler = world()
        _, _, report = work.bind(mission, scheduler, 'bob', resolved(('50', '51', '99')), None, contract=native())
        self.assertEqual(report['unconverted_source_seats'], ['99'])
        self.assertEqual(len(report['target_seats']), 3)

    def test_failures_raise_before_any_mutation(self):
        cases = {}
        mission, scheduler = world(seat_names=())
        cases['no converted bench'] = (mission, scheduler)
        mission, scheduler = world()
        mission.find("Entity[@Name='gm_bench_51_0_StanceSmartObject']/Properties").set('guidSmartObjectType', 'x')
        cases['foreign seat template'] = (mission, scheduler)
        mission, scheduler = world()
        mission.find("Entity[@Name='gm_schedule_bob_50']/Properties").set('guidSmartObjectType', 'x')
        cases['arrival not importer-owned'] = (mission, scheduler)
        mission, scheduler = world()
        scheduler.find('.//Parameters').set('BehaviorName', 'guard')
        cases['arrival already rebound'] = (mission, scheduler)
        mission, scheduler = world()
        seat = E.SubElement(scheduler.find('Schedulers'), 'C_SmartHub', EntityGuid=str(guid_value('00000000-0000-0010')))
        E.SubElement(seat, 'Links')
        cases['seat with scheduler dependencies'] = (mission, scheduler)
        for label, (mission, scheduler) in cases.items():
            with self.subTest(label):
                before = E.tostring(mission), E.tostring(scheduler)
                with self.assertRaises(ValueError):
                    work.bind(mission, scheduler, 'bob', resolved(), None, contract=native())
                self.assertEqual(before, (E.tostring(mission), E.tostring(scheduler)))

    def test_registry_pools_repeated_intervals_on_one_anchor(self):
        mission, scheduler = world()
        original = work.bind
        work.bind = lambda *a, **k: original(*a, contract=native(), **k)
        try:
            pools = {}
            first = registry.bind(mission, scheduler, 'bob', resolved(), None, pools)
            second = registry.bind(mission, scheduler, 'bob', dict(resolved(), start_minute=0, end_minute=60), None, pools)
        finally:
            work.bind = original
        self.assertEqual(first[3], '')
        self.assertEqual(second, (None, [], None, None))
        self.assertEqual(first[2]['intervals'], [[600, 1200], [0, 60]])


if __name__ == '__main__':
    unittest.main()
