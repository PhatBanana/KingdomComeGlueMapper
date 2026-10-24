import json
from pathlib import Path
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from region_travel_entry import entry_graph
from region_travel_ui_gate import gate, upgrade, FILTERS, TRAVEL
from setup_campaign import digest


class ArrivalUiGateTests(unittest.TestCase):
    def nodes(self, blob):
        return ET.fromstring(blob).find('Skald/Level/Nodes')

    def test_native_filters_follow_one_bounded_timer_started_by_both_entry_events(self):
        for profile in (None, 'kcd1_travel_arrival'):
            nodes = self.nodes(gate(entry_graph('kcd1_travel', profile), 'kcd1_travel'))
            timer = nodes.find("Timer[@Name='arrival_ui_settle']")
            self.assertEqual({c.get('Name'): c.get('Value') for c in timer.findall('Constant')},
                             {'Duration': '90s', 'TimeType': 'GameTime'})
            self.assertEqual(sorted((e.get('From'), e.get('To')) for e in timer.findall('Edge')),
                             [('OnLevelSwitched', 'SetRunning'), ('OnWake', 'SetRunning')])
            # Nothing can stop or restart the hold except a new level entry.
            self.assertEqual({e.get('To') for e in timer.findall('Edge')}, {'SetRunning'})
            array = nodes.find("MakeArray[@Name='arrival_ui_filters']")
            self.assertEqual(array.get('TypeT'), 'Strings')
            self.assertEqual([c.get('Value') for c in array.findall('Constant')], ['no_inventory', 'no_interaction'])
            hold = nodes.find("FilterInput[@Name='arrival_ui_gate']")
            self.assertEqual({e.get('To'): e.get('From') for e in hold.findall('Edge')},
                             {'Filters': 'arrival_ui_filters.Array', 'IsActive': 'arrival_ui_settle.Running'})
            self.assertEqual(len(nodes.findall('FilterInput')), 1)

    def test_streaming_ready_state_is_not_driven_by_the_hold(self):
        nodes = self.nodes(gate(entry_graph('kcd1_travel', 'kcd1_travel_arrival'), 'kcd1_travel'))
        ready = nodes.find("State[@Name='entry_ready']")
        self.assertEqual(ready.find("Edge[@To='SetTrue']").get('From'), 'stream_station.onloaded')
        self.assertFalse(any('arrival_ui' in e.get('From', '') for e in ready.iter('Edge')))

    def test_gate_is_idempotent_and_rejects_partial_or_foreign_graphs(self):
        once = gate(entry_graph('kcd1_travel', None), 'kcd1_travel')
        self.assertIs(gate(once, 'kcd1_travel'), once)
        with self.assertRaises(ValueError):
            gate(entry_graph('other', None), 'kcd1_travel')
        root = ET.fromstring(once)
        nodes = root.find('Skald/Level/Nodes')
        nodes.remove(nodes.find("FilterInput[@Name='arrival_ui_gate']"))
        with self.assertRaises(ValueError):
            gate(ET.tostring(root), 'kcd1_travel')

    def test_saved_build_upgrade_rewrites_only_the_entry_graph_once(self):
        entry = 'Quests/GlueTravel/entry/kcd1_travel.xml'
        with tempfile.TemporaryDirectory() as temporary:
            package = Path(temporary)
            (package / 'Data').mkdir()
            other = b'<Database><Skald><Project Name="GlueTravel"/></Skald></Database>'
            with zipfile.ZipFile(package / TRAVEL, 'w') as z:
                z.writestr(entry, entry_graph('kcd1_travel', None))
                z.writestr('Quests/GlueTravel/GlueTravel_kcd1.xml', other)
            files, report = upgrade(package)
            self.assertEqual(files, {TRAVEL: digest(package / TRAVEL)})
            self.assertTrue(report['changed'])
            self.assertEqual(report['filters'], list(FILTERS))
            self.assertFalse(report['notification'])
            self.assertFalse(report['runtime_verified'])
            json.dumps(report)
            with zipfile.ZipFile(package / TRAVEL) as z:
                self.assertEqual(z.read('Quests/GlueTravel/GlueTravel_kcd1.xml'), other)
                upgraded = z.read(entry)
            self.assertIsNotNone(self.nodes(upgraded).find("FilterInput[@Name='arrival_ui_gate']"))
            files, report = upgrade(package)
            self.assertEqual(files, {})
            self.assertFalse(report['changed'])
            with zipfile.ZipFile(package / TRAVEL) as z:
                self.assertEqual(z.read(entry), upgraded)

    def test_saved_build_without_entry_graph_is_refused(self):
        with tempfile.TemporaryDirectory() as temporary:
            package = Path(temporary)
            (package / 'Data').mkdir()
            with zipfile.ZipFile(package / TRAVEL, 'w') as z:
                z.writestr('Quests/GlueTravel/GlueTravel_kcd1.xml', b'<Database/>')
            with self.assertRaises(ValueError):
                upgrade(package)


if __name__ == '__main__':
    unittest.main()
