import sys
from pathlib import Path
import unittest
import xml.etree.ElementTree as E

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'tools'))
from localization_registry import reconcile


def table(key, value, prefix=b''):
    return prefix + ('<Table><Row><Cell>'+key+'</Cell><Cell>'+value+
                     '</Cell><Cell>'+value+'</Cell></Row></Table>').encode()


class LocalizationRegistryTests(unittest.TestCase):
    def test_cross_table_duplicate_and_idempotence(self):
        tables = {'items.xml': table('label', 'Hunting sword'),
                  'containers.xml': table('label', 'Hunting sword'),
                  'dialog.xml': table('hello', 'Hello', b'<?xml version="1.0"?>\n')}
        changed, report = reconcile(tables)
        self.assertEqual(set(changed), {'items.xml'})
        self.assertEqual(len(E.fromstring(changed['items.xml'])), 0)
        self.assertEqual(report, [dict(key='label', owner='containers.xml', removed_from='items.xml')])
        self.assertEqual(reconcile({**tables, **changed}), ({}, []))

    def test_conflicting_text_or_cell_metadata_rejected(self):
        original = table('label', 'Text')
        for changed in (table('label', 'Different'), table('label', ' Text'),
                        original.replace(b'<Cell>Text', b'<Cell translated="1">Text')):
            with self.subTest(changed=changed), self.assertRaisesRegex(ValueError, 'Conflicting localization key'):
                reconcile({'a.xml': original, 'b.xml': changed})

    def test_formatting_and_duplicates_within_one_table(self):
        row = b'<Row><Cell>key</Cell><Cell>Text</Cell><Cell>Text</Cell></Row>'
        blob = b'<Table>\n'+row+row.replace(b'><Cell>', b'>\n  <Cell>')+b'\n</Table>'
        changed, report = reconcile({'a.xml': blob})
        self.assertEqual(len(report), 1)
        self.assertEqual(len(E.fromstring(changed['a.xml'])), 1)

    def test_unique_tables_are_byte_preserved(self):
        self.assertEqual(reconcile({'a.xml': table('a', 'A'), 'config.xml': b'<Config />'}), ({}, []))


if __name__ == '__main__':
    unittest.main()
