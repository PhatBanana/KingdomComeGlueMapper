from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
import xml.etree.ElementTree as ET
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'tools'))
from miller import schedule_windows
from character_person_world import register_person_world, source_home_geometry
from campaign_trigger_areas import write_areas, read_areas
from campaign_entity_links import native_guid


class MillerScheduleTests(unittest.TestCase):
    def test_source_midnight_sleep_has_complete_nonoverlapping_day(self):
        windows=schedule_windows([dict(activity='work',start_minute=399),dict(activity='sleep',start_minute=1369)])
        for minute in range(1440):
            active=[w for w in windows if w['start']<=minute<w['end']]
            self.assertEqual(len(active),1)
            self.assertEqual(active[0]['activity'],'work' if 399<=minute<1369 else 'sleep')

    def test_new_source_activity_and_duplicate_boundary_fail_explicitly(self):
        for data in ([dict(activity='work',start_minute=0),dict(activity='sleep',start_minute=0)],
                     [dict(activity='work',start_minute=60),dict(activity='eat',start_minute=300)]):
            with self.assertRaises(ValueError):schedule_windows(data)

    def test_second_resident_reuses_float32_shared_home(self):
        # Regression: an XML home's doubles differ from the same installed
        # FUBAR polygon by 0.00003 m and must not block the second resident.
        home=ET.fromstring('''<Entity Name="shared_home" EntityGuid="408632C8F1081C57" Pos="2457.8511,711.57263,24.599272"><Area Height="20"><Points><Point Pos="0,0,0"/><Point Pos="7.0915527,-3.4624023,0.1"/><Point Pos="9.2229004,1.4005737,0.1"/></Points></Area></Entity>''')
        geo=source_home_geometry(home)
        mission=f'''<Objects><Entity Name="sa_land" EntityId="1" EntityGuid="{native_guid(1)}" Pos="0,0,0"/><Entity Name="miller" EntityId="2" EntityGuid="{native_guid(2)}" Pos="2457,706,28"/><Entity Name="shared_home" EntityClass="TriggerArea" EntityId="3" EntityGuid="{native_guid(geo.guid)}" Pos="2457,711,24"/></Objects>'''.encode()
        files={'objects_mission0.xml':mission,'tables/ai/scheduler.xml':b'<database><Schedulers><C_SmartHub EntityGuid="1"/><C_SmartHub EntityGuid="2"><Links><S_ActivityLink TargetGuid="1"/></Links></C_SmartHub></Schedulers></database>',
               'triggerareas.fubar':write_areas([geo],1)}
        person=dict(name='miller',source_level='rataje',ai=dict(schedule=[],links=[dict(label='Home,owner',source_xml=ET.tostring(home,encoding='unicode'))]))
        with tempfile.TemporaryDirectory() as directory:
            pak=Path(directory)/'Data/Levels/rataje/level.pak';pak.parent.mkdir(parents=True)
            with zipfile.ZipFile(pak,'w') as z:z.writestr('triggerareas.fubar',write_areas([],1))
            with patch('character_person_world.native_wait_activity',return_value=(ET.Element('S_ActivityLink'),ET.Element('C_SmartHub'))):
                updated,_=register_person_world(files,[person],directory,directory)
        self.assertEqual(updated['triggerareas.fubar'],files['triggerareas.fubar'])
        self.assertEqual(len(read_areas(updated['triggerareas.fubar'])['areas']),1)


if __name__=='__main__':unittest.main()
