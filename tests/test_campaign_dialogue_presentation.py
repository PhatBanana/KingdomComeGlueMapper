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
    def test_default_camera_preserves_speakers_without_invalid_enum(self):
        import copy
        source = model()
        source['roles']['3'] = dict(role_name='HENRY')
        lines = source['topics']['1']['sequences'][0]['lines']
        second = copy.deepcopy(lines[1])
        second['response']['role_id'] = '3'
        second['source']['sequence_line_id'] = '22'
        lines.append(second)
        blob, _ = emit(source, 'conversation', [])
        responses = ET.fromstring(blob).findall('.//Response')
        self.assertEqual([r.get('Role') for r in responses], ['MOTHER', 'HENRY'])
        self.assertTrue(all(r.find('./Commands/CameraCommand') is None for r in responses))
        with self.assertRaisesRegex(ValueError, 'Unconverted camera command'):
            presentation_command(dict(who='456', target='0', dialogue_command_type='2',
                                      int_param='0', char_param=''), source)

    def test_default_camera_preserves_authored_shots_and_bark_player_control(self):
        from campaign_dialogue import response_camera_command
        source = model()
        response = source['topics']['1']['sequences'][0]['lines'][1]['response']
        self.assertIsNone(response_camera_command(response,
            [dict(dialogue_command_type='2')], source))
        self.assertIsNone(response_camera_command(response, [], source, in_world=True))

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

    def test_look_at_keeps_actor_and_target_distinct_after_role_remap(self):
        from campaign_actor_dialogues import remap_roles
        source = model()
        source['roles']['3'] = dict(role_name='HENRY')
        source = remap_roles(source, {'MOTHER': 'imported_mother'})
        command = dict(who='456', target='3', delay='0.25', int_param='', char_param='', dialogue_command_type='4')
        converted = presentation_command(command, source)
        self.assertEqual(converted.attrib, dict(Role='imported_mother', LookAtRole='HENRY', Delay='0.25'))
        command['target'] = '999'
        with self.assertRaisesRegex(ValueError, 'target role'):
            presentation_command(command, source)

    def test_response_camera_and_listener_camera_do_not_change_speaker(self):
        source = model()
        source['roles']['3'] = dict(role_name='HENRY')
        lines = source['topics']['1']['sequences'][0]['lines']
        lines[1]['response']['camera_mode'] = '4'
        lines[0]['commands'] = [dict(who='3', target='0', delay='1.5', int_param='2', char_param='', dialogue_command_type='2')]
        blob, _ = emit(source, 'example', [], convert_presentation=True)
        response = ET.fromstring(blob).find('.//Response')
        self.assertEqual(response.get('Role'), 'MOTHER')
        cameras = response.findall('./Commands/CameraCommand')
        self.assertEqual([(c.get('Role'), c.get('CameraType')) for c in cameras], [('MOTHER','CloseUp'), ('HENRY','Medium')])
        self.assertEqual(cameras[1].get('Delay'), '1.5')

    def test_targeting_is_converted_without_enabling_unverified_gestures(self):
        source = model()
        source['roles']['3'] = dict(role_name='HENRY')
        lines = source['topics']['1']['sequences'][0]['lines']
        lines[0]['commands'].append(dict(who='456', target='3', delay='', int_param='', char_param='', dialogue_command_type='4'))
        blob, report = emit(source, 'example', [])
        root = ET.fromstring(blob)
        self.assertEqual(root.find('.//LookAtCommand').get('LookAtRole'), 'HENRY')
        self.assertIsNone(root.find('.//AnimationCommand'))
        self.assertEqual(report['presentation_pending'][0]['commands'][0]['dialogue_command_type'], '3')

    def test_silent_look_at_actor_is_an_import_dependency(self):
        from campaign_dialogue import referenced_roles
        source = model()
        source['roles']['99'] = dict(role_name='SILENT_LISTENER')
        source['topics']['1']['sequences'][0]['lines'][0]['commands'].append(
            dict(who='456', target='99', dialogue_command_type='4'))
        self.assertEqual(referenced_roles(source), {'456', '99'})
        del source['roles']['99']
        with self.assertRaisesRegex(ValueError, 'role dependencies'):
            referenced_roles(source)

    def test_installed_reconciliation_is_idempotent_and_preserves_audio(self):
        from campaign_dialogue_presentation import upgrade
        source = model()
        source['topics']['1']['sequences'][0]['lines'][1]['response']['camera_mode'] = '4'
        original, _ = emit(model(), 'example', [])
        root = ET.fromstring(original)
        root.find('.//Response').set('ReferenceLength', '2.75')
        changed, report = upgrade(ET.tostring(root), source)
        self.assertEqual(len(report['added']), 1)
        self.assertEqual(ET.fromstring(changed).find('.//Response').get('ReferenceLength'), '2.75')
        twice, report = upgrade(changed, source)
        self.assertEqual(report['added'], [])
        self.assertEqual(changed, twice)
        root.find('.//Text').set('StringName', 'missing')
        with self.assertRaisesRegex(ValueError, 'Missing installed response'):
            upgrade(ET.tostring(root), source)

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
