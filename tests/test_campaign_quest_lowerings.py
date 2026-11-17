import copy
from pathlib import Path
import sys
import unittest
import xml.etree.ElementTree as E
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from campaign_quest_graph import emit_project
from campaign_quest_lowerings import enable_tracked_predicate, lower
import test_campaign_quest_rewards as rewards
import test_campaign_quest_tracking as tracking


def source():
    """Tracked item hand-in, an NPC-death guard, a timed objective and objective rewards."""
    m = tracking.tracked()
    m['tables'].update({k: v for k, v in rewards.rewarded()['tables'].items() if k.startswith('quest_reward')})
    m['tables']['quest_objective']['rows'][3].update(condition='1', autocomplete_timeout_str='2h #WT')
    return m


def bindings(**changes):
    result = dict(rewards.bindings(), **{k: v for k, v in tracking.bindings().items() if k != 'soul_assets'})
    result.update(changes)
    return result


def kinds(quest):
    return sorted(r['kind'] for r in quest['unsupported'])


class LoweringTests(unittest.TestCase):
    def test_fully_bound_quest_reports_nothing_unsupported(self):
        m = source()
        files, report = emit_project([m], 'Example')
        before_files, before_report, before_model = dict(files), copy.deepcopy(report), copy.deepcopy(m)
        self.assertEqual(kinds(report['quests'][0]), ['completion_policy', 'completion_policy', 'rewards', 'rewards',
                                                      'tracked_completion', 'tracked_completion'])
        lowered_files, lowered = lower(files, report, [m], bindings())
        self.assertEqual((files, report, m), (before_files, before_report, before_model))
        quest = lowered['quests'][0]
        self.assertEqual(quest['unsupported'], [])
        self.assertEqual((quest['lowerings']['unsupported_before'], quest['lowerings']['unsupported_after']), (6, 0))
        self.assertEqual(sorted((r['kind'], r.get('objective') or r.get('table'), r['by'].removeprefix('campaign_quest_'))
                                for r in quest['lowerings']['resolved']), [
            ('completion_policy', 'returnHome', 'policy'), ('completion_policy', 'second', 'tracking'),
            ('rewards', 'quest_reward_money', 'rewards'), ('rewards', 'quest_reward_reputation', 'rewards'),
            ('tracked_completion', 'first', 'tracking'), ('tracked_completion', 'second', 'tracking')])
        self.assertFalse(quest['lowerings']['runtime_verified'])
        self.assertFalse(lowered['lowerings_runtime_verified'])
        path = 'Example/arbitrary_quest.xml'
        self.assertNotEqual(lowered['files'][path], report['files'][path])
        self.assertEqual(lowered['files']['Example.xml'], report['files']['Example.xml'])
        root = E.fromstring(lowered_files[path])
        for name in ('lowered_track_4_0_descriptor', 'lowered_track_5_0_watch', 'lowered_policy_6_timer',
                     'lowered_reward_4', 'lowered_reward_5'):
            self.assertIsNotNone(root.find(".//Nodes/*[@Name='" + name + "']"), name)
        names = [n.get('Name') for n in root.find('./Skald/Quest/Nodes')]
        self.assertEqual(len(names), len(set(names)))

    def test_nothing_is_removed_without_its_binding(self):
        m = source()
        files, report = emit_project([m], 'Example')
        lowered_files, lowered = lower(files, report, [m], {})
        quest = lowered['quests'][0]
        # Only the timed policy needs no binding.
        self.assertEqual(kinds(quest), ['completion_policy', 'rewards', 'rewards',
                                        'tracked_completion', 'tracked_completion'])
        root = E.fromstring(lowered_files['Example/arbitrary_quest.xml'])
        self.assertFalse([n.get('Name') for n in root.find('./Skald/Quest/Nodes')
                          if n.get('Name', '').startswith(('lowered_track_', 'lowered_reward_'))])

    def test_partly_bound_reward_table_keeps_its_remaining_rows(self):
        m = source()
        files, report = emit_project([m], 'Example')
        _, lowered = lower(files, report, [m], bindings(factions={}))
        left = [r for r in lowered['quests'][0]['unsupported'] if r['kind'] == 'rewards']
        self.assertEqual([(r['table'], len(r['rows']), r['lowered_rows'], r['reasons']) for r in left],
                         [('quest_reward_reputation', 1, 2, ['unmapped faction 31'])])
        self.assertEqual(left[0]['rows'][0]['quest_reward_reputation_id'], '143')

    def test_other_kinds_and_other_quests_are_untouched(self):
        m = source()
        rows = m['tables']['quest_objective']['rows']
        rows[1]['is_exclusive'] = 'True'                       # 4 exclusive, 5 not: mixed join into 6
        files, report = emit_project([m], 'Example')
        self.assertIn('mixed_exclusive_transition', kinds(report['quests'][0]))
        _, lowered = lower(files, report, [m], bindings())
        self.assertEqual(kinds(lowered['quests'][0]), ['mixed_exclusive_transition'])

    def test_presentation_only_tracking_is_resolved_without_nodes(self):
        m = source()
        m['tables']['quest_tracked_asset']['rows'][0].update(quest_asset_id='', map_asset_id='26')
        files, report = emit_project([m], 'Example')
        _, lowered = lower(files, report, [m], bindings())
        resolved = [r for r in lowered['quests'][0]['lowerings']['resolved'] if r.get('objective') == 'first']
        self.assertEqual([r['how'] for r in resolved], ['presentation only; no counted asset'])
        self.assertEqual(lowered['quests'][0]['unsupported'], [])

    def test_tracked_predicate_reaches_the_shared_condition_compiler(self):
        import campaign_dialogue_conditions as conditions
        saved = dict(conditions.OBJECTIVE)
        try:
            compiler = conditions.QuestConditions([source()])
            with self.assertRaises(ValueError):
                compiler.compile("IsObjectiveTrackedCompleted('arbitrary_quest','first')")
            enable_tracked_predicate()
            compiler = conditions.QuestConditions([source()])
            compiler.compile("IsObjectiveStarted('arbitrary_quest','first') AND IsObjectiveTrackedCompleted('arbitrary_quest','first')")
            self.assertEqual(sorted(b['output'] for b in compiler.bindings.values()),
                             ['first_Started', 'first_TrackedCompleted'])
        finally:
            conditions.OBJECTIVE.clear(); conditions.OBJECTIVE.update(saved)


class ReportTests(unittest.TestCase):
    def context(self):
        source_tables = dict(money={'19': '2-minor'}, exp={'7': '2-minor'},
            reputation={'21': 'quest_reward_4_normal', '72': 'quest_rewardFaction_2_normal'},
            souls={tracking.SOUL.lower(): 'rat_refugee_ales'}, item_categories={tracking.A: '5'})
        target = dict(item_map={tracking.A: tracking.A}, registered_items=[tracking.A],
            registered=dict(money_change={'02 Shoes'}, reputation_change={'quest_reward_4_normal'},
                            xp_change={'2-minor'}, xp_target=set(), faction=set(), perk=set()))
        return source_tables, target

    def test_native_bindings_never_invent_names(self):
        from quest_lowering_report import build_bindings
        source_tables, target = self.context()
        b = build_bindings([source()], source_tables, target, assume=False)
        self.assertEqual((b['soul_assets'], b['factions']), ({}, {}))
        # KCD1 values: money and reputation always bind to the 'kcd1_' rows that
        # campaign_quest_rewards.kcd1_value_tables writes, even where KCD2 has the same name.
        self.assertEqual(b['money_changes'], {'19': 'kcd1_2-minor'})
        self.assertEqual(b['reputation_changes'], {'21': 'kcd1_quest_reward_4_normal',
                                                   '72': 'kcd1_quest_rewardFaction_2_normal'})
        self.assertEqual(b['exp_changes'], {'7': '2-minor'})
        self.assertEqual(b['item_map'], {tracking.A: tracking.A})

    def test_assumed_bindings_are_listed_as_required_registrations(self):
        from quest_lowering_report import build_bindings, needs_registration
        source_tables, target = self.context()
        m = source()
        files, report = emit_project([m], 'Example')
        _, lowered = lower(files, report, [m], build_bindings([m], source_tables, target, assume=True))
        self.assertEqual(lowered['quests'][0]['unsupported'], [])
        native = dict(registered_items=set(target['registered_items']), registered=target['registered'])
        needed = needs_registration(lowered['quests'][0]['lowerings'], native)
        self.assertEqual([(n['kind'], n['target']) for n in needed], [
            ('faction', 'gluemapper_kcd1_faction_31'), ('money_change', 'kcd1_2-minor'),
            ('reputation_change', 'kcd1_quest_rewardFaction_2_normal'),
            ('reputation_change', 'kcd1_quest_reward_4_normal'), ('soul_asset', 'gm_soul_rat_refugee_ales')])


if __name__ == '__main__': unittest.main()
