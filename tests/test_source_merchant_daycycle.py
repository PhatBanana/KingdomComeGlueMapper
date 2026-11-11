"""A resident keeper sells by day and sleeps at home; nothing else is assumed."""
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import MagicMock, patch
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'tools'))
from source_merchant_daycycle import selling_schedule, bind_sleep, source_restock_policy


def interval(activity, start, end, **fields):
    return dict(dict(activity=activity, start_minute=start, end_minute=end), **fields)


SELLING = interval('work', 449, 1229, behavior=dict(tree_file='final/sa_shop2.xml', tree_name='merchant'))
NIGHT = [interval('sleep', 0, 449, reason='No source activity link'),
         interval('sleep', 1229, 1440, reason='No source activity link')]


class SellingScheduleTests(unittest.TestCase):
    def test_unlinked_home_night_leaves_the_selling_hours_resolved(self):
        schedule = dict(person='keeper', resolved=[SELLING], pending=list(NIGHT))
        result = selling_schedule(schedule)
        self.assertEqual(result['pending'], [])
        self.assertEqual(result['resolved'], [SELLING])
        self.assertEqual([(e['start_minute'], e['end_minute']) for e in result['home_sleep']], [(0, 449), (1229, 1440)])
        # The planner report itself is not edited.
        self.assertEqual(len(schedule['pending']), 2)
        self.assertNotIn('home_sleep', schedule)

    def test_all_day_seller_is_unchanged(self):
        schedule = dict(person='keeper', resolved=[interval('work', 0, 1440)], pending=[])
        self.assertIs(selling_schedule(schedule), schedule)

    def test_any_other_unconverted_activity_stays_pending(self):
        # Rattay keepers also have a morning or an evening out; those need their own adapters.
        for activity in ('morning', 'fun', 'eat'):
            schedule = dict(person='keeper', resolved=[SELLING],
                            pending=NIGHT+[interval(activity, 400, 449, reason='No source activity link')])
            self.assertIs(selling_schedule(schedule), schedule)
            self.assertNotIn('home_sleep', selling_schedule(schedule))

    def test_a_linked_but_undispatched_sleep_is_not_a_home_night(self):
        pending = [interval('sleep', 0, 449, reason='Activity link selection requires contextual dispatch')]
        schedule = dict(person='keeper', resolved=[SELLING], pending=pending)
        self.assertIs(selling_schedule(schedule), schedule)

    def test_a_night_without_any_selling_activity_is_not_accepted(self):
        schedule = dict(person='keeper', resolved=[], pending=list(NIGHT))
        self.assertIs(selling_schedule(schedule), schedule)


class RestockPolicyTests(unittest.TestCase):
    def test_daily_source_stock_is_kept_and_weekday_masks_use_the_native_period(self):
        self.assertEqual(source_restock_policy(dict(restock_day_mask='127')), 'source_daily')
        for mask in ('1', '9', '85'):
            self.assertEqual(source_restock_policy(dict(restock_day_mask=mask)), 'native_merchant')


class BindSleepTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.source = Path(self.temporary.name)
        (self.source/'Data/Levels/rataje').mkdir(parents=True)
        with zipfile.ZipFile(self.source/'Data/Levels/rataje/level.pak', 'w') as z:
            z.writestr('objects_mission0.xml', b'<Objects/>')
        self.merchant = dict(name='keeper', ai=dict(schedule=[]))

    def bind(self, reports, files=None):
        reader = MagicMock()
        reader.__enter__.return_value = reader
        updated = dict(files or {}, bound=b'yes')
        with patch('campaign_sources.RetailSourceReader', return_value=reader), \
                patch('campaign_dependency_adapters.SourceTables', return_value='tables') as tables, \
                patch('character_sleep_work.upgrade', return_value=(updated, reports)) as upgrade:
            result = bind_sleep(dict(files or {}), self.merchant, self.source, Path('target'))
        return result, upgrade, tables

    def test_only_this_keeper_goes_to_the_shared_sleep_extension(self):
        report = dict(person='keeper', clock=dict(mode='source', intervals=[(0, 449)]), beds=[dict(kind='home')])
        (files, sleep), upgrade, tables = self.bind([report], {'objects_mission0.xml': b'<Objects/>'})
        self.assertEqual(files['bound'], b'yes')
        self.assertEqual(sleep, report)
        args = upgrade.call_args.args
        self.assertEqual(args[1], {'keeper': self.merchant})
        self.assertEqual(args[3], Path('target'))
        self.assertEqual(args[4], 'tables')
        self.assertEqual(args[6], self.source)
        tables.assert_called_once()

    def test_a_keeper_without_a_converted_bed_fails_instead_of_standing_idle(self):
        for reports in ([], [dict(person='keeper', clock=dict(mode='source'), beds=[])],
                        [dict(person='other', clock=dict(mode='source'), beds=[dict(kind='home')])],
                        # A generated clock would mean the authored night was not read.
                        [dict(person='keeper', clock=dict(mode='generated_job_average'), beds=[dict(kind='home')])]):
            with self.assertRaisesRegex(ValueError, 'no converted sleep place: keeper'):
                self.bind(reports)


if __name__ == '__main__':
    unittest.main()
