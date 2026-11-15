import sys
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
import garrison_census as census
import garrison_posts as posts
import setup_garrison_population as stage


def workplace(name, order, pos, kind='guardPlace', important=False, disabled=False):
    return dict(name=name, kcd1_order=order, pos=list(pos), kind=kind, important=important,
                disabled=disabled, workplace_name=name, entity_guid=name.upper(), equipment='halberd', patrol=None)


def guard(name, start, end, home=(0, 0, 0)):
    """A guard whose daycycle is sleep, then work from start to end (minutes)."""
    return dict(soul_name=name, daycycle=[dict(activity='sleep', start=end), dict(activity='work', start=start)],
                home=dict(pos=list(home)), pos=list(home))


GARRISON = dict(name='sa_test', pos=[0, 0, 0], idle_benches=[], inside=[dict(pos=[50, 0, 0])],
                workplaces=[workplace('gate', 0, (0, 0, 0), important=True), workplace('wall', 1, (100, 0, 0))])


class AllocatorRuleTests(unittest.TestCase):
    """KCD1 sa_garrison.xml onUpdate: first free workplace in list order to the nearest available guard."""

    def test_first_post_goes_to_the_nearest_guard_and_is_held_for_the_shift(self):
        guards = [guard('far', 480, 1200, home=(90, 0, 0)), guard('near', 480, 1200, home=(5, 0, 0))]
        result = census.simulate(GARRISON, guards, {})
        self.assertEqual(result['method'], 'exact_periodic')
        self.assertEqual(result['per_guard']['near']['primary_post'], 'gate')
        self.assertEqual(result['per_guard']['far']['primary_post'], 'wall')
        self.assertEqual(result['per_guard']['near']['segments'],
                         [dict(start_minute=480, end_minute=1200, post='gate', start='08:00', end='20:00')])

    def test_a_guard_beyond_the_posts_stays_in_reserve(self):
        guards = [guard(n, 480, 1200, home=(i, 0, 0)) for i, n in enumerate(('a', 'b', 'c'))]
        result = census.simulate(GARRISON, guards, {})
        self.assertEqual(sorted(g['primary_post'] or '-' for g in result['per_guard'].values()), ['-', 'gate', 'wall'])

    def test_disabled_posts_are_skipped_until_a_quest_enables_them(self):
        garrison = dict(GARRISON, workplaces=[workplace('gate', 0, (0, 0, 0), disabled=True), workplace('wall', 1, (100, 0, 0))])
        guards = [guard('only', 480, 1200)]
        self.assertEqual(census.simulate(garrison, guards, {})['per_guard']['only']['primary_post'], 'wall')
        self.assertEqual(census.simulate(garrison, guards, {}, ['gate'])['per_guard']['only']['primary_post'], 'gate')

    def test_incoming_guard_waits_idle_until_relieved(self):
        guards = [guard('night', 1200, 540), guard('day', 480, 1200), guard('day2', 480, 1200)]
        result = census.simulate(dict(GARRISON, workplaces=GARRISON['workplaces'][:1]), guards, {})
        day = [g for g in ('day', 'day2') if result['per_guard'][g]['primary_post'] == 'gate']
        self.assertEqual(len(day), 1)
        segments = result['per_guard'][day[0]]['segments']
        self.assertEqual((segments[0]['post'], segments[0]['start'], segments[0]['end']), (None, '08:00', '09:00'))
        self.assertEqual(segments[1]['post'], 'gate')


class WorkClockTests(unittest.TestCase):
    def test_overnight_work_interval(self):
        schedule = [dict(activity='sleep', start_minute=540), dict(activity='work', start_minute=1228)]
        self.assertEqual(posts.work_intervals(schedule), [['20:28', '09:00']])

    def test_verifier_spans_wrap_midnight_and_detect_post_clashes(self):
        import verify_garrison as v
        night, day = v.span('20:28', '09:00'), v.span('09:00', '20:28')
        self.assertEqual(night, (1228, 1980))
        self.assertFalse(v.overlaps(night, day))                       # relief at 09:00 is not a clash
        self.assertTrue(v.overlaps(night, v.span('08:30', '12:00')))   # the morning guard arrives early
        self.assertTrue(v.overlaps(v.span('23:00', '01:00'), v.span('00:30', '02:00')))

    def test_verifier_folds_overnight_scheduler_windows_onto_one_day(self):
        import verify_garrison as v
        kcd1 = v.merge_day([v.span('20:28', '08:58')])
        self.assertEqual(kcd1, [(0, 538), (1228, 1440)])
        self.assertEqual(v.merge_day([(0, 538), (1228, 1440)]), kcd1)       # the scheduler's two links
        self.assertNotEqual(v.merge_day([(0, 530), (1228, 1440)]), kcd1)    # eight minutes short is a mismatch
        self.assertEqual(v.merge_day([v.span('08:00', '20:00')]), [(480, 1200)])


def mission(*entities):
    by_id, by_guid = {}, {}
    for e in entities:
        by_id[e.get('EntityId')] = e
        by_guid.setdefault(e.get('EntityGuid').upper(), []).append(e)
    return by_id, by_guid


def tagpoint(name, guid, pos, entity_id='7'):
    return ET.fromstring(f'<Entity Name="{name}" EntityClass="TagPoint" EntityId="{entity_id}" '
                         f'EntityGuid="{guid}" Pos="{pos}" Rotate="1,0,0,0"/>')


def captured(work='08:00', end='20:00', faction='46', extra_links=()):
    h, m = map(int, work.split(':')); eh, em = map(int, end.split(':'))
    return dict(soul=dict(soul_id='soul-1'), ai=dict(
        faction_graph=dict(faction=dict(faction_id=faction)),
        schedule=[dict(activity='work', start_minute=h * 60 + m), dict(activity='sleep', start_minute=eh * 60 + em)],
        links=[dict(label="Work[('Guard')]", target=dict(Name='sa_test', EntityGuid='AREA1'))] + list(extra_links)))


def record(**changes):
    base = dict(soul_id='soul-1', faction_id='46', garrison='sa_test', garrison_guid='area1', state='authored',
                method='exact_periodic', shift='day', work=[['08:00', '20:00']], segments=[['08:00', '20:00', 'tp_gate']],
                role='posted', post='tp_gate', post_guid='POST1', post_pos=[10.0, 20.0, 30.0], post_kind='guardPlace',
                kcd1_order=0, important=True, equipment='halberd', patrol=None, home='house', bed='bed1')
    base.update(changes)
    return base


class PostTests(unittest.TestCase):
    def setUp(self):
        self.mission = mission(tagpoint('tp_gate', 'POST1', '10,20,30'))

    def test_posted_guard_gets_the_census_post_as_its_forced_workplace(self):
        people = {'g': captured()}
        report = posts.apply(people, None, {'g': record()}, mission=self.mission)
        forced = [l for l in people['g']['ai']['links'] if l['label'] == posts.FORCED]
        self.assertEqual(len(forced), 1)
        self.assertEqual(ET.fromstring(forced[0]['source_xml']).get('Name'), 'tp_gate')
        self.assertEqual(forced[0]['garrison']['post_kind'], 'guardPlace')
        self.assertEqual(report[0]['pending'], [])

    def test_patrol_guard_is_reported_pending_its_route(self):
        people = {'g': captured()}
        rec = record(post_kind='patrolWalls', patrol=dict(type='ping_pong_chain', points=['POST1', 'P2']))
        report = posts.apply(people, None, {'g': rec}, mission=self.mission)
        self.assertEqual(report[0]['patrol_points'], 2)
        self.assertTrue(report[0]['pending'][0].startswith('patrol route'))

    def test_reserve_guard_gets_no_post(self):
        people = {'g': captured()}
        report = posts.apply(people, None, {'g': record(role='reserve', post=None, post_guid=None, post_kind=None)},
                             mission=self.mission)
        self.assertFalse(any(l['label'] == posts.FORCED for l in people['g']['ai']['links']))
        self.assertTrue(report[0]['pending'][0].startswith('reserve'))

    def test_any_source_difference_refuses_the_garrison(self):
        cases = [(captured(faction='27'), record(), 'faction'),
                 (captured(work='09:00'), record(), 'work clock'),
                 (captured(), record(post_pos=[11.0, 20.0, 30.0]), 'post tp_gate at'),
                 (captured(), record(post_guid='MISSING'), 'matches 0'),
                 (captured(), record(garrison='sa_other'), 'Work link'),
                 (captured(extra_links=[dict(label=posts.FORCED, target={})]), record(), 'authored')]
        for person, rec, message in cases:
            with self.subTest(message), self.assertRaisesRegex(ValueError, message):
                posts.apply({'g': person}, None, {'g': rec}, mission=self.mission)

    def test_people_outside_the_selection_are_untouched(self):
        people = {'resident': captured()}
        self.assertEqual(posts.apply(people, None, {'g': record()}, mission=self.mission), [])
        self.assertEqual(len(people['resident']['ai']['links']), 1)


class SelectionTests(unittest.TestCase):
    def test_a_guard_selected_as_resident_is_refused(self):
        import resident_selection
        with patch.object(resident_selection, 'RESIDENTS', {'rattay': ('rat_guard2',)}):
            with self.assertRaisesRegex(ValueError, 'rat_guard2'):
                stage.check_selection({'rat_guard2': {}, 'rat_guard3': {}})
            self.assertEqual(stage.check_selection({'rat_guard3': {}}), ['rat_guard3'])

    def test_census_routes_selected_guards_to_the_garrison_stage(self):
        import resident_census
        row = dict(person='rat_guard2', soul_rows=1, keeper=False, reserved=False, quest=False, home=False,
                   blocking=[], trees=[(resident_census.GARRISON, True)], forced_workplace=False)
        self.assertEqual(resident_census.bucket(row), ('residue', 'town guard: garrison stage (setup_garrison_population)'))
        self.assertEqual(resident_census.bucket(dict(row, person='tal_guard1', home=True))[1],
                         'town guard: garrison allocator missing')

    def test_quest_and_other_route_guards_are_out_of_scope(self):
        row = dict(soul_name='rat_guard2', forced_workplace=[])
        self.assertTrue(census.in_scope(row))
        for name in ('rat_guardJanik', 'rat_guardJanek', 'rat_guardJaroslav'):
            self.assertFalse(census.in_scope(dict(row, soul_name=name)))
        self.assertFalse(census.in_scope(dict(row, forced_workplace=['tp_x'])))


# Golden: Rattay's frozen garrison day (garrison_census on retail KCD1, 2026-11-14).
# Per guard: garrison, shift, post (None = reserve). Regenerating the census must
# reproduce this unless KCD1 data or the allocator replay changed on purpose.
RATTAY = {
    'rat_guard10': ('sa_rat_garrison', 'day', 'tp_primary5'),
    'rat_guard11': ('sa_rat_garrison', 'night', 'tp_primary3'),
    'rat_guard2': ('sa_rat_garrison', 'day', 'tp_primary1'),
    'rat_guard_pazdera': ('sa_rat_garrison', 'day', None),
    'rat_upper_guard1': ('rat_upper_garrison', 'night', 'rat_upper_insidePrimary'),
    'rat_pirk_guard8': ('sa_pirk_garrison', 'day', 'tp_rat_pirk_patrol_start'),
}


class RattayGoldenTests(unittest.TestCase):
    def setUp(self):
        from garrison_selection import GUARDS
        self.guards = GUARDS

    def test_every_rattay_town_guard_is_selected_once(self):
        expected = ({f'rat_guard{i}' for i in range(2, 28) if i != 20} | {'rat_guard_pazdera'}
                    | {f'rat_pirk_guard{i}' for i in range(1, 11)} | {f'rat_upper_guard{i}' for i in range(1, 17)})
        self.assertEqual(set(self.guards), expected)

    def test_golden_posts(self):
        for name, (garrison, shift, post) in RATTAY.items():
            with self.subTest(name):
                g = self.guards[name]
                self.assertEqual((g['garrison'], g['shift'], g['post']), (garrison, shift, post))

    def test_no_two_guards_share_a_post_at_the_same_time(self):
        def span(a, b):
            start = int(a[:2]) * 60 + int(a[3:]); end = int(b[:2]) * 60 + int(b[3:])
            return start, end if end > start else end + 1440
        held = {}
        for name, g in self.guards.items():
            for a, b, post in g['segments']:
                if post != 'idle':
                    held.setdefault(post, []).append((span(a, b), name))
        for post, rows in held.items():
            for i, ((s1, e1), n1) in enumerate(rows):
                for (s2, e2), n2 in rows[i + 1:]:
                    clash = any(s1 + d < e2 and s2 < e1 + d for d in (-1440, 0, 1440))
                    self.assertFalse(clash, f'{post}: {n1} and {n2}')

    def test_counts(self):
        kinds = {}
        for g in self.guards.values():
            kinds[g['post_kind']] = kinds.get(g['post_kind'], 0) + 1
        self.assertEqual(kinds, {'guardPlace': 31, 'patrolStreets': 11, 'patrolWalls': 9, None: 1})


if __name__ == '__main__':
    unittest.main()
