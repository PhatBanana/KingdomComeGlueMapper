import sys
from pathlib import Path
import unittest
import xml.etree.ElementTree as ET

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from wildlife import source_sites, hare_sites, apply
from campaign_trigger_areas import write_areas, read_areas
from campaign_entity_links import guid_value, native_guid


class Wildlife(unittest.TestCase):
    def test_hare_polygon_transform_and_population_override(self):
        doc = ET.fromstring('''<Objects><Entity Name="forest" EntityGuid="123" Pos="100,200,0">
          <Properties guidSmartAreaTemplate="40b53966-60ca-d312-d919-54b6c741a2b8"><Script Misc="hares:3"/></Properties>
          <Area Height="40"><Points><Point Pos="0,0,0"/><Point Pos="20,0,0"/>
          <Point Pos="20,20,0"/><Point Pos="0,20,0"/></Points></Area>
        </Entity></Objects>''')
        result = hare_sites(doc, lambda x,y:10)
        self.assertEqual(len(result),1)
        self.assertEqual(result[0]['count'],3)
        self.assertEqual(result[0]['area']['points'][0],(100,200,0))
        x,y,z=result[0]['position']
        self.assertTrue(100<x<120 and 200<y<220)
        self.assertEqual(z,10)
        doc.find('Entity/Properties/Script').set('Misc','hares:0')
        self.assertEqual(hare_sites(doc,lambda x,y:10),[])

    def test_regional_links_do_not_double_self_linked_population(self):
        doc = ET.fromstring('''<Objects>
        <Entity Name="boar" EntityId="1" EntityGuid="123" Pos="10,20,30">
          <EntityLinks><Link TargetId="1" Name="animalSpawn[amount(2),class(Boar),radius(7.2),respawn(8h)] "/></EntityLinks>
        </Entity><Entity Name="regional" EntityId="2"><EntityLinks>
          <Link TargetId="1" Name="animalSpawn[amount(3),class(Boar),radius(5.2),respawn(28h)]"/>
        </EntityLinks></Entity></Objects>''')
        sites, deferred = source_sites(doc)
        self.assertEqual(len(sites), 1)
        self.assertEqual(sites[0]['count'], 2)
        self.assertAlmostEqual(sites[0]['respawn_days'], 1/3)
        self.assertEqual(len(deferred), 1)

    def test_remap_preserves_existing_data_and_rejects_repeat_install(self):
        sp = ET.fromstring('<Entity EntityId="1" EntityClass="AnimalSpawner"><Properties guidSoul="native"/><EntityLinks><Link TargetId="2" Name="spawnArea"/></EntityLinks></Entity>')
        area = ET.fromstring('<Entity EntityId="2" EntityClass="TriggerArea"/>')
        row = ET.fromstring('<C_SmartHub EntityGuid="1"><Links><S_ActivityLink TargetGuid="2" PositioningDelegate="2"/></Links></C_SmartHub>')
        template = dict(root='1', area='2', keys={'1','2'}, entities={'1':sp,'2':area}, rows={'1':row}, by_id={'1':'1','2':'2'})
        files = {'objects_mission0.xml': b'<Objects><Entity EntityId="9" EntityGuid="00000009-0000-0000" Name="keep"/></Objects>',
                 'tables/ai/scheduler.xml': b'<Table><Schedulers><C_SmartHub EntityGuid="9"/></Schedulers></Table>',
                 'triggerareas.fubar':write_areas([],1)}
        site=dict(guid='123', name='source', species='Boar', position=(10,20,30), count=2, radius=7.2, respawn_days=1/3)
        result, report = apply(files, [site], {'Boar':template})
        entities=list(ET.fromstring(result['objects_mission0.xml']))
        self.assertEqual(entities[0].get('Name'),'keep')
        self.assertEqual(len(entities),3)
        shapes=read_areas(result['triggerareas.fubar'])['areas']
        self.assertEqual(len(shapes),1)
        ids={str(guid_value(e.get('EntityGuid'))) for e in entities}
        for link in ET.fromstring(result['tables/ai/scheduler.xml']).iter('S_ActivityLink'):
            self.assertIn(link.get('TargetGuid'),ids)
            self.assertIn(link.get('PositioningDelegate'),ids)
        self.assertEqual(native_guid(shapes[0].guid),next(e.get('EntityGuid') for e in entities if e.get('EntityClass')=='TriggerArea'))
        for x,y,z in shapes[0].points:
            self.assertLessEqual((x-10)**2+(y-20)**2,7.2**2+.001)
            self.assertEqual(z,25)
        with self.assertRaisesRegex(ValueError,'already installed'):
            apply(result,[site],{'Boar':template})


if __name__ == '__main__':
    unittest.main()
