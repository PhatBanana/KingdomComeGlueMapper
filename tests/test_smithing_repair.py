import sys
from pathlib import Path
import unittest
import xml.etree.ElementTree as ET
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from build_smithing_repair import repair_coal, COAL_ID


class CoalRepairTests(unittest.TestCase):
    def fixture(self):
        root=ET.Element('Objects')
        ET.SubElement(root,'Entity',Name='unrelated',EntityId='1')
        for i,station in enumerate(('62317','62236')):
            prefix=f'gm_rattay_smith_{station}_'
            smith=ET.SubElement(root,'Entity',Name=prefix+'46192',EntityId=str(2+i*2))
            links=ET.SubElement(smith,'EntityLinks')
            ET.SubElement(links,'Link',Name='hammer',TargetId='123',TargetGuid='abc')
            ET.SubElement(root,'Entity',Name=prefix+'prop_'+COAL_ID,EntityId=str(3+i*2),EntityGuid='coal-'+station,Geometry='Objects/manmade/structures/industrial/smitheries/coal_forge_small_a.cgf')
        return root

    def test_connects_each_station_to_its_own_coal_and_preserves_other_links(self):
        original=self.fixture();root=ET.fromstring(repair_coal(ET.tostring(original)))
        self.assertEqual(len(root),len(original))
        for old,new in zip(original,root):
            self.assertEqual(old.attrib,new.attrib)
            if old.find('EntityLinks') is None:continue
            self.assertEqual(old.find('EntityLinks/Link').attrib,new.find('EntityLinks/Link').attrib)
            link=new.find("EntityLinks/Link[@Name='forgeCoal']")
            coal=next(e for e in root if e.get('EntityId')==link.get('TargetId'))
            self.assertEqual(coal.get('EntityGuid'),link.get('TargetGuid'))
            self.assertEqual(coal.get('Name').split('_prop_')[0],new.get('Name').removesuffix('_46192'))
        once=repair_coal(ET.tostring(original))
        self.assertEqual(once,repair_coal(once))

    def test_rejects_wrong_coal_geometry(self):
        root=self.fixture();next(e for e in root if e.get('Geometry')).set('Geometry','wrong.cgf')
        with self.assertRaisesRegex(ValueError,'Unexpected'):repair_coal(ET.tostring(root))

if __name__=='__main__':unittest.main()
