from pathlib import Path
import os
import sys
import unittest
from unittest.mock import patch
import xml.etree.ElementTree as ET

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
import shared_xml


LAYER = b'<Objects>\n  <Entity EntityId="1" Name="a"/>\n  <Entity EntityId="2" Name="b"/>\n</Objects>'


class SharedXmlTests(unittest.TestCase):
    def setUp(self):
        shared_xml.clear()
        self.addCleanup(shared_xml.clear)

    def test_identical_bytes_share_one_tree_and_changed_bytes_do_not(self):
        first = shared_xml.parse(LAYER)
        self.assertIs(shared_xml.parse(bytes(LAYER)), first)
        changed = shared_xml.parse(LAYER.replace(b'"b"', b'"c"'))
        self.assertIsNot(changed, first)
        self.assertEqual([e.get('Name') for e in changed.iter('Entity')], ['a', 'c'])
        self.assertEqual(ET.tostring(first), ET.tostring(ET.fromstring(LAYER)))
        self.assertEqual(shared_xml.stats()['hits'], 1)

    def test_text_documents_are_shared_apart_from_their_bytes(self):
        text = LAYER.decode()
        self.assertIs(shared_xml.parse(text), shared_xml.parse(str(text)))
        self.assertIsNot(shared_xml.parse(text), shared_xml.parse(LAYER))

    def test_memo_stops_admitting_at_its_budget_and_evicts_nothing(self):
        cost = shared_xml.TREE_FACTOR * len(LAYER)
        shared_xml._STATE['budget'] = cost  # room for exactly one document
        kept = shared_xml.parse(LAYER)
        other = LAYER.replace(b'"a"', b'"z"')
        self.assertIsNot(shared_xml.parse(other), shared_xml.parse(other))  # not admitted
        self.assertIs(shared_xml.parse(LAYER), kept)  # still there
        self.assertEqual(shared_xml.stats()['documents'], 1)

    def test_budget_follows_free_memory_within_bounds(self):
        for free, expected in ((None, shared_xml.MIN_BUDGET), (2 * 1024**3, shared_xml.MIN_BUDGET),
                               (16 * 1024**3, 1024**3), (64 * 1024**3, shared_xml.MAX_BUDGET)):
            with self.subTest(free=free), patch('bounded_pool.available_memory', return_value=free):
                shared_xml.clear()
                self.assertEqual(shared_xml._budget(), expected)

    def test_switch_off_parses_every_call(self):
        with patch.dict(os.environ, {'GLUEMAPPER_SHARED_XML': '0'}):
            self.assertIsNot(shared_xml.parse(LAYER), shared_xml.parse(LAYER))

    def test_check_mode_reports_a_reader_that_edited_a_shared_tree(self):
        with patch.dict(os.environ, {'GLUEMAPPER_SHARED_XML_CHECK': '1'}):
            root = shared_xml.parse(LAYER)
            self.assertEqual(shared_xml.verify(), 1)
            root.find('Entity').set('Name', 'edited')
            with self.assertRaisesRegex(RuntimeError, 'edited'):
                shared_xml.verify()
            with self.assertRaisesRegex(RuntimeError, 'edited'):
                shared_xml.parse(LAYER)

    def test_without_tail_ignores_the_tail_and_leaves_the_element_alone(self):
        root = shared_xml.parse(LAYER)
        first, second = root.findall('Entity')
        self.assertEqual(first.tail, '\n  ')
        self.assertEqual(shared_xml.without_tail(first), b'<Entity EntityId="1" Name="a" />')
        self.assertEqual(first.tail, '\n  ')
        self.assertEqual(ET.tostring(root), ET.tostring(ET.fromstring(LAYER)))


if __name__ == '__main__': unittest.main()
