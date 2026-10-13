import sys
from pathlib import Path
import unittest
import xml.etree.ElementTree as ET

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from campaign_state_diagnostics import observe


class StateDiagnosticsTests(unittest.TestCase):
    def test_observes_real_binding_and_timer_without_changing_them(self):
        blob = b'''<Database><Skald><Quest Name="arbitrary"><Nodes>
        <State Name="objective_17" TypeT="ImportedProgress"><Constant Name="DefaultValue" Value="Unchanged"/></State>
        <Timer Name="complete_17"><Constant Name="Duration" Value="4m"/><Edge From="objective_17.OnStarted" To="SetRunning"/></Timer>
        <Output Name="Output"><Edge From="objective_17.Started" To="waiting_Started"/></Output>
        </Nodes></Quest></Skald></Database>'''
        result, report = observe(blob, ['waiting'])
        again, _ = observe(result, ['waiting'])
        self.assertEqual(result, again)
        root = ET.fromstring(result)
        self.assertEqual(len(root.findall('.//Trace')), 2)
        for before, after in zip(ET.fromstring(blob).find('.//Nodes'), root.find('.//Nodes')):
            self.assertEqual(before.attrib, after.attrib)
            self.assertEqual([c.attrib for c in before], [c.attrib for c in after])
        self.assertEqual(report[0]['timers'], ['complete_17'])
        with self.assertRaisesRegex(ValueError, 'objective binding'):
            observe(blob, ['missing'])


if __name__ == '__main__':
    unittest.main()
