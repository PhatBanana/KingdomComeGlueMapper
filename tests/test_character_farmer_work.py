import copy
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
import xml.etree.ElementTree as E
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'tools'))
import character_farmer_work as farm
from character_schedule_jobs import population_work_supports, bind_jobs
from campaign_entity_links import guid_value
from cooking_pots import rotate
import test_character_city_work as fixture


PROGRAM = b'''<BehaviorTrees><BehaviorTree name="Farmer"><Root>
<GraphSearch SubGraph="Home" depth="1"/><SlotClassFilter ClassId="hoe"/>
</Root></BehaviorTree><BehaviorTree name="Farmer_main"><Root>
<GraphSearch Origin="__area.id" depth="1"><LinkTagFilter tag="rowStart"/></GraphSearch>
<GraphSearch Origin="__area.id" depth="1"><LinkTagFilter tag="rowEnd"/></GraphSearch>
<GraphSearch Origin="__area.id" depth="1"><LinkTagFilter tag="fieldEnd"/></GraphSearch>
</Root></BehaviorTree></BehaviorTrees>'''


class FarmerTests(unittest.TestCase):
    def native(self):
        props = E.Element('Properties', guidSmartObjectType='native')
        activity = E.fromstring('''<S_ActivityLink TargetGuid="8" PositioningDelegate="0"><Parameters
            BehaviorName="hoeing" ProvidedRole="hoeing" TimeOfDayStart="0" TimeOfDayEnd="1440"/></S_ActivityLink>''')
        terminal = E.fromstring('''<C_SmartHub EntityGuid="8"><PostSearchData><SmartHubPostSearchData>
            <SchedulerEffect><EffectSoil Role="hoeing" SoilRate="5.000000"/></SchedulerEffect>
            </SmartHubPostSearchData></PostSearchData></C_SmartHub>''')
        contract = dict(item_id='hoe', properties=E.Element('Properties'), behavior='hoeing', decision='farmer_hoe',
            definition="schedulerReservedItem['hoeing','farmer_hoe']", direct_links=[])
        return props, activity, terminal, contract

    def prepared(self):
        files, schedules = fixture.CityWorkTests().prepared()
        for e in schedules['person']:
            e.pop('city_work', None)
            e['behavior'] = dict(tree_file=farm.SOURCE[0], tree_name=farm.SOURCE[1])
            e['farmer_work'] = dict(item_id='hoe', row_count=6, slots=[
                '<Entity EntityClass="ItemSlot" EntityGuid="FF" EntityId="99" Pos="1,2,3"><Properties guidItemClassId="hoe"/></Entity>'],
                points=dict(rowStart=dict(Pos='10,20,30'), rowEnd=dict(Pos='10,30,30'), fieldEnd=dict(Pos='20,20,30')))
        return files, schedules

    def test_selection_uses_behavior_not_person_or_gender(self):
        entry = dict(behavior=dict(tree_file='final\\sa_farm.xml', tree_name='Farmer'))
        self.assertTrue(population_work_supports(entry))
        entry['behavior']['tree_name'] = 'Farmer_main'
        self.assertFalse(farm.supports(entry))

    def test_row_facing_and_degenerate_input(self):
        for end, direction in [('10,0,0', (1,0,0)), ('0,10,0', (0,1,0)), ('-10,0,0', (-1,0,0))]:
            q = tuple(map(float, farm.row_rotation('0,0,0', end).split(',')))
            for a, b in zip(rotate(q, (0,1,0)), direction): self.assertAlmostEqual(a,b,places=8)
        for end in ('0,0,1', 'nan,0,0', '0.1,0,0'):
            with self.assertRaises(ValueError): farm.row_rotation('0,0,0', end)

    def test_source_contract_rejects_changed_search(self):
        self.assertEqual(farm.source_contract(PROGRAM), 'hoe')
        for change in (PROGRAM.replace(b'depth="1"', b'depth="2"'), PROGRAM.replace(b'rowEnd', b'other')):
            with self.assertRaises(ValueError): farm.source_contract(change)

    def test_rows_preserve_source_spacing_and_height(self):
        points=dict(rowStart=dict(Pos='1,2,3'), rowEnd=dict(Pos='1,12,4'), fieldEnd=dict(Pos='13,2,9'))
        rows=farm.field_rows(points,6)
        self.assertEqual(rows[0],('1,2,3','1,12,4'))
        self.assertEqual(rows[-1],('11,2,8','11,12,9'))
        for count in (0,129,1.5,True):
            with self.assertRaises(ValueError):farm.field_rows(points,count)
        points['fieldEnd']['Pos']='1,22,3'
        with self.assertRaisesRegex(ValueError,'overlap'):farm.field_rows(points,6)

    def test_row_count_requires_source_geometry_contract(self):
        program=E.fromstring(PROGRAM)
        main=program.find("BehaviorTree[@name='Farmer_main']")
        E.SubElement(E.SubElement(main,'Variables'),'Variable',name='fieldProperties',type='fieldProperties')
        for axis in 'xyz':
            E.SubElement(main.find('Root'),'Expression',expressions='$nextRowStep.'+axis+' /= $rowCountFloat')
        definitions=b'<Types><Type name="fieldProperties"><Member name="numberOfRows" type="int">6</Member></Type></Types>'
        blob=E.tostring(program)
        self.assertEqual(farm.source_row_count(blob,definitions),6)
        for changed in (definitions.replace(b'>6<',b'>0<'),definitions.replace(b'>6<',b'>129<'),definitions.replace(b'"int"',b'"float"')):
            with self.assertRaises(ValueError):farm.source_row_count(blob,changed)
        with self.assertRaises(ValueError):farm.source_row_count(blob.replace(b'/=',b'*='),definitions)
        main.find('Variables/Variable').set('values','different-field')
        with self.assertRaises(ValueError):farm.source_row_count(E.tostring(program),definitions)

    def test_missing_hoe_fails_instead_of_spawning_a_fake_tool(self):
        files, schedules = self.prepared()
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)/'source.pak'
            with zipfile.ZipFile(path,'w') as z: z.writestr('objects_mission0.xml','<Objects/>')
            with zipfile.ZipFile(path) as archive, patch.object(farm,'native_contract',return_value=self.native()):
                with self.assertRaisesRegex(ValueError, 'Unregistered job item'):
                    bind_jobs(files, schedules, archive, None, {})

    def test_binding_keeps_clocks_adds_reserved_tool_and_native_field_edges(self):
        files, schedules = self.prepared()
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)/'source.pak'
            with zipfile.ZipFile(path,'w') as z: z.writestr('objects_mission0.xml','<Objects/>')
            with zipfile.ZipFile(path) as archive, patch.object(farm,'native_contract',return_value=self.native()):
                result, report = bind_jobs(files, schedules, archive, None, {'hoe':'hoe'})
        mission=E.fromstring(result['objects_mission0.xml'])
        fields=[e for e in mission if e.get('Name','').startswith('gm_farmer_') and e.get('EntityClass')=='SmartObjectHolder']
        self.assertEqual(len(fields),6)
        field=fields[0]
        labels={l.get('Name') for l in field.findall('EntityLinks/Link')}
        self.assertTrue({"hoeingPoint['first']", "hoeingPoint['second']", "+Soil[hoeing,5]",
            "schedulerReservedItem['hoeing','farmer_hoe']"} <= labels)
        old=E.fromstring(files['tables/ai/scheduler.xml']);new=E.fromstring(result['tables/ai/scheduler.xml'])
        actor=mission.find("Entity[@Name='person']")
        guid=str(guid_value(actor.get('EntityGuid')))
        def clocks(root):
            return [(l.find('Parameters').get('TimeOfDayStart'), l.find('Parameters').get('TimeOfDayEnd'))
                for l in root.find("Schedulers/C_SmartHub[@EntityGuid='"+guid+"']").findall('Links/S_ActivityLink')]
        self.assertEqual(clocks(old),clocks(new))
        self.assertFalse(report[0]['runtime_verified'])
        self.assertEqual(len(report[0]['fields']),6)
        self.assertIn('source rain-shelter selection',report[0]['pending'])
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'source.pak'
            with zipfile.ZipFile(path,'w') as z:z.writestr('objects_mission0.xml','<Objects/>')
            with zipfile.ZipFile(path) as archive, patch.object(farm,'native_contract',return_value=self.native()):
                with self.assertRaisesRegex(ValueError,'non-owned farmer arrival'):
                    bind_jobs(result,schedules,archive,None,{'hoe':'hoe'})

    def test_conflicting_resolved_fields_rejected(self):
        files,schedules=self.prepared()
        schedules['person'].append(copy.deepcopy(schedules['person'][0]))
        schedules['person'][-1]['farmer_work']['points']['rowEnd']['Pos']='999,999,999'
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'source.pak'
            with zipfile.ZipFile(path,'w') as z:z.writestr('objects_mission0.xml','<Objects/>')
            with zipfile.ZipFile(path) as archive, patch.object(farm,'native_contract',return_value=self.native()):
                with self.assertRaisesRegex(ValueError,'Different farms'):
                    bind_jobs(files,schedules,archive,None,{'hoe':'hoe'})


if __name__ == '__main__': unittest.main()
