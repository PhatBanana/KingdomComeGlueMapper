import unittest
import xml.etree.ElementTree as E
from training_presentation_repair import guard_progress, repair_progress_types


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


class ProgressDefinitions(unittest.TestCase):
    def test_inherited_enum_is_installed_and_defaults_to_none(self):
        root=E.fromstring('<Quest Name="lesson"><Nodes><State Name="state" TypeT="Progress"><Edge From="stop" To="SetNone"/></State></Nodes></Quest>')
        definition=E.fromstring('<Type TypeName="Progress"><StateTypeEnumeration Name="None"/><StateTypeEnumeration Name="Active"/><StateTypeEnumeration Name="Done"/></Type>')
        repair_progress_types(root,'lesson_presentation',{'Progress':definition})
        self.assertEqual(root.find('Nodes/State').get('TypeT'),'lesson_presentation_Progress')
        self.assertEqual(root.find('Nodes/State/Constant').get('Value'),'None')
        self.assertEqual([n.get('Name') for n in root.find('Types/Type')],['None','Active','Done'])
        before=E.tostring(root)
        repair_progress_types(root,'lesson_presentation',{'Progress':definition})
        self.assertEqual(E.tostring(root),before)

    def test_missing_definition_is_not_assumed_builtin(self):
        with self.assertRaisesRegex(ValueError,'Missing native'):
            repair_progress_types(E.fromstring('<Module><State TypeT="Progress"/></Module>'),'lesson',{})
