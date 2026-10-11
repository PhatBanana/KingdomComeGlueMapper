from pathlib import Path
import posixpath
import sys
import unittest
import xml.etree.ElementTree as ET
import zipfile

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from room_rental import source_room
from room_rental_dialogue import attach, PROJECT, DIALOG_PATH, MODULE, DIRECTORY
from region_travel_merchant import ROLE


class RoomResolutionTests(unittest.TestCase):
    def test_authored_home_links_choose_room_not_distance(self):
        root=ET.fromstring('''<Objects>
          <Entity EntityId="1" Name="keeper"><EntityLinks><Link Name="Home,owner" TargetId="10"/></EntityLinks></Entity>
          <Entity EntityId="2" Name="guest"><EntityLinks><Link Name="sleepoverParentHome" TargetId="10"/>
          <Link Name="sleepoverBed" TargetId="3"/><Link Name="sleepoverStash" TargetId="4"/>
          <Link Name="sleepoverDoor" TargetId="5"/></EntityLinks></Entity>
          <Entity EntityId="3"/><Entity EntityId="4"/><Entity EntityId="5"/>
          <Entity EntityId="6"><EntityLinks><Link Name="sleepoverParentHome" TargetId="99"/></EntityLinks></Entity>
        </Objects>''')
        entities={e.get('EntityId'):e for e in root}
        room,parts=source_room(entities,'keeper')
        self.assertEqual(room.get('Name'),'guest')
        self.assertEqual({k:v.get('EntityId') for k,v in parts.items()},dict(bed='3',chest='4',door='5'))
        root[-1].find('EntityLinks/Link').set('TargetId','10')
        with self.assertRaises(ValueError): source_room(entities,'keeper')


# Run against the shipped contract when the user's game assets are available.
SCRIPTS=Path('D:/SteamLibrary/steamapps/common/KCD2Mod/Data/Scripts.pak')
@unittest.skipUnless(SCRIPTS.exists(),'Native game assets are not installed')
class NativeRentalTests(unittest.TestCase):
    def setUp(self):
        resources={PROJECT:b'''<Database><Skald><Project><Definitions><Definition File="rattay_innkeeper.xml"/></Definitions>
            <Nodes><rattay_innkeeper Name="rattay_innkeeper"/><quest><Edge From="rattay_innkeeper.dialog_started" To="talked"/></quest></Nodes>
            <Assets><SoulAsset Name="rattay_innkeeper" SharedSoulGuids="test"/></Assets></Project></Skald></Database>''',
            DIALOG_PATH:b'''<Database><Skald><FaderDialog Name="rattay_innkeeper"><Ports><Port Name="dialog_started" Direction="Out" Type="trigger"/></Ports>
            <Dialogue><Decision Name="services"><Sequences><Sequence Name="trade"/><Sequence Name="end"/></Sequences></Decision></Dialogue>
            </FaderDialog></Skald></Database>'''}
        with zipfile.ZipFile(SCRIPTS) as scripts: self.files,self.report=attach(resources,scripts,'test')
        self.module=ET.fromstring(self.files[DIRECTORY+'/'+MODULE+'.xml']).find('Skald/Module')

    def test_dependencies_are_closed_and_dialogue_retains_services(self):
        for path,blob in self.files.items():
            root=ET.fromstring(blob)
            for definition in root.findall('.//Definition'):
                self.assertIn(posixpath.normpath(posixpath.join(posixpath.dirname(path),definition.get('File'))),self.files)
        dialog=ET.fromstring(self.files[DIALOG_PATH])
        decisions={e.get('Name') for e in dialog.iter('Decision')}
        for node in dialog.iter():
            if node.get('GoToDecision'):self.assertIn(node.get('GoToDecision'),decisions)
        self.assertIsNotNone(dialog.find(".//Sequence[@Name='trade']"))
        self.assertIsNotNone(dialog.find(".//Sequence[@Name='end']"))
        self.assertNotIn(b'HOSPODSKY_PRONAJEM',self.files[DIALOG_PATH])
        self.assertIn(ROLE.encode(),self.files[DIALOG_PATH])

    def test_rental_state_controls_chest_and_quest_completion_survives(self):
        owner=self.module.find("Nodes/SetOwner[@Name='rental_chest_owner']")
        self.assertIsNotNone(owner.find("Edge[@From='or32.bool'][@To='IsActive']"))
        lock=self.module.find("Nodes/Function[@Name='chest_lock']")
        self.assertIsNotNone(lock.find("Edge[@From='state24.Onnone'][@To='Exec']"))
        unlock=self.module.find("Nodes/Function[@Name='chest_unlock']")
        self.assertIsNotNone(unlock.find("Edge[@From='state24.OnoneNight']"))
        self.assertIsNotNone(unlock.find("Edge[@From='state24.Oninfinite']"))
        project=ET.fromstring(self.files[PROJECT])
        self.assertIsNotNone(project.find(".//Edge[@From='gm_room_rental.dialog_started'][@To='talked']"))
        self.assertIsNone(self.module.find("Ports/Port[@Name='kotlik']"))

    def test_shared_utilities_have_common_scope_and_required_enum(self):
        definitions=self.module.findall('Definitions/Definition')
        names={Path(e.get('File')).stem for e in definitions}
        for path,blob in self.files.items():
            if path.startswith(DIRECTORY+'/') and not path.endswith('/'+MODULE+'.xml'):
                root=ET.fromstring(blob)
                self.assertEqual(root.findall('.//Definitions/Definition'),[])
                for node in root.findall('.//Nodes/*'):
                    if node.tag.startswith('gm_rent_'):self.assertIn(node.tag,names)
                    self.assertNotEqual(node.tag,'converttogroshen')
        self.assertIsNotNone(self.module.find("Types/Type[@TypeName='RPGStatInterval']"))

    def test_rental_choices_do_not_wait_for_unresolved_recordings(self):
        dialog=ET.fromstring(self.files[DIALOG_PATH])
        topic=dialog.find(".//Sequence[@Name='koupit_pokoj_a_stravu']")
        self.assertIsNotNone(topic)
        self.assertTrue(list(topic.iter('UiPrompt')))
        for response in topic.iter('Response'):
            self.assertEqual(response.attrib,{'Role':'HENRY'})
            self.assertEqual(len(response),0)
        self.assertIsNotNone(topic.find(".//Sequence[@Name='jedna_noc'][@Type='Payment']"))
        self.assertIsNotNone(topic.find(".//Sequence[@Name='na_stalo'][@Type='Payment']"))
        self.assertIsNotNone(topic.find(".//Triggers/Port[@Name='pronajem_na_jednu_noc']"))
        self.assertIsNotNone(topic.find(".//Triggers/Port[@Name='pronajem_do_konce_hry']"))
        for sequence in topic.iter('Sequence'):
            self.assertFalse(sequence.get('ExitScript','').lstrip().startswith(';'))


if __name__=='__main__':unittest.main()
