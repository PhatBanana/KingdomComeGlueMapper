import copy
from pathlib import Path
import sys
import unittest
import xml.etree.ElementTree as E

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'tools'))
from character_water_source import resolve, conflicting_tools, bucket_contract
from character_water_work import refill_graph, well_group
from character_city_benches import signature
from campaign_entity_links import native_guid


class WaterSourceTests(unittest.TestCase):
    def test_fill_before_pour_and_origin_alignment_are_required(self):
        program = E.fromstring('''<Program><BehaviorTree name="Waterfill_waterTube_refill"><Root>
          <CallBehavior Target="t_fillSpot" BehaviorName="use"/>
          <Expression expressions="$t_queue_params.actionBehavior.behavior = 'refill_tube'"/>
          <CallBehavior Target="t_waterTube" BehaviorName="manageQueue"/>
          </Root></BehaviorTree></Program>''')
        helpers = E.fromstring('<SmartObjects><Helper className="Well" name="gate" pos="0,0,0" rot="1,0,0,0"/></SmartObjects>')
        bucket_contract(program,helpers)
        helpers[0].set('pos','1,0,0')
        with self.assertRaises(ValueError): bucket_contract(program,helpers)
        helpers[0].set('pos','0,0,0')
        program.find('.//CallBehavior').set('Target','differentResource')
        with self.assertRaises(ValueError): bucket_contract(program,helpers)

    def fixture(self):
        def entity(key, category='', position='5,5,1'):
            e = E.Element('Entity', EntityId=key, EntityGuid=key, Pos=position)
            E.SubElement(e, 'Properties', sWH_AI_EntityCategory=category)
            E.SubElement(e, 'EntityLinks')
            return e
        es = {k: entity(k, cat) for k, cat in [('1',''),('2','Watertub'),('3','bucket'),('4','Well'),('5','Well'),('6','')]}
        for key in ('2', '3'): E.SubElement(es['1'].find('EntityLinks'), 'Link', TargetId=key, Name='')
        city = es['6']; city.set('EntityClass', 'SmartAreaShape'); city.set('Pos', '0,0,0')
        city.find('Properties').set('guidSmartAreaTemplate', 'city')
        E.SubElement(city.find('EntityLinks'), 'Link', TargetId='4', Name='')
        points = E.SubElement(E.SubElement(city, 'Area', Height='10'), 'Points')
        for pos in ('0,0,0','10,0,0','10,10,0','0,10,0'): E.SubElement(points, 'Point', Pos=pos)
        return dict(area=dict(EntityId='1')), es

    def test_city_uses_linked_well_not_nearest_unlinked_well(self):
        entry, es = self.fixture()
        es['4'].set('Pos', '9,9,1'); es['5'].set('Pos', '5,5,1')
        result = resolve(entry, es, {'city'})
        self.assertEqual([e.get('EntityId') for e in result['sources']], ['4'])
        self.assertEqual(result['provider'].get('EntityId'), '6')

    def test_home_well_takes_precedence(self):
        entry, es = self.fixture()
        E.SubElement(es['1'].find('EntityLinks'), 'Link', TargetId='5', Name='')
        self.assertEqual([e.get('EntityId') for e in resolve(entry, es, {'city'})['sources']], ['5'])

    def test_missing_and_ambiguous_providers_do_not_assign_arbitrary_well(self):
        entry, es = self.fixture()
        with self.assertRaises(ValueError): resolve(entry, es, set())
        es['7'] = copy.deepcopy(es['6']); es['7'].set('EntityId','7'); es['7'].set('EntityGuid','7')
        with self.assertRaises(ValueError): resolve(entry, es, {'city'})

    def test_missing_bucket_does_not_borrow_other_households_tool(self):
        entry, es = self.fixture()
        es['1'].find('EntityLinks').remove(es['1'].find("EntityLinks/Link[@TargetId='3']"))
        with self.assertRaises(ValueError): resolve(entry, es, {'city'})

    def test_shared_tub_only_accepts_the_same_authored_tool_pool(self):
        entry, es = self.fixture()
        a = resolve(entry, es, {'city'}); b = dict(a)
        self.assertEqual(conflicting_tools([a,b]),set())
        other = copy.deepcopy(es['3']); other.set('EntityGuid','other-home-bucket')
        b['buckets'] = [other]
        self.assertEqual(conflicting_tools([a,b]),{'2'})


class WaterGraphTests(unittest.TestCase):
    def test_well_dependencies_follow_source_rotation_and_replace_only_its_visual(self):
        m = E.fromstring('<Objects><Entity EntityId="90" Name="glue_item_1"/><Entity EntityId="91" Name="keep"/></Objects>')
        source = E.fromstring('''<Entity EntityId="1" EntityGuid="ABC" EntityClass="AnimObject"
          Pos="10,20,30" Rotate="0.7071067811865476,0,0,0.7071067811865476">
          <Properties object_Model="objects/well.cdf" soclasses_SmartObjectHelpers="Well"/></Entity>''')
        def donor(role, key, pos):
            e = E.Element('Entity', Name=role, EntityId=str(key), EntityGuid=native_guid(key), Pos=pos,
                          EntityClass={'holder':'SmartObjectHolder','animObject':'AnimObject','slot':'ItemSlot'}[role])
            E.SubElement(e,'Properties',object_Model='Data/objects/well.cdf')
            return e
        contract = dict(well=donor('holder',100,'100,200,300'),
            group=dict(animObject=donor('animObject',101,'100,200,300'),slot=donor('slot',102,'101,200,300')),
            well_leaf=E.Element('C_SmartHub',EntityGuid='100'))
        pair, waiting = well_group(m,source,{'1':source},contract)
        self.assertEqual(len(waiting),2)
        self.assertIsNone(m.find("Entity[@Name='glue_item_1']"))
        self.assertIsNotNone(m.find("Entity[@Name='keep']"))
        slot = m.find("Entity[@EntityClass='ItemSlot']")
        for actual, expected in zip(map(float,slot.get('Pos').split(',')),(10,21,30)):
            self.assertAlmostEqual(actual,expected)
        before = signature(m)
        well_group(m,source,{'1':source},contract)
        self.assertEqual(before,signature(m))
        source.set('Pos','11,20,30')
        with self.assertRaises(ValueError): well_group(m,source,{'1':source},contract)

    def test_refill_preserves_washing_and_repeats_without_duplicate_links(self):
        m = E.Element('Objects')
        tub = E.SubElement(m, 'Entity', EntityId='10', EntityGuid=native_guid(10), Pos='1,2,3')
        well = E.SubElement(m, 'Entity', EntityId='11', EntityGuid=native_guid(11), Pos='4,5,6')
        s = E.fromstring('<database><Schedulers><C_SmartHub EntityGuid="10" IgnoreDeadEnds="false" StupidHub="false">'
            '<PostSearchData><SmartHubPostSearchData><SchedulerEffect><EffectClean Role="washFace" CleanTarget="0.9"/>'
            '</SchedulerEffect></SmartHubPostSearchData></PostSearchData></C_SmartHub></Schedulers></database>')
        clean = signature(s.find('.//EffectClean'))
        native = E.fromstring('<C_SmartHub><PostSearchData><SmartHubPostSearchData><SchedulerEffect>'
            '<EffectSoil Role="refillWatertube" SoilRate="1.000000"/></SchedulerEffect></SmartHubPostSearchData></PostSearchData></C_SmartHub>')
        edge = E.fromstring('<S_ActivityLink TargetGuid="0"><Parameters BehaviorName="refillWatertube" BehaviorOverride="false"/></S_ActivityLink>')
        c = dict(tub_row=native, well_edge=edge, source_edge=copy.deepcopy(edge), source_definition='_refillWatertube|,23:00,')
        sources=[(well,E.Element('C_SmartHub', EntityGuid='11'))]
        first = refill_graph(m,s,tub,sources,c)
        self.assertEqual(signature(s.find('.//EffectClean')), clean)
        self.assertEqual(len(s.findall('.//EffectSoil')),1)
        before = signature(m),signature(s)
        second = refill_graph(m,s,tub,sources,c)
        self.assertEqual(before,(signature(m),signature(s)))
        self.assertEqual(signature(first[1][1]),signature(second[1][1]))
        s.find('.//EffectSoil').set('SoilRate','99')
        with self.assertRaises(ValueError): refill_graph(m,s,tub,sources,c)


if __name__ == '__main__': unittest.main()
