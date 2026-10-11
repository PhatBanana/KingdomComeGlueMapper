"""Regression boundaries for the optional cache quest and its world registration."""
import sys
import tempfile
from pathlib import Path
import unittest
import xml.etree.ElementTree as ET
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'tools'))
from debug_supply_quest import attach, ENTRY, PATH
from build_debug_supplies import CHEST_XY, SEARCH_XY, SEARCH_RADIUS, world
from campaign_trigger_areas import write_areas, read_areas
from campaign_entity_links import guid_value


class DebugSuppliesTests(unittest.TestCase):
    def setUp(self):
        temporary=tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        stream=Path(temporary.name)/'scripts.pak'
        with zipfile.ZipFile(stream,'w') as z:
            for name in ('HasItems_Stash','hasitems'):
                z.writestr('Quests/Final/Barbora/utils/item/'+name+'.xml',
                           '<Database><Skald><Module Name="'+name+'"/></Skald></Database>')
        resources={ENTRY:b'<Database><Skald><Level Name="kcd1_travel"><Nodes/></Level></Skald></Database>',
            'Quests/GlueTravel/visit_rattay_journal.xml':b'<Database><Skald><Quest Name="old"/></Skald></Database>',
            'Quests/Final/native.xml':b'<Database><Skald><Quest Name="native" Type="Main"/></Skald></Database>'}
        with zipfile.ZipFile(stream) as z:
            self.result,_=attach(resources,[{'Id':str(i)} for i in range(5)],z)
        self.quest=ET.fromstring(self.result[PATH]).find('Skald/Quest')

    def test_search_marker_hides_exact_chest_and_contains_it(self):
        log=self.quest.find("Objectives/Objective/Logs/EnumLog[@Name='Active']")
        self.assertEqual(log.get('Marker'),'debug_supply_search')
        distance=sum((a-b)**2 for a,b in zip(CHEST_XY,SEARCH_XY))**.5
        self.assertGreater(distance,5)
        self.assertLess(distance,SEARCH_RADIUS)

    def test_opening_or_taking_only_money_cannot_complete(self):
        nodes=self.quest.find('Nodes')
        finish=nodes.find("If[@Name='finish_after_looting']")
        self.assertEqual(finish.find("Edge[@To='Exec']").get('From'),'chest_events.OnClosed')
        self.assertEqual(len(nodes.findall('HasItems_Stash')),5)
        self.assertEqual(len([n for n in nodes.findall('Function') if n.get('MethodName')=='math::boolean::Or']),4)
        done=nodes.find("State[@Name='progress']/Edge[@To='SetDone']")
        self.assertEqual(done.get('From'),'seller_introduction.True')
        self.assertEqual(nodes.find("StashTrigger/Edge[@To='IsActive']").get('From'),'objective.Active')
        self.assertEqual(nodes.find("State[@Name='visit_seller']/Edge[@To='SetActive']").get('From'),'finish_after_looting.True')

    def test_seller_step_is_gated_and_completed_saves_upgrade_once(self):
        nodes=self.quest.find('Nodes')
        self.assertEqual(nodes.find("If[@Name='seller_introduction']/Edge[@To='Condition']").get('From'),'visit_seller.Active')
        self.assertEqual(nodes.find("If[@Name='upgrade_only_once']/Edge[@To='Condition']").get('From'),'visit_seller.None')
        self.assertEqual(nodes.find("State[@Name='objective']/Edge[@To='SetActive']").get('From'),'start_once.True')
        marker=self.quest.find("Objectives/Objective[@Name='meet_zora']/Logs/EnumLog[@Name='Active']")
        self.assertEqual(marker.get('Marker'),'horse_seller')

    def test_existing_native_quests_are_untouched(self):
        self.assertEqual(self.quest.get('Type'),'Side')
        custom=ET.fromstring(self.result['Quests/GlueTravel/visit_rattay_journal.xml'])
        native=ET.fromstring(self.result['Quests/Final/native.xml'])
        self.assertEqual(custom.find('Skald/Quest').get('Type'),'Side')
        self.assertEqual(native.find('Skald/Quest').get('Type'),'Main')

    def test_world_binds_project_level_and_compiled_search_area(self):
        files={'objects_mission0.xml': b'<Objects><Entity Name="kcd1_travel" EntityClass="LevelHolder" EntityId="1" EntityGuid="00000001-0000-0000" Pos="3800,1800,130"/></Objects>',
               'waitinglinks.xml': b'<StaticLinksInfo version="1"><WaitingLinks/></StaticLinksInfo>',
               'triggerareas.fubar':write_areas([],123)}
        result,_=world(files,lambda x,y:130.)
        mission=ET.fromstring(result['objects_mission0.xml'])
        project=mission.find("Entity[@Name='GlueTravel_kcd1']")
        self.assertEqual(project.get('EntityClass'),'SmartObjectHolder')
        self.assertEqual(project.find("EntityLinks/Link[@Name='module']").get('TargetId'),'1')
        area=mission.find("Entity[@Name='gm_debug_supply_search']")
        self.assertEqual(read_areas(result['triggerareas.fubar'])['areas'][0].guid,guid_value(area.get('EntityGuid')))
        links=ET.fromstring(result['waitinglinks.xml'])
        self.assertTrue(any(e.text=='module' for e in links.iter('LinkDefinition')))


if __name__=='__main__':unittest.main()
