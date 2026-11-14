import sys
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from character_schedule import HOME_TIME, blocking_pending, has_home
import setup_resident_population as residents


def person(*labels):
    return dict(name='someone', ai=dict(schedule=[], links=[dict(label=l, source_xml='<Entity/>') for l in labels]))


def unlinked(activity):
    return dict(activity=activity, start_minute=0, end_minute=60, reason='No source activity link')


class HomeTimeTests(unittest.TestCase):
    def test_home_time_needs_the_flag_and_a_source_home(self):
        schedule = dict(pending=[unlinked('sleep'), unlinked('eat')], resolved=[dict(activity='work')])
        resident = person('Home,owner', "Work[('Guard')]")
        self.assertEqual(len(blocking_pending(schedule, resident)), 2)            # default keeps the old rule
        self.assertEqual(blocking_pending(schedule, resident, home_time=True), [])
        self.assertEqual(len(blocking_pending(schedule, person("Work[('Guard')]"), home_time=True)), 2)

    def test_only_unlinked_generic_activities_are_home_time(self):
        resident = person('Home')
        work = unlinked('work')
        ambiguous = dict(unlinked('fun'), reason='Activity link selection requires contextual dispatch')
        schedule = dict(pending=[unlinked('Morning'), unlinked('fun'), work, ambiguous], resolved=[])
        self.assertEqual(blocking_pending(schedule, resident, home_time=True), [work, ambiguous])
        self.assertEqual(HOME_TIME, {'sleep', 'eat', 'morning', 'fun'})

    def test_home_link_is_the_first_label_token(self):
        self.assertTrue(has_home(person(' Home ,owner')))
        self.assertFalse(has_home(person('homeless', 'Work[cityWalk]', None)))


class SelectionTests(unittest.TestCase):
    def test_batch_has_no_duplicates_or_shop_keepers(self):
        self.assertEqual(residents.check_selection(), list(residents.RESIDENTS))
        self.assertEqual(len(residents.RATTAY_1), 81)

    def test_rejects_duplicates_and_keepers(self):
        with self.assertRaises(ValueError):
            residents.check_selection(('rat_ruch', 'rat_ruch'))
        with self.assertRaisesRegex(ValueError, 'rat_armorer'):
            residents.check_selection(('rat_ruch', 'rat_armorer'))

    def test_empty_selection_changes_nothing(self):
        changed, report = residents.upgrade('unused', None, None, residents=())
        self.assertEqual(changed, {})
        self.assertEqual((report['people'], report['runtime_verified']), (0, False))

    def test_profiles_and_names_are_exclusive(self):
        from profile_population_upgrade import discover
        with self.assertRaises(ValueError):
            discover(Path('unused'), 'rataje', ['q_skalitz_normal'], None, names=['rat_ruch'])


class CensusTests(unittest.TestCase):
    def row(self, **kw):
        base = dict(person='p', soul_rows=1, reserved=False, quest=False, keeper=False, home=True, blocking=[],
                    trees=[('final/sa_city.xml:CityWalk', True)], forced_workplace=False)
        return dict(base, **kw)

    def test_buckets(self):
        from resident_census import bucket, GARRISON
        self.assertEqual(bucket(self.row()), ('selected', 'work: sa_city.xml:CityWalk'))
        cases = [(dict(error='ValueError: x'), 'source data'), (dict(soul_rows=0), 'soul name has 0 soul rows'),
                 (dict(keeper=True), 'shop keeper'), (dict(reserved=True), 'registered by a quest branch'),
                 (dict(home=False), 'no KCD1 home'), (dict(blocking=['work']), 'unlinked work'),
                 (dict(trees=[]), 'no linked work'),
                 (dict(trees=[('final/sa_pub_v3.xml:PubVisitor', False)]), 'work adapter missing'),
                 (dict(trees=[(GARRISON, True)]), 'town guard')]
        for changes, reason in cases:
            kind, why = bucket(self.row(**changes))
            self.assertEqual(kind, 'residue', changes)
            self.assertTrue(why.startswith(reason), (changes, why))
        self.assertEqual(bucket(self.row(trees=[(GARRISON, True)], forced_workplace=True))[0], 'selected')
        # Quest people are placed even without a home or work; keepers never are.
        self.assertEqual(bucket(self.row(quest=True, home=False, trees=[])), ('selected', 'quest person'))
        self.assertEqual(bucket(self.row(quest=True, keeper=True))[0], 'residue')

    def test_towns_are_areas(self):
        from resident_census import town_of
        self.assertEqual(town_of((2578.0, 605.0)), 'rattay')
        self.assertEqual(town_of((937.0, 1687.0)), 'monastery')
        self.assertIsNone(town_of((0.0, 0.0)))

    def test_generated_module_round_trips(self):
        from resident_census import selection_module
        result = dict(counts={'rattay': {'selected': 2, 'no KCD1 home': 1}},
                      selected=[dict(person='rat_b', town='rattay'), dict(person='rat_a', town='rattay')])
        namespace = {}
        exec(selection_module(result), namespace)
        self.assertEqual(namespace['RESIDENTS'], {'rattay': ('rat_a', 'rat_b')})


if __name__ == '__main__':
    unittest.main()
