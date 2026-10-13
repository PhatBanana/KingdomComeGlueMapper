import sys
from pathlib import Path
import unittest
import xml.etree.ElementTree as ET

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from campaign_dialogue_runtime import bind_recordings, attach_dialogue
from test_dialogue_dubbing import ogg


class RuntimeDialogueTests(unittest.TestCase):
    def test_level_container_resolves_relative_definitions_and_engine_predicate(self):
        from campaign_dialogue_conditions import QuestConditions
        conditions = QuestConditions([])
        conditions.compile('!IsStreamInstallComplete()')
        key = next(iter(conditions.bindings))
        files = {'world/entry/level.xml': b'<Database><Skald><Level><Definitions><Definition File="../quest.xml"/></Definitions><Nodes><quest Name="quest"/></Nodes></Level></Skald></Database>',
                 'world/quest.xml': b'<Database><Skald><Quest Name="quest"><Ports><Port Name="ready" Direction="Out" Type="bool"/></Ports></Quest></Skald></Database>'}
        blob = self.sample()[0].replace(b'</Ports>', ('<Port Name="' + key + '" Direction="In" Type="bool"/></Ports>').encode())
        result = attach_dialogue(files, 'level', blob, dict(actions={}, active_port='active', conditions=conditions.bindings),
                                 'quest.ready', 'world/entry/level.xml')
        root = ET.fromstring(result['world/entry/level.xml'])
        function = root.find('.//Function')
        self.assertEqual(function.get('MethodName'), 'wh::framework::IsStreamInstallComplete')
        self.assertIn('world/entry/level/scene.xml', result)
        self.assertEqual(root.findall('.//scene/Edge')[1].get('From'), function.get('Name') + '.IsCompleted')
        self.assertNotIn(b'Constant', result['world/entry/level.xml'])

    def test_level_uses_parent_project_declarations(self):
        files = {'project.xml': b'<Database><Skald><Project Name="project"><Definitions><Definition File="entry/level.xml"/><Definition File="quest.xml"/></Definitions><Nodes/></Project></Skald></Database>',
                 'entry/level.xml': b'<Database><Skald><Level Name="level"><Definitions/><Nodes><quest Name="quest"/></Nodes></Level></Skald></Database>',
                 'quest.xml': b'<Database><Skald><Quest Name="quest"><Ports><Port Name="ready" Direction="Out" Type="bool"/></Ports></Quest></Skald></Database>'}
        result = attach_dialogue(files, 'level', self.sample()[0], dict(actions={}), 'quest.ready', 'entry/level.xml')
        self.assertIn('entry/level/scene.xml', result)
        del files['project.xml']
        with self.assertRaisesRegex(ValueError, 'Missing declared project instance'):
            attach_dialogue(files, 'level', self.sample()[0], dict(actions={}), 'quest.ready', 'entry/level.xml')

    def sample(self):
        model = dict(roles={'7': {'role_name': 'SPEAKER'}}, topics={'1': dict(sequences=[dict(lines=[
            dict(response={'role_id': '7', 'string_name': 'line_aBcD'},
                 voices=[{'wave_file': 'voice_line_aBcD'}])])])})
        blob = b'<Database><Skald><ForcedDialog Name="scene"><Ports><Port Name="active" Direction="In" Type="bool"/></Ports><Dialogue><Decision><Sequences><Sequence><Elements><Response Role="SPEAKER"><Text StringName="line_aBcD"/></Response></Elements></Sequence></Sequences></Decision></Dialogue></ForcedDialog></Skald></Database>'
        voices = b'<database><voices><voice abbreviation="voice" voice_technical_name="OriginalActor" voice_id="8"/></voices></database>'
        return blob, model, {'dialog/old/voice_line_aBcD.ogg': ogg()}, voices

    def test_original_recording_uses_native_namespace_and_timing(self):
        blob, media, report = bind_recordings(*self.sample())
        root = ET.fromstring(blob)
        self.assertEqual(root.find('./Skald/ForcedDialog').get('VoiceNamespace'), 'true')
        self.assertEqual(root.find('.//SelectedSoul').get('Voice'), 'OriginalActor')
        self.assertEqual(root.find('.//Response').get('ReferenceLength'), '1.500000')
        self.assertEqual(list(media), ['dialog/scene/voice_line_aBcD.ogg'])
        self.assertFalse(report['runtime_verified'])

    def test_unresolved_and_ambiguous_recordings_fail(self):
        blob, model, media, voices = self.sample()
        with self.assertRaises(ValueError): bind_recordings(blob, model, {}, voices)
        with self.assertRaises(ValueError): bind_recordings(blob, model, media, b'<database/>')
        with self.assertRaises(ValueError): bind_recordings(blob, model, {**media, 'elsewhere/voice_line_aBcD.ogg': ogg()}, voices)

    def test_objective_edges_validate_ports_without_starting_scene(self):
        files = {'world.xml': b'<Database><Skald><Project><Definitions><Definition File="quest.xml"/></Definitions><Nodes><quest Name="quest"/></Nodes></Project></Skald></Database>',
                 'quest.xml': b'<Database><Skald><Quest Name="quest"><Ports><Port Name="ready" Direction="Out" Type="bool"/><Port Name="start_choice" Direction="In" Type="trigger"/></Ports></Quest></Skald></Database>'}
        blob = self.sample()[0].replace(b'</Ports>', b'<Port Name="choice" Direction="Out" Type="trigger"/></Ports>')
        report = {'actions': {'choice': {'quest': 'quest', 'input': 'start_choice'}}}
        result = attach_dialogue(files, 'world', blob, report, 'quest.ready')
        root = ET.fromstring(result['world.xml'])
        self.assertEqual(root.find('.//quest/Edge').attrib, {'From': 'scene.choice', 'To': 'start_choice'})
        self.assertEqual(root.find('.//scene/Edge').attrib, {'From': 'quest.ready', 'To': 'active'})
        self.assertNotIn(b'GameStart', result['world.xml'])
        self.assertNotIn(b'Edge', files['world.xml'])
        with self.assertRaises(ValueError): attach_dialogue(files, 'world', blob, report, 'quest.missing')
        with self.assertRaises(ValueError): attach_dialogue(files, 'world', blob, {'actions': {}}, 'quest.ready')


if __name__ == '__main__':
    unittest.main()
