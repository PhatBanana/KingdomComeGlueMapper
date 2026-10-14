import sys
from pathlib import Path
import unittest
import xml.etree.ElementTree as ET

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from campaign_refresh import objective_timers, dialogue_endings, dialogue_cameras
from campaign_quest_graph import emit_project
from test_campaign_quest_graph import model


class RefreshTests(unittest.TestCase):
    def test_automatic_camera_refresh_preserves_other_commands_and_is_idempotent(self):
        from test_campaign_dialogue_presentation import model as dialogue_model
        from campaign_refresh import dialogue_camera_selection
        source = dialogue_model()
        blob = b'<Database><Skald><FaderDialog><Dialogue><Sequence Name="seq_10"><Elements><Response Role="renamed"><Text StringName="speech"/><Commands><FacialMoodCommand FacialMood="happy"/><CameraCommand CameraType="CloseUp"/></Commands></Response></Elements></Sequence></Dialogue></FaderDialog></Skald></Database>'
        result, report = dialogue_camera_selection(blob, source)
        repeated, _ = dialogue_camera_selection(result, source)
        self.assertEqual(result, repeated)
        root = ET.fromstring(result)
        self.assertEqual(root.find('.//CameraCommand').attrib, {'Role': 'renamed'})
        self.assertIsNotNone(root.find('.//FacialMoodCommand'))
        self.assertEqual(report['automatic'], 1)
        source['topics']['1']['sequences'][0]['lines'][1]['response']['string_name'] = 'wrong'
        with self.assertRaisesRegex(ValueError, 'order differs'):
            dialogue_camera_selection(blob, source)

    def test_camera_refresh_preserves_runtime_voice_and_source_response_order(self):
        from test_campaign_dialogue_presentation import model as dialogue_model
        source = dialogue_model()
        command = source['topics']['1']['sequences'][0]['lines'][0]['commands'][0]
        command.update(dialogue_command_type='2', int_param='5', char_param='source_cam')
        blob = b'<Database><Skald><FaderDialog><Dialogue><Sequence Name="seq_10"><Elements><Response Role="native_actor"><Text StringName="speech"/><Commands><FacialMoodCommand FacialMood="happy"/></Commands></Response></Elements></Sequence></Dialogue></FaderDialog></Skald></Database>'
        result, changes = dialogue_cameras(blob, source, {'source_cam'}, {'MOTHER':'native_actor'})
        repeated, _ = dialogue_cameras(result, source, {'source_cam'}, {'MOTHER':'native_actor'})
        self.assertEqual(result, repeated)
        self.assertEqual(ET.fromstring(result).find('.//CameraCommand').get('Role'), 'native_actor')
        self.assertIsNotNone(ET.fromstring(result).find('.//FacialMoodCommand'))
        self.assertEqual(changes[0]['response'], '21')
        with self.assertRaisesRegex(ValueError, 'Unregistered source camera'):
            dialogue_cameras(blob, source, set())

    def test_refresh_keeps_runtime_bindings_and_is_repeatable(self):
        source = model()
        old, _ = emit_project([source], 'Example')
        root = ET.fromstring(old['Example/arbitrary_quest.xml'])
        nodes = root.find('./Skald/Quest/Nodes')
        ET.SubElement(nodes, 'Trace', Name='preserved_reward_binding')
        source['tables']['quest_objective']['rows'][0].update(condition='1', autocomplete_timeout_str='4m #GT')
        updated, report = objective_timers(ET.tostring(root), source)
        repeated, _ = objective_timers(updated, source)
        self.assertEqual(updated, repeated)
        result = ET.fromstring(updated)
        self.assertIsNotNone(result.find(".//Trace[@Name='preserved_reward_binding']"))
        self.assertEqual(result.find(".//Timer/Constant[@Name='Duration']").get('Value'), '4m')
        self.assertIn(dict(objective='3', duration='4m'), report['timers'])

    def test_dialogue_refresh_only_changes_source_terminal_end_policy(self):
        blob = b'<Database><Skald><ForcedDialog><Dialogue><Sequence Name="seq_10" EndType="EndDialogue" ExitScript="preserve()"/></Dialogue></ForcedDialog></Skald></Database>'
        source = dict(topics={'1':dict(sequences=[dict(source=dict(sequence_id='10',flags='0',next='0'))])})
        updated, changes = dialogue_endings(blob, source)
        sequence = ET.fromstring(updated).find('.//Sequence')
        self.assertIsNone(sequence.get('EndType'))
        self.assertEqual(sequence.get('ExitScript'), 'preserve()')
        self.assertEqual(len(changes), 1)


if __name__ == '__main__': unittest.main()
