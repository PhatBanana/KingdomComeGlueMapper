import sys
from pathlib import Path
import unittest
import xml.etree.ElementTree as E
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from character_crime_districts import contains, convert
from character_person_world import source_home_geometry
from campaign_entity_links import native_guid
from campaign_trigger_areas import read_areas,write_areas


class DistrictTests(unittest.TestCase):
    def source(self, identity, name):
        return E.fromstring(f'<Entity EntityGuid="{identity:X}" EntityId="{identity}" EntityClass="SmartAreaShape" Name="{name}" Pos="10,20,30">'
            '<Area Height="8"><Points><Point Pos="0,0,0"/><Point Pos="10,0,0"/>'
            '<Point Pos="10,10,0"/><Point Pos="0,10,0"/></Points></Area></Entity>')

    def test_spatial_selection_uses_height_and_includes_polygon_boundary(self):
        area=source_home_geometry(self.source(10,'anywhere'))
        for pos in [(15,25,35),(10,20,30),(20,30,38)]:self.assertTrue(contains(area,pos))
        for pos in [(15,25,40),(9,25,35),(15,31,35)]:self.assertFalse(contains(area,pos))

    def test_native_labels_graph_and_geometry_agree_and_merge_is_idempotent(self):
        root=self.source(10,'root');district=self.source(11,'district')
        E.SubElement(E.SubElement(district,'EntityLinks'),'Link',Name='inside',TargetId='12')
        anchor=E.Element('Entity',EntityId='12',EntityGuid='C',EntityClass='TagPoint',Name='origin',Pos='15,25,30')
        files={'objects_mission0.xml':b'<Objects/>','triggerareas.fubar':write_areas([],123),
               'waitinglinks.xml':b'<StaticLinksInfo version="1"><WaitingLinks/></StaticLinksInfo>'}
        native=E.Element('SmartEntityTemplate',Name='sa_crime_district',BrainId='brain',DatabaseId='type')
        result,report=convert(files,[root,district,anchor],root,[district],native)
        second,_=convert(result,[root,district,anchor],root,[district],native)
        self.assertEqual(result,second)
        self.assertEqual(read_areas(result['triggerareas.fubar'])['export_version'],123)
        self.assertEqual({a.guid for a in read_areas(result['triggerareas.fubar'])['areas']},{10,11})
        mission=E.fromstring(result['objects_mission0.xml'])
        self.assertEqual(mission.find("Entity[@Name='root']/Properties").get('Label'),'crimeDistrict_main')
        self.assertEqual(mission.find("Entity[@Name='district']/Properties").get('guidSmartAreaTemplate'),'type')
        links=E.fromstring(result['waitinglinks.xml'])
        self.assertEqual({x.text for x in links.iter('LinkDefinition')},{'crime_district','crime_districtOrigin'})
        self.assertEqual(report['districts'][0]['origin'],native_guid(12))
        self.assertEqual(files['objects_mission0.xml'],b'<Objects/>')

    def test_missing_origin_does_not_emit_partially_wired_district(self):
        root=self.source(10,'root');district=self.source(11,'district')
        files={'objects_mission0.xml':b'<Objects/>','triggerareas.fubar':write_areas([],123),'waitinglinks.xml':b''}
        with self.assertRaisesRegex(ValueError,'authored origin'):
            convert(files,[root,district],root,[district],E.Element('SmartEntityTemplate',Name='sa_crime_district',BrainId='b',DatabaseId='t'))
        self.assertEqual(files['objects_mission0.xml'],b'<Objects/>')

if __name__=='__main__':unittest.main()
