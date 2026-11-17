import copy
from pathlib import Path
import sys
import unittest
import xml.etree.ElementTree as E
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from campaign_quest_graph import emit_project
from campaign_quest_rewards import (KCD1_MONEY_TABLE, KCD1_REPUTATION_TABLE, bind, kcd1_value_tables, plan)
from test_campaign_quest_graph import model

A = '00000000-0000-0000-0000-000000000001'
B = '00000000-0000-0000-0000-000000000002'
SOUL = '4bd6aed3-4d8a-e72c-dae5-fcf29ec7daa1'


def rewarded():
    m = model()
    m['tables']['quest_reward_money'] = dict(rows=[dict(quest_id='42', objective_id='4', money_change_id='19',
        is_immediate='True', is_exclusive='False', quest_reward_money_id='137')])
    m['tables']['quest_reward_reputation'] = dict(rows=[
        dict(quest_id='42', objective_id='4', reputation_change_id='21', soul_id=SOUL.upper(), faction_id='',
             is_immediate='True', quest_reward_reputation_id='142'),
        dict(quest_id='42', objective_id='4', reputation_change_id='72', soul_id='', faction_id='31',
             is_immediate='True', quest_reward_reputation_id='143'),
        dict(quest_id='42', objective_id='5', reputation_change_id='21', soul_id=SOUL, faction_id='',
             is_immediate='True', quest_reward_reputation_id='144')])
    return m


def bindings(**changes):
    result = dict(money_changes={'19': 'kcd1_2-minor'},
        reputation_changes={'21': 'quest_reward_4_normal', '72': 'quest_rewardFaction_2_normal'},
        soul_assets={SOUL: 'gm_soul_ales'}, factions={'31': 'gluemapper_kcd1_faction_31'},
        exp_changes={'7': '2-minor'}, exp_targets={'spc': ('StatReward', 'speech'), 'stealth': ('SkillReward', 'stealth')},
        item_map={A: B}, registered_items=[B], perks={'p1': 'kcd1_perk'},
        registered=dict(money_change=['kcd1_2-minor'], faction=['gluemapper_kcd1_faction_31'],
                        reputation_change=['quest_reward_4_normal', 'quest_rewardFaction_2_normal'],
                        xp_change=['2-minor'], xp_target=['speech', 'stealth'], perk=['kcd1_perk']))
    result.update(changes)
    return result


def lowered(m, b=None):
    files, _ = emit_project([m], 'Example')
    blob, report = bind(files['Example/arbitrary_quest.xml'], m, bindings() if b is None else b)
    return E.fromstring(blob), report, blob


class RewardTests(unittest.TestCase):
    def test_immediate_rows_become_one_native_reward_per_objective(self):
        m = rewarded(); before = copy.deepcopy(m)
        root, report, _ = lowered(m)
        self.assertEqual(m, before)
        node = root.find(".//Nodes/AddReward[@Name='lowered_reward_4']")
        self.assertEqual([e.attrib for e in node.findall('Edge')], [dict(From='objective_4.OnCompleted', To='AddReward')])
        self.assertEqual([(e.tag, e.attrib) for e in node.find('Rewards')], [
            ('MoneyReward', dict(Amount='kcd1_2-minor')),
            ('SoulReputationReward', dict(ReputationChange='quest_reward_4_normal', Target='gm_soul_ales')),
            ('FactionReputationReward', dict(ReputationChange='quest_rewardFaction_2_normal', Target='gluemapper_kcd1_faction_31'))])
        other = root.find(".//Nodes/AddReward[@Name='lowered_reward_5']")
        self.assertEqual(len(other.find('Rewards')), 1)
        self.assertEqual([(g['objective'], g['timing'], len(g['rewards'])) for g in report['converted']],
                         [('first', 'immediate', 3), ('second', 'immediate', 1)])
        self.assertFalse(report['pending'])
        self.assertFalse(report['runtime_verified'])

    def test_rows_without_a_binding_stay_pending_and_emit_nothing(self):
        m = rewarded()
        report = plan(m, bindings(money_changes={}, soul_assets={}, factions={}))
        self.assertFalse(report['converted'])
        self.assertEqual(sorted(p['reason'] for p in report['pending']),
                         ['unmapped faction 31', 'unmapped money change 19',
                          'unregistered soul ' + SOUL, 'unregistered soul ' + SOUL])
        files, _ = emit_project([m], 'Example')
        blob, _ = bind(files['Example/arbitrary_quest.xml'], m, {})
        self.assertEqual(blob, files['Example/arbitrary_quest.xml'])

    def test_target_names_must_be_registered(self):
        for table in ('money_change', 'reputation_change', 'faction'):
            with self.subTest(table=table):
                b = bindings(); b['registered'][table] = []
                with self.assertRaisesRegex(ValueError, 'Unregistered ' + table):
                    plan(rewarded(), b)

    def test_ambiguous_or_exclusive_rows_stay_pending(self):
        m = rewarded()
        m['tables']['quest_reward_money']['rows'][0]['is_exclusive'] = 'True'
        m['tables']['quest_reward_reputation']['rows'][0]['faction_id'] = '31'
        m['tables']['quest_reward_reputation']['rows'][1]['faction_id'] = ''
        m['tables']['quest_reward_reputation']['rows'][2]['objective_id'] = '99'
        reasons = sorted(p['reason'] for p in plan(m, bindings())['pending'])
        self.assertEqual(reasons, ['exclusive reward', 'reputation reward needs exactly one of soul and faction',
                                   'reputation reward needs exactly one of soul and faction',
                                   'reward without a known objective'])

    def test_deferred_rows_need_an_explicit_policy(self):
        m = rewarded()
        m['tables']['quest_reward_money']['rows'][0]['is_immediate'] = 'False'
        report = plan(m, bindings())
        self.assertEqual([p['reason'] for p in report['pending']], ['deferred reward timing is not established'])
        root, report, _ = lowered(m, bindings(policies=dict(deferred_rewards='quest_done')))
        self.assertFalse(report['pending'])
        node = root.find(".//Nodes/AddReward[@Name='lowered_reward_4_deferred']")
        self.assertEqual([e.attrib for e in node.findall('Edge')],
                         [dict(From='lowered_reward_4_deferred_if_completed.True', To='AddReward')])
        gate = root.find(".//Nodes/If[@Name='lowered_reward_4_deferred_if_completed']")
        self.assertEqual({(e.get('From'), e.get('To')) for e in gate},
                         {('objective_4.Completed', 'Condition'), ('quest_progress.OnDone', 'Exec')})
        self.assertEqual(len(root.find(".//Nodes/AddReward[@Name='lowered_reward_4']/Rewards")), 2)
        with self.assertRaisesRegex(ValueError, 'Unknown deferred reward policy'):
            plan(m, bindings(policies=dict(deferred_rewards='now')))

    def test_experience_item_and_perk_rows(self):
        m = model()
        m['tables']['quest_reward_exp'] = dict(rows=[
            dict(quest_id='42', objective_id='4', exp_change_id='7', rpg_attr='spc', is_immediate='True'),
            dict(quest_id='42', objective_id='4', exp_change_id='7', rpg_attr='stealth', is_immediate='True'),
            dict(quest_id='42', objective_id='4', exp_change_id='7', rpg_attr='hunter', is_immediate='True')])
        m['tables']['quest_reward_item'] = dict(rows=[dict(quest_id='42', objective_id='4', item_id=A.upper(), count='3',
            is_immediate='True', is_exclusive='False')])
        m['tables']['quest_reward_perk'] = dict(rows=[
            dict(quest_id='42', objective_id='4', perk_id='p1', soul_id='', only_unlock='False', is_immediate='True'),
            dict(quest_id='42', objective_id='4', perk_id='p1', soul_id='', only_unlock='True', is_immediate='True')])
        root, report, _ = lowered(m)
        self.assertEqual([(e.tag, e.attrib) for e in root.find(".//Nodes/AddReward[@Name='lowered_reward_4']/Rewards")], [
            ('StatReward', dict(Type='speech', ExperienceChange='2-minor')),
            ('SkillReward', dict(Type='stealth', ExperienceChange='2-minor')),
            ('ItemReward', dict(Amount='3', ItemClass=B)),
            ('PerkReward', dict(Perk='kcd1_perk'))])
        self.assertEqual(sorted(p['reason'] for p in report['pending']),
                         ['perk reward for another soul or unlock-only', 'unmapped experience target hunter'])
        with self.assertRaisesRegex(ValueError, 'Unregistered target item'):
            plan(m, bindings(registered_items=[]))

    def test_achievements_are_never_mapped(self):
        m = model()
        m['tables']['quest_reward_achievement'] = dict(rows=[dict(quest_id='42', objective_id='4', statistic_id='139',
                                                                  is_immediate='True')])
        report = plan(m, bindings())
        self.assertEqual([p['reason'] for p in report['pending']], ['source-platform achievement is not mapped'])
        report = plan(m, bindings(policies=dict(achievements='omit')))
        self.assertFalse(report['pending'] or report['converted'])
        self.assertEqual(len(report['omitted']), 1)

    def test_binding_is_single_use(self):
        m = rewarded()
        _, _, blob = lowered(m)
        with self.assertRaisesRegex(ValueError, 'already lowered'):
            bind(blob, m, bindings())


class Kcd1ValueTablesTests(unittest.TestCase):
    MONEY = [dict(change='40', money_change_id='19', name='2-minor'), dict(change='60', money_change_id='21', name='4-normal')]
    REP = [dict(can_change_hostility='False', change='0.35', name='quest_reward_4_normal', reputation_cap='',
                reputation_change_id='21', reputation_change_target_id='15', reputation_notification_id='0'),
           dict(can_change_hostility='True', change='-2', name='hit_capped', reputation_cap='0.5',
                reputation_change_id='40', reputation_change_target_id='1', reputation_notification_id='')]

    def test_rows_carry_kcd1_values_under_kcd1_names(self):
        out = kcd1_value_tables(self.MONEY, self.REP, ['2-minor'], ['quest_reward_4_normal'])
        self.assertEqual(sorted(out), sorted([KCD1_MONEY_TABLE, KCD1_REPUTATION_TABLE]))
        money = E.fromstring(out[KCD1_MONEY_TABLE])
        self.assertEqual([r.attrib for r in money.iter('money_change')], [dict(change='40', name='kcd1_2-minor')])
        rep = [r.attrib for r in E.fromstring(out[KCD1_REPUTATION_TABLE]).iter('reputation_change')]
        self.assertEqual(rep, [dict(can_change_hostility='false', change='0.35', name='kcd1_quest_reward_4_normal',
                                    reputation_change_id='900021', reputation_change_target_id='15',
                                    reputation_notification_id='0')])
        self.assertTrue(out[KCD1_MONEY_TABLE].startswith(b'<?xml version="1.0" encoding="us-ascii"?>'))

    def test_refuses_caps_unknown_names_and_targets(self):
        with self.assertRaisesRegex(ValueError, 'cap'):
            kcd1_value_tables(self.MONEY, self.REP, [], ['hit_capped'])
        with self.assertRaisesRegex(ValueError, 'Unknown KCD1 money change: 9-none'):
            kcd1_value_tables(self.MONEY, self.REP, ['9-none'], [])
        odd = [dict(self.REP[0], reputation_change_target_id='3')]
        with self.assertRaisesRegex(ValueError, 'Unknown reputation target'):
            kcd1_value_tables([], odd, [], None)

    def test_unused_tables_are_not_written(self):
        self.assertEqual(kcd1_value_tables(self.MONEY, self.REP, [], []), {})


if __name__ == '__main__': unittest.main()
