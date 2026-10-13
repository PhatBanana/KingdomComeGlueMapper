from pathlib import Path
import sys
import tempfile
import unittest
import zipfile
import xml.etree.ElementTree as ET

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from campaign_dialogue import camera_assets, emit, presentation_command


def model():
    command = dict(who='456', target='0', delay='2.571127', dialogue_command_type='3',
                   char_param='ADLG_Frustration', int_param='1', sequence_line_id='20')
    return dict(alias='opening', start_topic='1', roles={'456': {'role_name': 'MOTHER'}},
                moods=[dict(dialogue_mood_id='39', dialogue_mood_name='thinking1')],
                strings={'speech': 'Original line'}, topics={'1': dict(source={'label': 'opening'}, sequences=[dict(
                    source=dict(sequence_id='10', type='0', group='0', skill_check_difficulty_id='',
                                reputation='0', script='', flags='0', ui_prompt='', next='0'),
                    entry=dict(entry_condition='1', npc_entry_condition=''), effects=[], lines=[
                        dict(source=dict(sequence_line_type='5', sequence_line_id='20'), commands=[command]),
                        dict(source=dict(sequence_line_type='1', sequence_line_id='21'),
                             response=dict(role_id='456', string_name='speech'), commands=[])])])})


class DialoguePresentationTests(unittest.TestCase):
    def test_in_world_monologue_retains_alias_without_becoming_a_fader(self):
        source = model()
        source['branch'] = [dict(start_topic='1', priority='0', allow_greeting='True',
                                 branch_type_id='6', reputation_condition_id='')]
        blob, report = emit(source, 'world_speech', [], kind='Dialog')
        host = ET.fromstring(blob).find('./Skald/Dialog')
        self.assertEqual(host.find('Dialogue').get('Type'), 'ingame monolog')
        self.assertEqual(host.find('.//Decision').get('Alias'), 'opening')
        self.assertEqual(report['kind'], 'Dialog')
        with self.assertRaisesRegex(ValueError, 'branch type'):
            emit(source, 'wrong_mode', [])
        source['branch'][0]['branch_type_id'] = '0'
        with self.assertRaisesRegex(ValueError, 'branch type'):
            emit(source, 'wrong_mode', [], kind='Dialog')

    def test_source_branch_priority_and_greeting_are_not_reset_to_defaults(self):
        source = model()
        source['branch'] = [dict(start_topic='1', priority='2', allow_greeting='True',
                                 branch_type_id='0', reputation_condition_id='')]
        blob, _ = emit(source, 'ordinary', [])
        body = ET.fromstring(blob).find('.//Dialogue')
        self.assertEqual(body.get('Priority'), '2')
        self.assertEqual(body.get('AllowGreeting'), 'true')
        source['branch'][0]['reputation_condition_id'] = '7'
        with self.assertRaisesRegex(ValueError, 'reputation policy'):
            emit(source, 'ordinary', [])

    def test_ordinary_branch_end_does_not_close_entire_conversation(self):
        source = model()
        blob, report = emit(source, 'ordinary', [])
        self.assertNotIn('EndType', ET.fromstring(blob).find('.//Sequence').attrib)
        self.assertEqual(report['branch_endings'][0]['native_end'], 'EndTopic')
        # Entry mode must not invent a session exit absent from the source.
        forced, report = emit(source, 'forced', [], kind='ForcedDialog')
        self.assertNotIn('EndType', ET.fromstring(forced).find('.//Sequence').attrib)
        self.assertEqual(report['branch_endings'][0]['native_end'], 'EndTopic')
        source['topics']['1']['sequences'][0]['source']['flags'] = '1'
        flagged, report = emit(source, 'flagged', [])
        self.assertEqual(ET.fromstring(flagged).find('.//Sequence').get('EndType'), 'EndDialogue')
        self.assertTrue(any(p['kind'] == 'sequence_flags' for p in report['presentation_pending']))

    def test_commands_before_response_attach_to_following_response(self):
        data, report = emit(model(), 'opening', [], convert_presentation=True)
        command = ET.fromstring(data).find('.//Response/Commands/AnimationCommand')
        self.assertEqual(command.get('FragmentId'), 'ADLG_Frustration')
        self.assertEqual(command.get('Variant'), '1')
        self.assertEqual(command.get('Delay'), '2.571127')
        self.assertEqual(report['converted_commands'][0]['response'], '21')

    def test_custom_camera_and_facial_mood_preserve_source_identity(self):
        base = dict(who='456', target='0', delay='', int_param='5', char_param='cam_original', dialogue_command_type='2')
        self.assertEqual(presentation_command(base, model()).get('CustomCamera'), 'cam_original')
        base.update(dialogue_command_type='1', int_param='39')
        self.assertEqual(presentation_command(base, model()).get('FacialMood'), 'thinking1')

    def test_orphaned_or_unknown_commands_fail_instead_of_disappearing(self):
        data = model()
        data['topics']['1']['sequences'][0]['lines'].pop()
        with self.assertRaisesRegex(ValueError, 'no following response'):
            emit(data, 'opening', [], convert_presentation=True)
        command = model()['topics']['1']['sequences'][0]['lines'][0]['commands'][0]
        command['dialogue_command_type'] = '999'
        with self.assertRaisesRegex(ValueError, 'command type'):
            presentation_command(command, model())

    def test_camera_resolution_is_name_driven_and_preserves_optics(self):
        data = model()
        command = data['topics']['1']['sequences'][0]['lines'][0]['commands'][0]
        command.update(dialogue_command_type='2', int_param='5', char_param='unrelated_scene_camera')
        camera = b'<Objects><Entity Name="unrelated_scene_camera" EntityClass="CameraSource" EntityGuid="4667872F5E7F435C" EntityId="12" Pos="1,2,3" Rotate="1,0,0,0" Layer="source"><CameraProxy Fov="0.31" FocusDistance="1.6"/></Entity></Objects>'
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'level.pak'
            with zipfile.ZipFile(path, 'w') as archive:
                archive.writestr('layers/arbitrary.xml', camera)
            converted, report = camera_assets(data, path)
            entity = ET.fromstring(converted).find('Entity')
            self.assertEqual(entity.get('Pos'), '1,2,3')
            self.assertEqual(entity.find('CameraProxy').get('Fov'), '0.31')
            self.assertIsNone(entity.get('EntityId'))
            self.assertEqual(len(report), 1)


if __name__ == '__main__':
    unittest.main()
