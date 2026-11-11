import copy
from pathlib import Path
import sys
import unittest
import xml.etree.ElementTree as E
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from campaign_quest_graph import emit_project
from campaign_quest_tracking import bind, plan
from test_campaign_quest_graph import model

A = '00000000-0000-0000-0000-000000000001'
B = '00000000-0000-0000-0000-000000000002'
SOUL = '4BD6AED3-4d8a-e72c-dae5-fcf29ec7daa1'


def tracked(condition='', min_health='0.5', category='5'):
    """Objective 4 counts ten of item A; objective 5 counts the death of one named NPC."""
    m = model()
    rows = m['tables']['quest_objective']['rows']
    rows[1]['condition'] = condition
    rows[2]['condition'] = '1'
    m['tables']['quest_tracked_asset'] = dict(rows=[
        dict(quest_id='42', objective_id='4', quest_asset_id='8', count='10', map_asset_id='26'),
        dict(quest_id='42', objective_id='5', quest_asset_id='26', count='1', map_asset_id='')])
    m['tables']['quest_item'] = dict(rows=[dict(quest_id='42', quest_asset_id='8', item_id=A,
        item_category_id=category, item_category_type_id='', item_category_subtype_id='', min_health=min_health)])
    m['tables']['quest_npc'] = dict(rows=[dict(quest_id='42', quest_asset_id='26', soul_id=SOUL,
        soul_class_id='', soul_faction_id='')])
    return m


def bindings(**changes):
    result = dict(player_asset='player', item_map={A: B}, registered_items=[B], item_categories={A: '5'},
                  soul_assets={SOUL.lower(): 'gm_soul_ales'})
    result.update(changes)
    return result


def lowered(m, b=None):
    files, _ = emit_project([m], 'Example')
    blob, report = bind(files['Example/arbitrary_quest.xml'], m, bindings() if b is None else b)
    return E.fromstring(blob), report, blob


def froms(node, port=None):
    return {e.get('From') for e in node.findall('Edge') if port is None or e.get('To') == port}


class TrackingTests(unittest.TestCase):
    def test_manual_item_objective_gains_only_the_predicate(self):
        m = tracked(); before = copy.deepcopy(m)
        root, report, _ = lowered(m)
        self.assertEqual(m, before)
        record = report['converted'][0]
        self.assertEqual((record['objective'], record['mode'], record['predicate']), ('first', 'manual', 'first_TrackedCompleted'))
        descriptor = root.find(".//Function[@Name='lowered_track_4_0_descriptor']")
        constants = {c.get('Name'): c.get('Value') for c in descriptor.findall('Constant')}
        self.assertEqual(constants, dict(ItemClass=B, Amount='10', MinimumHealth='0.5'))
        port = root.find(".//Ports/Port[@Name='first_TrackedCompleted']")
        self.assertEqual((port.get('Direction'), port.get('Type')), ('Out', 'bool'))
        output = root.find(".//Nodes/Output[@Name='Output']")
        self.assertIn('lowered_track_4_0_matches.bool', froms(output, 'first_TrackedCompleted'))
        # A source objective with an empty condition is completed by its own script or dialogue.
        state = root.find(".//State[@Name='objective_4']")
        self.assertFalse([f for f in froms(state, 'SetCompleted') if f.startswith('lowered_track_')])
        self.assertIsNone(root.find(".//ItemDescriptorTrigger[@Name='lowered_track_4_0_watch']"))
        self.assertIsNone(root.find(".//Timer[@Name='lowered_track_4_queued']"))
        self.assertFalse(report['runtime_verified'])

    def test_zero_condition_is_also_manual(self):
        _, report, _ = lowered(tracked(condition='0'))
        self.assertEqual(report['converted'][0]['mode'], 'manual')

    def test_automatic_item_objective_rechecks_amount_and_state(self):
        root, report, _ = lowered(tracked(condition='1', min_health='0', category='0'))
        self.assertEqual(report['converted'][0]['mode'], 'auto')
        descriptor = root.find(".//Function[@Name='lowered_track_4_0_descriptor']")
        self.assertIsNone(descriptor.find("Constant[@Name='MinimumHealth']"))
        watch = root.find(".//ItemDescriptorTrigger[@Name='lowered_track_4_0_watch']")
        self.assertEqual(froms(watch, 'IsActive'), {'objective_4.Started'})
        timer = root.find(".//Timer[@Name='lowered_track_4_queued']")
        self.assertEqual(froms(timer, 'SetRunning'), {'objective_4.OnStarted', 'lowered_track_4_0_watch.OnAcquire',
                                                     'lowered_track_4_0_watch.OnTargetAmountAcquire'})
        gate = root.find(".//If[@Name='lowered_track_4_complete']")
        self.assertEqual(froms(gate, 'Exec'), {'lowered_track_4_queued.OnFinished'})
        self.assertEqual(froms(root.find(".//Function[@Name='lowered_track_4_all_0']")),
                         {'objective_4.Started', 'lowered_track_4_0_matches.bool'})
        self.assertIn('lowered_track_4_complete.True', froms(root.find(".//State[@Name='objective_4']"), 'SetCompleted'))

    def test_named_npc_death_uses_death_trigger_and_persistent_latch(self):
        root, report, _ = lowered(tracked())
        record = next(r for r in report['converted'] if r['objective'] == 'second')
        self.assertEqual(record['requirements'], [dict(kind='npc_death', asset='26', source_soul=SOUL.lower(),
                                                       soul_asset='gm_soul_ales')])
        watch = root.find(".//SoulDeathTrigger[@Name='lowered_track_5_0_watch']")
        self.assertEqual(watch.find('Asset').attrib, dict(Name='Souls', Alias='gm_soul_ales'))
        self.assertEqual(froms(watch, 'IsActive'), {'objective_5.Started'})
        latch = root.find(".//State[@Name='lowered_track_5_0_dead']")
        self.assertEqual(latch.get('TypeT'), 'bool')
        self.assertEqual(froms(latch, 'SetTrue'), {'lowered_track_5_0_watch.OnAllDeath'})
        timer = root.find(".//Timer[@Name='lowered_track_5_queued']")
        self.assertEqual(froms(timer, 'SetRunning'), {'objective_5.OnStarted', 'lowered_track_5_0_dead.OnExec'})
        self.assertIn('lowered_track_5_complete.True', froms(root.find(".//State[@Name='objective_5']"), 'SetCompleted'))
        self.assertIn('lowered_track_5_0_dead.State',
                      froms(root.find(".//Nodes/Output[@Name='Output']"), 'second_TrackedCompleted'))

    def test_item_and_npc_on_one_objective_must_both_hold(self):
        m = tracked(condition='1')
        m['tables']['quest_tracked_asset']['rows'][1]['objective_id'] = '4'
        root, report, _ = lowered(m)
        self.assertEqual([q['kind'] for q in report['converted'][0]['requirements']], ['item', 'npc_death'])
        self.assertEqual(froms(root.find(".//Function[@Name='lowered_track_4_tracked_0']")),
                         {'lowered_track_4_0_matches.bool', 'lowered_track_4_1_dead.State'})

    def test_unproven_filters_and_selectors_stay_pending(self):
        cases = dict(
            category=lambda m, b: b.update(item_categories={A: '4'}),
            no_category_evidence=lambda m, b: b.update(item_categories={}),
            item_type=lambda m, b: m['tables']['quest_item']['rows'][0].update(item_category_type_id='3'),
            classless=lambda m, b: m['tables']['quest_item']['rows'][0].update(item_id=''),
            health=lambda m, b: m['tables']['quest_item']['rows'][0].update(min_health='1.5'),
            unmapped=lambda m, b: b.update(item_map={}),
            expression=lambda m, b: m['tables']['quest_objective']['rows'][1].update(condition='HasTalked()'),
            timeout=lambda m, b: m['tables']['quest_objective']['rows'][1].update(autocomplete_timeout_str='5s #GT'),
            expiration=lambda m, b: m['tables']['quest_objective']['rows'][1].update(expiration_timeout_str='5s #GT'))
        for name, change in cases.items():
            with self.subTest(name=name):
                m, b = tracked(), bindings()
                change(m, b)
                report = plan(m, b)
                self.assertEqual([p['objective'] for p in report['pending']], ['first'])
                self.assertEqual([c['objective'] for c in report['converted']], ['second'])
        cases = dict(
            unregistered=lambda m, b: b.update(soul_assets={}),
            soul_class=lambda m, b: m['tables']['quest_npc']['rows'][0].update(soul_class_id='7'),
            faction=lambda m, b: m['tables']['quest_npc']['rows'][0].update(soul_faction_id='27'),
            count=lambda m, b: m['tables']['quest_tracked_asset']['rows'][1].update(count='2'))
        for name, change in cases.items():
            with self.subTest(name=name):
                m, b = tracked(), bindings()
                change(m, b)
                self.assertEqual([p['objective'] for p in plan(m, b)['pending']], ['second'])

    def test_place_and_unknown_assets_stay_pending(self):
        m = tracked()
        m['tables']['quest_place'] = dict(rows=[dict(quest_id='42', quest_asset_id='54', entity='area', map='')])
        m['tables']['quest_tracked_asset']['rows'] = [
            dict(quest_id='42', objective_id='4', quest_asset_id='54', count='1', map_asset_id=''),
            dict(quest_id='42', objective_id='5', quest_asset_id='99', count='1', map_asset_id='')]
        report = plan(m, bindings())
        self.assertFalse(report['converted'])
        self.assertIn('place tracking requires a spatial adapter 54', report['pending'][0]['reasons'])
        self.assertIn('unknown asset kind 99', report['pending'][1]['reasons'])

    def test_markers_are_presentation_and_never_completion(self):
        m = tracked()
        m['tables']['quest_tracked_asset']['rows'] = [
            dict(quest_id='42', objective_id='4', quest_asset_id='', count='1', map_asset_id='26'),
            dict(quest_id='42', objective_id='5', quest_asset_id='26', count='0', map_asset_id='')]
        report = plan(m, bindings())
        self.assertEqual([p['objective'] for p in report['presentation']], ['first'])
        # Objective 5 is constant-true with nothing to count: immediate completion would be a guess.
        self.assertEqual([p['objective'] for p in report['pending']], ['second'])
        files, _ = emit_project([m], 'Example')
        blob, _ = bind(files['Example/arbitrary_quest.xml'], m, bindings())
        self.assertEqual(blob, files['Example/arbitrary_quest.xml'])

    def test_targets_must_be_registered_and_binding_is_single_use(self):
        with self.assertRaisesRegex(ValueError, 'Unregistered target item'):
            plan(tracked(), bindings(registered_items=[]))
        with self.assertRaisesRegex(ValueError, 'Invalid native identifier'):
            plan(tracked(), bindings(soul_assets={SOUL: 'not an alias'}))
        m = tracked()
        _, _, blob = lowered(m)
        with self.assertRaisesRegex(ValueError, 'already lowered'):
            bind(blob, m, bindings())
        m['tables']['quest_tracked_asset']['rows'][0]['objective_id'] = '99'
        with self.assertRaisesRegex(ValueError, 'Unknown tracked objective'):
            plan(m, bindings())

    def test_objectives_completed_by_quest_items_are_left_to_it(self):
        from campaign_quest_items import bind as bind_items
        m = tracked(condition='1', min_health='0', category='0')
        files, _ = emit_project([m], 'Example')
        blob, _ = bind_items(files['Example/arbitrary_quest.xml'], m, {A: B}, [B], 'player')
        blob, report = bind(blob, m, bindings())
        root = E.fromstring(blob)
        self.assertEqual(report['bound_by_quest_items'], [dict(objective_id='4', objective='first')])
        self.assertEqual([c['objective'] for c in report['converted']], ['second'])
        self.assertIsNone(root.find(".//Function[@Name='lowered_track_4_0_descriptor']"))
        self.assertEqual(froms(root.find(".//State[@Name='objective_4']"), 'SetCompleted'),
                         {'complete_first', 'tracked_items_4_complete.True'})


if __name__ == '__main__': unittest.main()
