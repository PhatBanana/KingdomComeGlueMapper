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


class MarketJobTests(unittest.TestCase):
    def test_a_keeper_never_takes_the_job_of_a_keeper_whose_name_extends_it(self):
        # unified-13: sas_merchant took gm_schedule_sas_merchant_grocery_11682.
        import xml.etree.ElementTree as E
        from setup_work_speech import market_jobs
        mission = E.fromstring('<Objects>'
            '<Entity Name="gm_schedule_sas_merchant_11664"><Properties guidSmartObjectType="m"/></Entity>'
            '<Entity Name="gm_schedule_sas_merchant_grocery_11682"><Properties guidSmartObjectType="m"/></Entity>'
            '<Entity Name="gm_schedule_sas_merchant_11665"><Properties guidSmartObjectType="other"/></Entity>'
            '</Objects>')
        self.assertEqual([e.get('Name') for e in market_jobs(mission, 'sas_merchant', 'm')],
                         ['gm_schedule_sas_merchant_11664'])
        self.assertEqual([e.get('Name') for e in market_jobs(mission, 'sas_merchant_grocery', 'm')],
                         ['gm_schedule_sas_merchant_grocery_11682'])


if __name__ == '__main__':
    unittest.main()
