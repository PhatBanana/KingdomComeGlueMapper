import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'tools'))
from setup_work_speech import soul_voice


def report(voice, role='VYVOLAVANI'):
    return dict(binding=dict(roles={role: dict(voice_technical_name=voice, voice_id='1')}))


class SoulVoiceTests(unittest.TestCase):
    def test_two_cry_branches_of_one_soul_bind_one_voice(self):
        # led_merchant_grocery owns cries 26007 and 26856; both speak with bdou.
        self.assertEqual(soul_voice([report('gm_source_bdou'), report('gm_source_bdou', 'OTHER')])['voice_technical_name'],
                         'gm_source_bdou')

    def test_branches_that_disagree_on_the_voice_stop_the_stage(self):
        with self.assertRaisesRegex(ValueError, 'disagree'):
            soul_voice([report('gm_source_bdou'), report('gm_source_rpro')])

    def test_a_soul_without_branches_has_no_voice(self):
        with self.assertRaisesRegex(ValueError, 'disagree'):
            soul_voice([])


if __name__ == '__main__':
    unittest.main()
