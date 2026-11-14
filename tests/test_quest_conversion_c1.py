"""Converter C1 (objectives): place tracking, function conditions, the residue
ledger, the source-equivalence checker and the q_skalitz golden fixture.

The checker tests are mutation tests: a correct conversion must pass, and each
deliberately broken copy must FAIL in the category that owns the damage.
"""
import copy
import json
import os
from pathlib import Path
import sys
import unittest
import xml.etree.ElementTree as E
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from campaign_quest_graph import emit_project
from campaign_quest_lowerings import lower
import campaign_quest_conditions
import quest_conversion_ledger as ledger
import quest_source_equivalence as equivalence
import test_campaign_quest_lowerings as base

FIXTURES = Path(__file__).resolve().parent / 'fixtures' / 'quest_conversion'
KCD1 = Path(os.environ.get('GLUEMAPPER_KCD1', 'D:/SteamLibrary/steamapps/common/KingdomComeDeliverance'))
KCD2 = Path(os.environ.get('GLUEMAPPER_KCD2', 'D:/SteamLibrary/steamapps/common/KingdomComeDeliverance2'))
RETAIL = (KCD1 / 'Data/Tables.pak').is_file() and (KCD2 / 'Data/Tables.pak').is_file()
PATH = 'Example/arbitrary_quest.xml'
FUNCTIONS = {'example_firstDone': "IsObjectiveCompleted('arbitrary_quest','first')"}


def source():
    """base.source() plus a place-tracked objective (3) and a function condition (7)."""
    m = base.source()
    rows = m['tables']['quest_objective']['rows']
    rows[0]['condition'] = '1'
    rows[4]['condition'] = 'example_firstDone'
    m['tables']['quest_tracked_asset']['rows'].append(
        dict(quest_id='42', objective_id='3', quest_asset_id='90', count='1', map_asset_id=''))
    m['tables']['quest_place'] = dict(rows=[dict(quest_id='42', quest_asset_id='90', entity='example_area',
                                                 map='', show_as_area='False')])
    return m


def bindings(**changes):
    result = base.bindings(condition_functions=FUNCTIONS,
                           place_assets={'example_area': dict(alias='gm_place_example_area', entity_class='TriggerArea')})
    result.update(changes)
    return result


def converted(m=None, b=None):
    m = m or source()
    b = bindings() if b is None else b
    files, emitted = emit_project([m], 'Example')
    files, report = lower(files, emitted, [m], b)
    return m, b, files, emitted, report


def check(m, b, files, report, blob=None, quest=None):
    return equivalence.check(m, blob or files[PATH], quest or report['quests'][0], b, files['Example.xml'])


def mutate(files, change):
    root = E.fromstring(files[PATH])
    change(root.find('./Skald/Quest'), root.find('./Skald/Quest/Nodes'))
    return E.tostring(root)


def failed(result):
    return sorted({f['category'] for f in result['failures']})


class PlaceTrackingTests(unittest.TestCase):
    def test_registered_trigger_area_becomes_a_presence_latch(self):
        m, b, files, emitted, report = converted()
        quest = report['quests'][0]
        self.assertEqual(quest['unsupported'], [])
        nodes = E.fromstring(files[PATH]).find('./Skald/Quest/Nodes')
        watch = nodes.find("AreaTrigger[@Name='lowered_track_3_0_watch']")
        self.assertEqual({a.get('Name'): a.get('Alias') for a in watch.findall('Asset')},
                         dict(Souls='player', Areas='gm_place_example_area'))
        self.assertEqual([(e.get('From'), e.get('To')) for e in watch.findall('Edge')], [('quest_progress.Active', 'IsActive')])
        latch = nodes.find("State[@Name='lowered_track_3_0_inside']")
        self.assertEqual(sorted((e.get('From'), e.get('To')) for e in latch.findall('Edge')),
                         [('lowered_track_3_0_watch.OnEnter', 'SetTrue'), ('lowered_track_3_0_watch.OnLeave', 'SetFalse')])
        record = next(r for r in quest['lowerings']['tracking']['converted'] if r['objective_id'] == '3')
        self.assertFalse(record['requirements'][0]['initial_presence_verified'])
        self.assertEqual(ledger.build(m, emitted['quests'][0], quest, check(m, b, files, report))['world_requirements'],
                         [dict(kind='TriggerArea', source_entity='example_area', asset='gm_place_example_area')])

    def test_a_place_stays_pending_without_an_area(self):
        cases = [(None, 'place tracking requires a spatial adapter 90', 'place_unresolved'),
                 ({}, 'unregistered place example_area', 'place_unresolved'),
                 ({'example_area': dict(alias='gm_x', entity_class='TagPoint')},
                  'place without an area (TagPoint) example_area', 'place_without_area')]
        for places, reason, kind in cases:
            b = bindings()
            if places is None: del b['place_assets']
            else: b['place_assets'] = places
            m, b, files, emitted, report = converted(b=b)
            quest = report['quests'][0]
            self.assertEqual(quest['lowerings']['tracking']['pending'][0]['reasons'], [reason])
            self.assertEqual(sorted(r['kind'] for r in quest['unsupported']), ['completion_policy', 'tracked_completion'])
            self.assertIsNone(E.fromstring(files[PATH]).find('.//AreaTrigger'))
            result = check(m, b, files, report)
            self.assertEqual((result['verdict'], result['summary']['residue']), ('PASS', 1), result['failures'])
            built = ledger.build(m, emitted['quests'][0], quest, result)
            self.assertEqual({k for r in built['residue'] for k in r['residue_kinds']}, {kind})


class FunctionConditionTests(unittest.TestCase):
    def test_a_named_function_is_expanded_and_bound_like_a_written_condition(self):
        m, b, files, emitted, report = converted()
        quest = report['quests'][0]
        self.assertEqual(quest['lowerings']['conditions']['converted'][0]['functions'], ['example_firstDone'])
        self.assertIn(('completion_policy', 'disabled', 'campaign_quest_conditions'),
                      [(r['kind'], r.get('objective'), r['by']) for r in quest['lowerings']['resolved']])
        written = source()
        written['tables']['quest_objective']['rows'][4]['condition'] = '(' + FUNCTIONS['example_firstDone'] + ')'
        # Same nodes as the emitter writes for the written-out expression; only their position differs.
        def canonical(blob):
            return sorted(E.tostring(n) for n in E.fromstring(blob).find('./Skald/Quest/Nodes'))
        self.assertEqual(canonical(converted(written)[2][PATH]), canonical(files[PATH]))

    def test_an_undefined_name_is_residue_and_emits_nothing(self):
        m, b, files, emitted, report = converted(b=bindings(condition_functions={}))
        quest = report['quests'][0]
        self.assertEqual(quest['lowerings']['conditions']['pending'][0]['reason'], 'undefined condition name: example_firstDone')
        self.assertEqual([r['kind'] for r in quest['unsupported']], ['completion_policy'])
        self.assertIsNone(E.fromstring(files[PATH]).find(".//Timer[@Name='source_condition_7']"))
        built = ledger.build(m, emitted['quests'][0], quest, check(m, b, files, report))
        self.assertEqual(built['residue'][0]['residue_kinds'], ['undefined_condition_name'])

    def test_lowering_twice_is_refused(self):
        m, b, files, emitted, report = converted()
        with self.assertRaisesRegex(ValueError, 'already lowered'):
            campaign_quest_conditions.bind(files[PATH], m, b)


class EquivalenceTests(unittest.TestCase):
    def setUp(self):
        self.m, self.b, self.files, self.emitted, self.report = converted()

    def result(self, change=None, quest=None, m=None, b=None):
        blob = mutate(self.files, change) if change else None
        return check(m or self.m, b or self.b, self.files, self.report, blob, quest)

    def test_a_correct_conversion_passes_every_category(self):
        result = self.result()
        self.assertEqual(result['verdict'], 'PASS', result['failures'])
        self.assertEqual(result['summary']['failed'], 0)
        self.assertEqual(sorted(result['categories']),
                         ['completion', 'objectives', 'quest_end', 'references', 'rewards', 'transitions'])
        self.assertEqual(result['summary']['checked'], result['summary']['passed'] + result['summary']['residue'])

    def test_a_missing_or_reordered_objective_fails(self):
        self.assertIn('objectives', failed(self.result(lambda q, n: n.remove(n.find("State[@Name='objective_7']")))))
        def reorder(q, n):
            state = n.find("State[@Name='objective_4']"); n.remove(state); n.append(state)
        self.assertEqual(failed(self.result(reorder)), ['objectives'])
        def unhide(q, n): E.SubElement(q.find('Objectives'), 'Objective', Name='intro')
        self.assertEqual(failed(self.result(unhide)), ['objectives'])

    def test_a_changed_transition_fails(self):
        def drop(q, n):
            gate = n.find("If[@Name='advance_6']")
            gate.remove(next(e for e in gate.findall('Edge') if e.get('From') == 'objective_5.OnCompleted'))
        self.assertEqual(failed(self.result(drop)), ['transitions'])
        def any_instead_of_all(q, n):
            n.find("Function[@Name='ready_6_predecessors_0']").set('MethodName', 'math::boolean::Or')
        self.assertEqual(failed(self.result(any_instead_of_all)), ['transitions'])
        def invented(q, n):
            E.SubElement(n.find("State[@Name='objective_7']"), 'Edge', From='advance_6.True', To='SetStarted')
        self.assertEqual(failed(self.result(invented)), ['transitions'])
        def end(q, n):
            timer = n.find("Timer[@Name='quest_end_2_queued']")
            next(e for e in timer.findall('Edge') if e.get('To') == 'SetRunning').set('From', 'objective_4.OnCompleted')
        self.assertEqual(failed(self.result(end)), ['quest_end'])

    def test_a_changed_completion_fails(self):
        def wrong_clock(q, n):
            timer = n.find("Timer[@Name='lowered_policy_6_timer']")
            next(c for c in timer.findall('Constant') if c.get('Name') == 'Duration').set('Value', '3h')
        self.assertEqual(failed(self.result(wrong_clock)), ['completion'])
        def invented(q, n):
            E.SubElement(n.find("State[@Name='objective_4']"), 'Edge', From='advance_6.True', To='SetCompleted')
        self.assertEqual(failed(self.result(invented)), ['completion'])
        def fewer_assets(q, n):
            for node in [x for x in n if x.get('Name', '').startswith('lowered_track_3_0_')]: n.remove(node)
        self.assertIn('completion', failed(self.result(fewer_assets)))

    def test_a_record_must_be_converted_or_residue_never_both_or_neither(self):
        # Neither: the place is not lowered, and its residue records are withheld.
        b = bindings(); del b['place_assets']
        m, b, files, emitted, report = converted(b=b)
        quest = dict(report['quests'][0], unsupported=[])
        self.assertEqual(failed(check(m, b, files, report, quest=quest)), ['completion'])
        # Both: converted, but a residue record still claims it.
        quest = dict(self.report['quests'][0], unsupported=[dict(kind='completion_policy', objective='returnHome')])
        result = self.result(quest=quest)
        self.assertEqual(failed(result), ['completion'])
        self.assertIn('converted and still reported as residue', result['failures'][0]['detail'])

    def test_a_dropped_reward_or_unresolved_reference_fails(self):
        def drop_reward(q, n):
            rewards = n.find("AddReward[@Name='lowered_reward_4']/Rewards"); rewards.remove(rewards[0])
        self.assertEqual(failed(self.result(drop_reward)), ['rewards'])
        self.assertEqual(failed(self.result(b=dict(self.b, place_assets={}))), ['references'])
        self.assertEqual(failed(self.result(b=dict(self.b, registered_items=[]))), ['references'])
        def dangling(q, n):
            E.SubElement(n.find("State[@Name='objective_4']"), 'Edge', From='nothing.Out', To='SetFailed')
        self.assertEqual(failed(self.result(dangling)), ['references'])

    def test_the_source_side_is_derived_from_the_tables_not_the_report(self):
        changed = copy.deepcopy(self.m)
        changed['tables']['quest_objective']['rows'][3]['autocomplete_timeout_str'] = '5h #WT'
        self.assertEqual(failed(self.result(m=changed)), ['completion'])
        changed = copy.deepcopy(self.m)
        changed['tables']['quest_transition']['rows'][5]['enabled'] = 'True'
        self.assertEqual(failed(self.result(m=changed)), ['transitions'])


class LedgerTests(unittest.TestCase):
    def test_counts_and_every_residue_reason_is_typed(self):
        m, b, files, emitted, report = converted()
        built = ledger.build(m, emitted['quests'][0], report['quests'][0], check(m, b, files, report))
        self.assertEqual((built['counts']['before_total'], built['counts']['after_total']), (9, 0))
        self.assertEqual(built['source']['objectives'], 5)
        self.assertEqual(built['layers']['source_equivalence']['verdict'], 'PASS')
        self.assertFalse(built['runtime_verified'])
        self.assertEqual(ledger.residue_kind('something new'), 'unclassified')
        for reason, kind in [('timeout without a named clock: 15s', 'timeout_clock_unnamed'),
                             ('expiration timeout', 'expiration_semantics'),
                             ('timeout without a constant-true condition', 'timeout_on_expression'),
                             ('item asset without a class 7', 'category_only_item')]:
            self.assertEqual(ledger.residue_kind(reason), kind)

    def test_walk_spec_lists_the_source_sequence_and_what_a_walk_must_supply(self):
        spec = ledger.walk_spec(source())
        self.assertEqual([s['objective'] for s in spec['main_path']], ['intro', 'first', 'second', 'returnHome'])
        self.assertEqual([s['objective'] for s in spec['off_path']], ['disabled'])
        self.assertEqual(spec['main_path'][3]['started_by'], dict(join='all', after=['first', 'second']))
        self.assertEqual((spec['main_path'][3]['completion'], spec['main_path'][3]['duration'], spec['main_path'][3]['clock']),
                         ('timed', '2h', 'WorldTime'))
        self.assertEqual(spec['expected_end_states'], ['returnHome'])
        self.assertEqual(spec['outcomes_the_walk_must_supply'], ['first'])

    def test_golden_changes_when_the_output_changes(self):
        m, b, files, emitted, report = converted()
        built = ledger.build(m, emitted['quests'][0], report['quests'][0], check(m, b, files, report))
        first = ledger.golden(built, files[PATH])
        self.assertEqual(first, ledger.golden(built, files[PATH].replace(b'\n', b'\r\n')))
        changed = mutate(files, lambda q, n: n.find("Timer[@Name='lowered_policy_6_timer']").set('Name', 'renamed'))
        self.assertNotEqual(first['emitted_sha256'], ledger.golden(built, changed)['emitted_sha256'])
        self.assertNotEqual(first['lowered_nodes'], ledger.golden(built, changed)['lowered_nodes'])


@unittest.skipUnless(RETAIL, 'requires installed retail KCD1 and KCD2 tables')
class RetailTests(unittest.TestCase):
    """Layers 1 and 3 on the real quests. Fixtures hold hashes and counts, no source text."""
    @classmethod
    def setUpClass(cls):
        cls.run_ = ledger.convert(KCD1, KCD2, ['q_skalitz', 'a_huntsman_alex', 'a_huntsman_butcher'])
        cls.ledgers = {l['quest']: l for l in cls.run_['ledgers']}

    def test_source_equivalence_passes(self):
        for name, built in self.ledgers.items():
            layer = built['layers']['source_equivalence']
            self.assertEqual((layer['verdict'], layer['failures']), ('PASS', []), name)
            self.assertNotIn('unclassified', built['counts']['after_by_residue_kind'], name)

    def test_q_skalitz_matches_its_golden_fixture(self):
        blob = self.run_['files'][self.run_['project'] + '/q_skalitz.xml']
        current = json.loads(json.dumps(ledger.golden(self.ledgers['q_skalitz'], blob), sort_keys=True, default=str))
        self.assertEqual(current, json.loads((FIXTURES / 'q_skalitz.c1.golden.json').read_text(encoding='utf-8')))

    def test_q_skalitz_walk_spec_matches_its_fixture(self):
        model = next(m for m in self.run_['models'] if m['quest'] == 'q_skalitz')
        self.assertEqual(json.loads(json.dumps(ledger.walk_spec(model), sort_keys=True)),
                         json.loads((FIXTURES / 'q_skalitz.walk.json').read_text(encoding='utf-8')))


if __name__ == '__main__': unittest.main()
