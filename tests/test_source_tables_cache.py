"""SourceTables shares parsed rows across instances without sharing row objects."""
import hashlib
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
import campaign_dependency_adapters as adapters
from campaign_dependency_adapters import SourceTables


def table(*rows):
    body = ''.join('<row ' + ' '.join(f'{k}="{v}"' for k, v in row.items()) + '/>' for row in rows)
    return f'<database><table name="t"><rows>{body}</rows></table></database>'.encode()


class Reader:
    """Stands in for RetailSourceReader: the selected candidate carries the data's hash."""
    def __init__(self, data):
        self.data, self.calls = data, 0

    def __call__(self, source, files):
        self.calls += 1
        data = self.data
        return {'table': dict(data=data, candidates=[dict(archive='Data/Tables.pak', revision='base',
                                                          sha256=hashlib.sha256(data).hexdigest())])}


class SourceTablesCacheTests(unittest.TestCase):
    def setUp(self):
        adapters._ROWS.clear()

    def test_rows_are_shared_by_content_but_not_by_object(self):
        reader = Reader(table({'soul_name': 'Ada', 'id': '1'}, {'soul_name': 'bob', 'id': '2'}))
        first, second = SourceTables('game', reader), SourceTables('game', reader)
        self.assertEqual(first.get('rpg/soul')['rows'], second.get('rpg/soul')['rows'])
        first.get('rpg/soul')['rows'][0]['id'] = 'changed'
        self.assertEqual(second.get('rpg/soul')['rows'][0]['id'], '1')
        self.assertEqual(SourceTables('game', reader).get('rpg/soul')['rows'][0]['id'], '1')
        self.assertIs(first.get('rpg/soul'), first.get('rpg/soul'))   # one table per instance, read once
        self.assertEqual(reader.calls, 3)

    def test_changed_table_bytes_are_parsed_again(self):
        reader = Reader(table({'soul_name': 'ada'}))
        self.assertEqual(SourceTables('game', reader).get('rpg/soul')['rows'], [{'soul_name': 'ada'}])
        reader.data = table({'soul_name': 'eve'})
        self.assertEqual(SourceTables('game', reader).get('rpg/soul')['rows'], [{'soul_name': 'eve'}])

    def test_lookup_matches_the_linear_scan(self):
        tables = SourceTables('game', Reader(table({'soul_name': 'Ada', 'id': '1'}, {'soul_name': 'twin', 'id': '2'},
                                                   {'soul_name': 'TWIN', 'id': '3'}, {'id': '4'})))
        self.assertEqual(tables.row('rpg/soul', 'soul_name', 'ADA')['id'], '1')
        self.assertEqual(tables.row('rpg/soul', 'soul_name', '')['id'], '4')   # a missing field matches ''
        self.assertEqual(tables.row('rpg/soul', 'soul_name', 'nobody', optional=True), {})
        for value in ('twin', 'nobody'):
            with self.assertRaisesRegex(ValueError, 'Missing/ambiguous'):
                tables.row('rpg/soul', 'soul_name', value)
        self.assertIs(tables.row('rpg/soul', 'id', '1'), tables.get('rpg/soul')['rows'][0])

    def test_cache_stays_within_its_byte_bound(self):
        with patch.object(adapters, 'ROWS_CACHE_BYTES', 300):
            for name in 'abcdefgh':
                SourceTables('game', Reader(table({'soul_name': name * 40}))).get('rpg/' + name)
            self.assertLessEqual(sum(size for _, size in adapters._ROWS.values()), 300)
            self.assertIn('rpg/h', {key[0] for key in adapters._ROWS})


if __name__ == '__main__':
    unittest.main()
