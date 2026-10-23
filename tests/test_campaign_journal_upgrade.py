import sys
from pathlib import Path
import unittest
import xml.etree.ElementTree as E

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'tools'))
from campaign_quest_graph import emit_project
from campaign_quest_text import update_journal, localization_table
from test_campaign_quest_graph import model


class JournalUpgradeTests(unittest.TestCase):
    def test_source_without_journal_keeps_state_but_emits_no_technical_title(self):
        m = model()
        m['tables']['quest2skald_subchapter'] = {'rows': []}
        files, report = emit_project([m], 'Example')
        q = E.fromstring(files['Example/arbitrary_quest.xml']).find('Skald/Quest')
        self.assertIsNone(q.find('QuestName'))
        self.assertEqual(q.findall('Objectives/Objective'), [])
        self.assertIsNotNone(q.find("Nodes/State[@Name='objective_4']"))
        self.assertIsNotNone(q.find("Ports/Port[@Name='complete_first']"))
        self.assertFalse(report['quests'][0]['journal_visible'])
        self.assertEqual(report['quests'][0]['journal_strings'], [])

    def test_localized_fields_preserve_custom_graph_and_markers(self):
        m = model()
        files, _ = emit_project([m], 'Example')
        old = E.fromstring(files['Example/arbitrary_quest.xml'])
        q = old.find('Skald/Quest')
        E.SubElement(q.find('Nodes'), 'State', Name='custom_state', TypeT='bool')
        obj = q.find("Objectives/Objective[@Name='first']")
        E.SubElement(obj, 'MapMarker', Name='preserve')
        before = E.tostring(q.find('Nodes'))
        new, records = update_journal(E.tostring(old),m,{'name':'Source title','objectives':{'4':{'name':'First source step'}}})
        q = E.fromstring(new).find('Skald/Quest')
        self.assertEqual(E.tostring(q.find('Nodes')),before)
        self.assertIsNotNone(q.find("Objectives/Objective[@Name='first']/MapMarker"))
        self.assertEqual(q.find('QuestName').get('Text'),'Source title')
        keys = {r.findtext('Cell') for r in E.fromstring(localization_table(records))}
        self.assertTrue(all(e.get('StringName') in keys for e in q.iter() if e.get('StringName')))
        again, rows = update_journal(new,m,{'name':'Source title','objectives':{'4':{'name':'First source step'}}})
        self.assertEqual(new,again)
        self.assertEqual(records,rows)
