import unittest
import xml.etree.ElementTree as E
from training_presentation_repair import guard_progress


class InactivePresentation(unittest.TestCase):
    def test_completion_and_cancel_require_active_but_reset_does_not(self):
        root=E.fromstring('''<Module><Ports><Port Name="gm_active"/></Ports><Nodes>
          <State Name="objective" TypeT="ProgressFailable">
            <Edge From="finished" To="SetDone"/><Edge From="canceled" To="SetCanceled"/>
            <Edge From="gm_stop" To="SetNone"/>
          </State><State Name="speaking" TypeT="bool"><Edge From="after" To="SetFalse"/></State>
        </Nodes></Module>''')
        self.assertEqual(guard_progress(root),2)
        for gate in root.findall('Nodes/If'):
            self.assertIsNotNone(gate.find("Edge[@From='gm_active'][@To='Condition']"))
        self.assertIsNotNone(root.find("Nodes/State/Edge[@From='gm_stop'][@To='SetNone']"))
        self.assertIsNotNone(root.find("Nodes/State[@Name='speaking']/Edge[@From='after']"))
        before=E.tostring(root);self.assertEqual(guard_progress(root),0);self.assertEqual(E.tostring(root),before)

    def test_phase_dispatch_is_guarded(self):
        root=E.fromstring('<Module><Ports><Port Name="active"/></Ports><Nodes><State Name="phase" TypeT="custom_enum"><Edge From="phase_started" To="Exec"/><Edge From="switch.Value" To="Value"/><Edge From="stop" To="SetNone"/></State></Nodes></Module>')
        self.assertEqual(guard_progress(root),1)
        self.assertIsNotNone(root.find("Nodes/State/Edge[@From='switch.Value'][@To='Value']"))
