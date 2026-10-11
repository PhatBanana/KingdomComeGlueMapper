from pathlib import Path
import sys
import unittest
import xml.etree.ElementTree as ET
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from room_rental import register_bed_scheduler
from campaign_entity_links import guid_value

DONOR='8b84586f-f515-085a'
BED='8a76a45a-78af-8352'
BASE=b'<database><Schedulers><C_SmartHub EntityGuid="42"/></Schedulers></database>'

def native(extra=''):
    return f'''<database><Schedulers><C_SmartHub EntityGuid="{guid_value(DONOR)}" IgnoreDeadEnds="false" StupidHub="false">
    <PostSearchData><SmartHubPostSearchData><SchedulerEffect>
    <EffectHeal HealRate="25.000000" Role="sleeper"/>
    </SchedulerEffect></SmartHubPostSearchData></PostSearchData>{extra}</C_SmartHub></Schedulers></database>'''.encode()

class BedSchedulerTests(unittest.TestCase):
    def test_registers_hub_and_preserves_healing_and_other_records(self):
        result=register_bed_scheduler(BASE,native(),DONOR,BED)
        rows=ET.fromstring(result).find('Schedulers')
        self.assertEqual(len(rows),2)
        self.assertEqual(rows[0].get('EntityGuid'),'42')
        self.assertEqual(rows[1].get('EntityGuid'),str(guid_value(BED)))
        self.assertEqual(rows[1].find('.//EffectHeal').attrib,{'HealRate':'25.000000','Role':'sleeper'})
        with self.assertRaises(ValueError):register_bed_scheduler(result,native(),DONOR,BED)
    def test_rejects_unconverted_external_activity(self):
        with self.assertRaises(ValueError):
            register_bed_scheduler(BASE,native('<Links><S_ActivityLink TargetGuid="999"/></Links>'),DONOR,BED)
    def test_missing_donor_fails(self):
        with self.assertRaises(ValueError):register_bed_scheduler(BASE,BASE,DONOR,BED)

if __name__=='__main__':unittest.main()
