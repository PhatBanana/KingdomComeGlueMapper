import sys
from pathlib import Path
import unittest
import xml.etree.ElementTree as ET

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from campaign_scene import attach_scene
from campaign_start_policy import METHOD, POLICY, gate_start, validate_native, validate_start_policy


class CampaignStartPolicyTests(unittest.TestCase):
    def scene(self):
        host = b'<Database><Skald><Project><Definitions/><Nodes/><Types/><ObjectiveValueTypes/></Project></Skald></Database>'
        source = b'<Database><Skald><Project><Definitions/><Nodes><Quest Name="quest"/><Dialogue Name="opening"/></Nodes><Types/><ObjectiveValueTypes/></Project></Skald></Database>'
        return attach_scene(host, source, 'opening', 'quest', 'region.arrived', 'Finished', 'player')

    def test_shared_scene_builder_gates_entire_initialization(self):
        blob = self.scene()
        self.assertEqual(validate_start_policy(blob, 'opening'), POLICY)
        nodes = ET.fromstring(blob).find('./Skald/Project/Nodes')
        sequence = nodes.find("TriggerSequence[@Name='opening_initialize']")
        self.assertEqual(sequence.find('Edge').attrib, {'From': 'opening_new_game.True', 'To': 'Exec'})
        self.assertEqual(nodes.find("Quest/Edge[@To='start']").get('From'), 'opening_initialize.B')
        self.assertEqual(nodes.find("Dialogue/Edge[@To='EnqueueDialogue']").get('From'), 'opening_initialize.C')
        self.assertIsNotNone(nodes.find("State/Edge[@From='opening_new_game.False'][@To='SetTrue']"))
        self.assertEqual(gate_start(blob, 'opening'), blob)

    def test_unprotected_existing_packages_can_be_migrated(self):
        root = ET.fromstring(self.scene())
        nodes = root.find('./Skald/Project/Nodes')
        nodes.remove(nodes.find('IfFunction'))
        nodes.find('TriggerSequence/Edge').set('From', 'opening_begin.True')
        latch = nodes.find('State')
        latch.remove(latch.find("Edge[@From='opening_new_game.False']"))
        old = ET.tostring(root)
        with self.assertRaises(ValueError):
            validate_start_policy(old, 'opening')
        self.assertEqual(validate_start_policy(gate_start(old, 'opening'), 'opening'), POLICY)

    def test_bypass_edges_and_wrong_predicate_are_rejected(self):
        for kind in ('sequence', 'guard', 'condition', 'visitor', 'method'):
            with self.subTest(kind=kind):
                root = ET.fromstring(self.scene())
                nodes = root.find('./Skald/Project/Nodes')
                if kind in ('sequence', 'guard', 'condition'):
                    tag, port = {'sequence': ('TriggerSequence', 'Exec'), 'guard': ('IfFunction', 'Exec'), 'condition': ('If', 'Condition')}[kind]
                    ET.SubElement(nodes.find(tag), 'Edge', From='region.arrived', To=port)
                elif kind == 'visitor':
                    latch = nodes.find('State')
                    latch.remove(latch.find("Edge[@From='opening_new_game.False']"))
                else:
                    nodes.find('IfFunction').set('MethodName', 'wrong')
                with self.assertRaises(ValueError):
                    validate_start_policy(ET.tostring(root), 'opening')

    def test_native_definition_contract_required(self):
        root = ET.fromstring('<Definitions><Definition TypeName="IfFunction"><Properties/><Ports/></Definition></Definitions>')
        definition = root.find('Definition')
        ET.SubElement(definition.find('Properties'), 'Property', Name='MethodName', Value=METHOD)
        for name, direction in [('Exec', 'In'), ('True', 'Out'), ('False', 'Out')]:
            ET.SubElement(definition.find('Ports'), 'CompileTimePort', Name=name, Direction=direction, Type='trigger')
        validate_native(ET.tostring(root))
        definition.find('Ports')[2].set('Type', 'bool')
        with self.assertRaises(ValueError):
            validate_native(ET.tostring(root))
        with self.assertRaises(ValueError):
            validate_native(b'<Definitions/>')


if __name__ == '__main__':
    unittest.main()
