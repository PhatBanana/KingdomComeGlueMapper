import copy
from pathlib import Path
import tempfile
import unittest
import xml.etree.ElementTree as E
import zipfile

from gambler_dialogue_registration import HOST, MINIH, ROOT, NATIVE, ALIAS, adapted_root, prepare
from upgrade_map import read, xml

GAME=Path('D:/SteamLibrary/steamapps/common/KingdomComeDeliverance2')


@unittest.skipUnless((GAME/'Data/Scripts.pak').exists(), 'requires installed native dice contract')
class NativeDiceRegistrationTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.package=Path(self.temp.name)
        (self.package/'Data').mkdir()
        self.host=b'<Database><Skald><Project Name="test"><Assets/><Nodes><open_world Name="open_world"/></Nodes><Definitions><Definition File="smithing_voice/open_world.xml"/></Definitions></Project></Skald></Database>'
        self.minih=b'<Database><Skald><Gameplay Name="minihry" VoiceNamespace="true"><Definitions><Definition File="kovareni.xml"/></Definitions><Nodes><kovareni Name="kovareni"/></Nodes></Gameplay></Skald></Database>'
        self.write({HOST:self.host,MINIH:self.minih})
        self.files={'objects_mission0.xml':b'<Objects><Entity Name="test" EntityClass="SmartObjectHolder" EntityId="1" EntityGuid="00000000-0000-0001" Pos="0,0,0"/></Objects>',
                    'waitinglinks.xml':b'<StaticLinksInfo version="1"><WaitingLinks/></StaticLinksInfo>'}

    def write(self, definitions):
        with zipfile.ZipFile(self.package/'Data/gluemappertravel.pak','w') as z:
            for n,b in definitions.items():z.writestr(n,b)
            z.writestr('Quests/GlueTravel/smithing_voice/open_world.xml',b'<Database><Skald><Gameplay Name="open_world" VoiceNamespace="true"><Definitions><Definition File="minihry.xml"/></Definitions><Nodes><minihry Name="minihry"/></Nodes></Gameplay></Skald></Database>')

    def test_native_lifecycle_dependencies_and_nonmutation(self):
        archive=self.package/'Data/gluemappertravel.pak'
        before=archive.read_bytes();original=copy.deepcopy(self.files)
        files,defs,report=prepare(self.package,GAME,self.files)
        self.assertEqual(archive.read_bytes(),before);self.assertEqual(self.files,original)
        self.assertGreater(report['validated_graphs'],50)
        root=E.fromstring(defs[ROOT]);self.assertIsNone(root.find(".//Port[@Name='m03']"))
        self.assertIsNone(root.find(".//debug"))
        self.assertIsNotNone(root.find(".//diceowlogic"))
        payload=b'\n'.join(defs.values())
        self.assertTrue(b'MessageType="dice:initDialogResult"' in payload)
        self.assertTrue(b'dice_readyToPlayMinigame' in payload)
        self.assertFalse(b'Alias="test_QSO"' in payload)
        self.assertIn(b'esCutsceneName="dice_preMinigameFader"',files['objects_mission0.xml'])
        for path,blob in defs.items():
            for d in E.fromstring(blob).findall('.//Definitions/Definition'):
                self.assertNotIn('..',d.get('File'))
        self.assertIsNotNone(E.fromstring(defs[MINIH]).find('.//kovareni'))
        self.assertFalse(report['runtime_verified'])

    def test_repeat_has_no_duplicate_entities_or_registrations(self):
        files,defs,_=prepare(self.package,GAME,self.files)
        self.write(defs)
        again,other,_=prepare(self.package,GAME,files)
        self.assertEqual(again,files);self.assertEqual(other,defs)

    def test_repeat_after_speech_serializer_preserves_existing_type_bytes(self):
        # Work speech uses campaign_quest_graph.xml, which reindents the whole
        # project, including existing native types copied by this stage.
        from campaign_quest_graph import xml as speech_xml
        files,defs,_=prepare(self.package,GAME,self.files)
        project=E.fromstring(defs[HOST])
        E.SubElement(project.find('.//Assets'),'SoulAsset',Name='speech_actor',SharedSoulGuids='00000000-0000-0002')
        defs[HOST]=speech_xml(project)
        self.write(defs)
        again,other,_=prepare(self.package,GAME,files)
        self.assertEqual(again,files)
        self.assertEqual(other[HOST],defs[HOST])

    def test_reformatted_changed_enum_is_still_rejected(self):
        from campaign_quest_graph import xml as speech_xml
        files,defs,_=prepare(self.package,GAME,self.files)
        project=E.fromstring(defs[HOST])
        enum=project.find(".//Type[@TypeName='DiceGameState']/StateTypeEnumeration")
        self.assertIsNotNone(enum)
        enum.set('ObjectiveValueType','Started')
        defs[HOST]=speech_xml(project);self.write(defs)
        with self.assertRaisesRegex(ValueError,'Conflicting inherited native dice type: DiceGameState'):
            prepare(self.package,GAME,files)

    def test_foreign_holder_alias_fails_before_mutation(self):
        root=E.fromstring(self.host)
        E.SubElement(root.find('.//Assets'),'SoulAsset',Name=ALIAS)
        self.write({HOST:xml(root),MINIH:self.minih})
        before=(self.package/'Data/gluemappertravel.pak').read_bytes()
        with self.assertRaisesRegex(ValueError,'Dice asset type conflict'):
            prepare(self.package,GAME,self.files)
        self.assertEqual((self.package/'Data/gluemappertravel.pak').read_bytes(),before)

    def test_new_dependency_on_excluded_campaign_branch_rejected(self):
        with zipfile.ZipFile(GAME/'Data/Scripts.pak') as z:root=E.fromstring(read(z,NATIVE))
        n=E.SubElement(root.find('.//Gameplay/Nodes'),'If',Name='new_gate')
        E.SubElement(n,'Edge',From='SockyDone.True',To='Exec')
        with self.assertRaisesRegex(ValueError,'excluded campaign/debug'):
            adapted_root(xml(root))

    def test_unrelated_native_logic_is_preserved(self):
        with zipfile.ZipFile(GAME/'Data/Scripts.pak') as z:payload=read(z,NATIVE)
        original=E.fromstring(payload).find('Skald/Gameplay')
        adapted=E.fromstring(adapted_root(payload)).find('Skald/Gameplay')
        expected=[xml(n) for n in original.find('Nodes') if n.get('Name') not in {'debug','SockyDone','codexHry'}]
        self.assertEqual([xml(n) for n in adapted.find('Nodes')],expected)


if __name__=='__main__':unittest.main()
