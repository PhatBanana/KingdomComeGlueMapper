import sys
from pathlib import Path
import unittest
import xml.etree.ElementTree as E
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from campaign_linked_conditions import expose_state_changes


class StateNotificationTests(unittest.TestCase):
    def test_migration_preserves_quest_and_exposes_each_source_state_once(self):
        blob=b'''<Document><Skald><Quest Name="another_quest"><Ports/><Nodes><Output Name="Output"/>
<State Name="quest_progress"/><State Name="quest_available"/><State Name="objective_91"/>
<State Name="unrelated"/></Nodes></Quest></Skald></Document>'''
        result=expose_state_changes(blob)
        root=E.fromstring(result)
        self.assertEqual({e.get('From') for e in root.findall('.//Output/Edge')},
            {'quest_progress.OnExec','quest_available.OnExec','objective_91.OnExec'})
        self.assertEqual(expose_state_changes(result),result)
        with self.assertRaises(ValueError):expose_state_changes(result.replace(b'objective_91.OnExec',b'unrelated.OnExec'))

if __name__=='__main__':unittest.main()
