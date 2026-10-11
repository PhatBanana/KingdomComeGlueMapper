from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from campaign_engine_enums import decode_serializer


def string(register, text):
    return dict(register=register, text=text, rva=32)


def member(name, ordinal):
    return [string('r8', 'Member'), string('rdx', name), string('rdx', 'value'),
        dict(register='r8d', integer=ordinal, rva=64)]


class EngineEnumTests(unittest.TestCase):
    def test_nonsequential_values_are_read_from_instructions_without_inference(self):
        events = [string('r8', 'enum'), string('r8', 'DifferentEnum'), string('rdx', 'name')]
        events += member('Earlier', 13) + member('Later', 90) + member('Latest', 300)
        result = decode_serializer(events)
        self.assertEqual(result['name'], 'DifferentEnum')
        self.assertEqual([v['ordinal'] for v in result['values']], [13, 90, 300])
        self.assertEqual(result['values'][1]['value_rva'], 64)

    def test_neighboring_strings_and_incomplete_member_are_not_declarations(self):
        with self.assertRaisesRegex(ValueError, 'Not a literal'):
            decode_serializer([string('r8', 'Nearby')])
        events = [string('r8', 'enum'), string('r8', 'DifferentEnum'), string('rdx', 'name')]
        with self.assertRaisesRegex(ValueError, 'Unsupported engine enum member'):
            decode_serializer(events + member('Value', 3)[:-1])

    def test_duplicate_members_and_unverified_signed_ordinals_fail(self):
        events = [string('r8', 'enum'), string('r8', 'DifferentEnum'), string('rdx', 'name')]
        with self.assertRaisesRegex(ValueError, 'duplicate'):
            decode_serializer(events + member('Value', 3) + member('Value', 4))
        with self.assertRaisesRegex(ValueError, 'Signed engine enum'):
            decode_serializer(events + member('Value', 0xffffffff))


if __name__ == '__main__':
    unittest.main()
