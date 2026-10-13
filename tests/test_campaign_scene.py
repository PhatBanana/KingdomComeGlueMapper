import sys
from pathlib import Path
import unittest
import xml.etree.ElementTree as ET

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from campaign_scene import stat_effects, bind_stat_effects, bind_scene_cameras, bind_scene_positions


class SceneTests(unittest.TestCase):
    def test_scene_entry_places_both_souls_without_moving_camera(self):
        project=b'<Database><Skald><Project Name="scene"><Nodes><opening Name="opening"/></Nodes><Assets><SoulAsset Name="player"/><SoulAsset Name="mother"/></Assets></Project></Skald></Database>'
        mission=b'<Objects><Entity Name="scene" EntityClass="SmartObjectHolder" EntityId="1" EntityGuid="00000001-0000-0000"/><Entity Name="camera" EntityClass="CameraSource" EntityId="2" EntityGuid="00000002-0000-0000" Pos="5,6,10"/></Objects>'
        poses={'player':dict(Name='source1',Pos='5,6,8',Rotate='1,0,0,0'),
               'mother':dict(Name='source2',Pos='6,6,8',Rotate='0,0,0,1')}
        p,m,w,report=bind_scene_positions(project,mission,None,'opening',poses)
        entities=ET.fromstring(m);root=ET.fromstring(p)
        self.assertEqual(entities.find("Entity[@Name='camera']").get('Pos'),'5,6,10')
        points=entities.findall("Entity[@EntityClass='TagPoint']")
        self.assertEqual([e.get('Pos') for e in points],['5,6,8','6,6,8'])
        self.assertEqual([e.get('Rotate') for e in points],['1,0,0,0','0,0,0,1'])
        for point,soul in zip(points,poses):
            link=point.find('EntityLinks/Link')
            self.assertEqual(link.get('Name'),"useAsset['"+soul+"']")
            self.assertEqual(link.get('TargetGuid'),point.get('EntityGuid'))
        self.assertEqual(len(entities.findall("Entity[@EntityClass='DialogueHolder']/EntityLinks/Link[@Name='teleportBefore']")),2)
        self.assertEqual(len(list(ET.fromstring(w).iter('LinkDefinition'))),5)
        self.assertIsNotNone(root.find('.//opening/Asset[@Name="DialogueHolder"]'))
        with self.assertRaisesRegex(ValueError,'already registered'):
            bind_scene_positions(p,m,w,'opening',poses)
        with self.assertRaisesRegex(ValueError,'Missing scene participant'):
            bind_scene_positions(project,mission,None,'opening',{'absent':poses['player']})
        with self.assertRaisesRegex(ValueError,'Parented'):
            bind_scene_positions(project,mission,None,'opening',{'player':dict(poses['player'],ParentId='42')})

    def test_custom_camera_has_asset_and_both_world_link_registrations(self):
        project=b'<Database><Skald><Project Name="scene"><Assets><SoulAsset Name="player"/></Assets></Project></Skald></Database>'
        mission=b'<Objects><Entity Name="scene" EntityClass="SmartObjectHolder" EntityId="1" EntityGuid="00000001-0000-0000"/><Entity Name="original_cam" EntityClass="CameraSource" EntityId="2" EntityGuid="00000002-0000-0000" Pos="1,2,3" Rotate="1,0,0,0"/></Objects>'
        dialogue=b'<Dialogue><CameraCommand CustomCamera="original_cam"/></Dialogue>'
        p,m,w,r=bind_scene_cameras(project,mission,None,dialogue)
        self.assertEqual(ET.fromstring(p).find('.//CameraAsset').get('Name'),'original_cam')
        self.assertEqual(ET.fromstring(m).find('.//Link').get('TargetGuid'),'00000002-0000-0000')
        self.assertEqual(ET.fromstring(w).findtext('.//LinkDefinition'),"asset['original_cam']")
        self.assertEqual(r[0]['position'],'1,2,3')
        self.assertIsNotNone(ET.fromstring(p).find('.//SoulAsset'))
        with self.assertRaisesRegex(ValueError,'Missing or ambiguous'):
            bind_scene_cameras(project,mission,None,b'<Dialogue><CameraCommand CustomCamera="absent"/></Dialogue>')

    def source(self, condition=None, script=None):
        root=ET.Element('Root')
        gate=ET.SubElement(root,'IfCondition',condition=condition or
            "($questObjectiveUpdate.State == $enum:ObjectiveState.Completed) & ($questObjectiveUpdate.ObjectiveName == 'first' | $questObjectiveUpdate.ObjectiveName == 'second')")
        ET.SubElement(gate,'ExecuteLua',code=script or
            "local val = player.soul:GetStatLevel('agi'); player.soul:AdvanceToStatLevel('agi',val+1)")
        return ET.tostring(root)

    def test_source_names_and_reward_are_preserved(self):
        effects=stat_effects(self.source(),[dict(objective_name='first',objective_id='41'),dict(objective_name='second',objective_id='42')])
        self.assertEqual(set(effects),{'first','second'})
        self.assertEqual(effects['first']['stat'],'agility')
        self.assertEqual(effects['second']['amount'],1)
        graph=b'<Database><Skald><Quest><Nodes><State Name="objective_41"/><State Name="objective_42"/></Nodes></Quest></Skald></Database>'
        root=ET.fromstring(bind_stat_effects(graph,effects,'my_player'))
        self.assertEqual(len(root.findall('.//MemberFunction[@MethodName="AdvanceToStatLevel"]')),2)
        self.assertEqual(len(root.findall('.//State[@TypeT="bool"]')),2)
        self.assertEqual(root.find('.//MemberFunction[@Name="reward_first_advance"]/Edge[@To="Exec"]').get('From'),'reward_first_gate.True')
        self.assertEqual(root.find('.//State[@Name="reward_first_paid"]/Edge').get('From'),'reward_first_advance.OnExec')

    def test_unknown_condition_fails(self):
        with self.assertRaisesRegex(ValueError,'condition'):
            stat_effects(self.source(condition='true'),[])

    def test_unknown_script_fails(self):
        with self.assertRaisesRegex(ValueError,'source stat reward'):
            stat_effects(self.source(script="player.soul:AdvanceToStatLevel('agi',99)"),
                [dict(objective_name='first'),dict(objective_name='second')])


if __name__=='__main__':unittest.main()
