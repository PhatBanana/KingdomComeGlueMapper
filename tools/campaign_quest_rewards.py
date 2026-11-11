"""Bind source objective rewards to the native Reward node.

Call after quest emission. Source reward rows hang off objectives; retail KCD2
uses one AddReward node whose Rewards children name table rows and assets:

    <AddReward Name="..."><Edge From="....OnDone" To="AddReward" />
      <Rewards><MoneyReward Amount="02 Shoes" />
               <SoulReputationReward ReputationChange="quest_reward_3_small" Target="olbram" />
               <FactionReputationReward ReputationChange="..." Target="<faction name>" /></Rewards>
    </AddReward>

Every target name comes from an explicit binding and must be registered; a row
without one stays pending, and its table stays in the conversion report. No
amount, faction or soul is chosen here. Immediate rows fire on the objective's
completion event. Deferred rows (is_immediate False) stay pending unless the
caller states a policy; achievements are never mapped. Not runtime-verified:
in particular, whether State.OnCompleted can repeat after a load is unproven.
"""
from collections import defaultdict
import uuid
import xml.etree.ElementTree as ET

from campaign_quest_graph import edge, identifier, xml

PREFIX = 'lowered_reward_'
# KCD1 reward values (Sean, 11-11: quests pay KCD1's own values, not KCD2's nearest rows).
# Money and reputation rows bind to 'kcd1_<KCD1 name>' rows that carry KCD1's numbers.
# Both games share the reputation target ids (all 67 shared row names keep the same
# target; KCD2 names them in rpg/reputation_change_target.xml). Engine scaling still
# differs: rpg_param QuestMoneyRewardScaleConstant is 1.2 in KCD1, 1.025 in KCD2.
KCD1_VALUE_PREFIX = 'kcd1_'
KCD1_MONEY_TABLE = 'Libs/Tables/rpg/money_change__gm_kcd1_quest.xml'
KCD1_REPUTATION_TABLE = 'Libs/Tables/rpg/reputation_change__gm_kcd1_quest.xml'
KCD1_REPUTATION_ID_BASE = 900000   # retail KCD2 ids end at 4206
KCD2_TARGETS = frozenset(('1', '6', '7', '14', '15'))
TABLES = ('quest_reward_money', 'quest_reward_reputation', 'quest_reward_exp',
          'quest_reward_item', 'quest_reward_perk', 'quest_reward_achievement')
EXPERIENCE = ('StatReward', 'SkillReward')


def _lookup(bindings, name, key):
    return {str(k).lower(): v for k, v in bindings.get(name, {}).items()}.get(str(key).lower())


def _registered(bindings, table, value):
    if value not in set(bindings.get('registered', {}).get(table, ())):
        raise ValueError('Unregistered ' + table + ': ' + str(value))
    return value


def lower_row(table, row, bindings):
    """One native reward element description, or (None, reason)."""
    if row.get('is_exclusive') == 'True':
        return None, 'exclusive reward'
    if table == 'quest_reward_money':
        name = _lookup(bindings, 'money_changes', row['money_change_id'])
        if name is None: return None, 'unmapped money change ' + row['money_change_id']
        return dict(tag='MoneyReward', Amount=_registered(bindings, 'money_change', name)), None
    if table == 'quest_reward_reputation':
        name = _lookup(bindings, 'reputation_changes', row['reputation_change_id'])
        if name is None: return None, 'unmapped reputation change ' + row['reputation_change_id']
        _registered(bindings, 'reputation_change', name)
        soul, faction = row.get('soul_id'), row.get('faction_id')
        if bool(soul) == bool(faction):
            return None, 'reputation reward needs exactly one of soul and faction'
        if soul:
            alias = _lookup(bindings, 'soul_assets', soul)
            if alias is None: return None, 'unregistered soul ' + soul.lower()
            return dict(tag='SoulReputationReward', ReputationChange=name, Target=identifier(alias)), None
        target = _lookup(bindings, 'factions', faction)
        if target is None: return None, 'unmapped faction ' + faction
        return dict(tag='FactionReputationReward', ReputationChange=name,
                    Target=_registered(bindings, 'faction', target)), None
    if table == 'quest_reward_exp':
        target = _lookup(bindings, 'exp_targets', row.get('rpg_attr', ''))
        name = _lookup(bindings, 'exp_changes', row['exp_change_id'])
        if target is None: return None, 'unmapped experience target ' + str(row.get('rpg_attr'))
        if name is None: return None, 'unmapped experience change ' + row['exp_change_id']
        tag, kind = target
        if tag not in EXPERIENCE: raise ValueError('Invalid experience reward kind: ' + str(tag))
        return dict(tag=tag, Type=_registered(bindings, 'xp_target', kind),
                    ExperienceChange=_registered(bindings, 'xp_change', name)), None
    if table == 'quest_reward_item':
        target = _lookup(bindings, 'item_map', row['item_id'])
        if target is None: return None, 'unmapped item ' + row['item_id'].lower()
        uuid.UUID(target)
        if target.lower() not in {str(i).lower() for i in bindings.get('registered_items', ())}:
            raise ValueError('Unregistered target item: ' + target)
        count = int(row.get('count') or '1')
        if count < 1: return None, 'unsupported item count ' + str(row.get('count'))
        return dict(tag='ItemReward', Amount=str(count), ItemClass=target), None
    if table == 'quest_reward_perk':
        if row.get('soul_id') or row.get('only_unlock') == 'True':
            return None, 'perk reward for another soul or unlock-only'
        name = _lookup(bindings, 'perks', row['perk_id'])
        if name is None: return None, 'unmapped perk ' + row['perk_id']
        return dict(tag='PerkReward', Perk=_registered(bindings, 'perk', name)), None
    return None, 'source-platform achievement is not mapped'


def kcd1_value_tables(money_rows, reputation_rows, money_names=None, reputation_names=None):
    """{package path: XML bytes} of 'kcd1_<name>' rows carrying KCD1's values.

    money_rows / reputation_rows are KCD1's quest/money_change and rpg/reputation_change
    rows; *_names limits the output to the KCD1 names a quest uses (None = all). A row
    with a reputation cap, an unknown target, or a name not in the source is refused,
    never dropped."""
    def table(root_tag, rows):
        db = ET.Element('database', {'name': 'barbora'})
        group = ET.SubElement(db, root_tag, version='1')
        for attributes in rows: ET.SubElement(group, root_tag[:-1], attributes)
        ET.indent(db, '\t')
        body = ET.tostring(db, encoding='unicode').encode('ascii', 'xmlcharrefreplace')
        return b'<?xml version="1.0" encoding="us-ascii"?>\n' + body + b'\n'
    def pick(rows, names, label):
        by_name = {r['name']: r for r in rows}
        wanted = sorted(by_name) if names is None else sorted(set(names))
        missing = [n for n in wanted if n not in by_name]
        if missing: raise ValueError('Unknown KCD1 ' + label + ': ' + ', '.join(missing))
        return [by_name[n] for n in wanted]
    money = [dict(change=r['change'], name=KCD1_VALUE_PREFIX + r['name'])
             for r in pick(money_rows, money_names, 'money change')]
    reputation = []
    for r in pick(reputation_rows, reputation_names, 'reputation change'):
        if r.get('reputation_cap'):
            raise ValueError('KCD1 reputation change with a cap has no KCD2 column: ' + r['name'])
        if r['reputation_change_target_id'] not in KCD2_TARGETS:
            raise ValueError('Unknown reputation target for ' + r['name'] + ': ' + r['reputation_change_target_id'])
        reputation.append(dict(can_change_hostility=r['can_change_hostility'].lower(), change=r['change'],
                               name=KCD1_VALUE_PREFIX + r['name'],
                               reputation_change_id=str(KCD1_REPUTATION_ID_BASE + int(r['reputation_change_id'])),
                               reputation_change_target_id=r['reputation_change_target_id'],
                               reputation_notification_id=r.get('reputation_notification_id') or '0'))
    out = {}
    if money: out[KCD1_MONEY_TABLE] = table('money_changes', money)
    if reputation: out[KCD1_REPUTATION_TABLE] = table('reputation_changes', reputation)
    return out


def plan(model, bindings):
    policies = bindings.get('policies', {})
    deferred = policies.get('deferred_rewards')
    if deferred not in (None, 'quest_done'):
        raise ValueError('Unknown deferred reward policy: ' + str(deferred))
    if policies.get('achievements') not in (None, 'omit'):
        raise ValueError('Unknown achievement policy: ' + str(policies.get('achievements')))
    objectives = {r['objective_id']: r for r in model['tables']['quest_objective']['rows']}
    groups, pending, omitted = defaultdict(list), [], []
    for table in sorted(t for t in model['tables'] if t.startswith('quest_reward')):
        for row in model['tables'][table]['rows']:
            if row['quest_id'] != model['quest_id']:
                raise ValueError('Mismatched reward row')
            if table not in TABLES:
                pending.append(dict(table=table, row=row, reason='unknown reward table')); continue
            if row.get('objective_id') not in objectives:
                pending.append(dict(table=table, row=row, reason='reward without a known objective')); continue
            if table == 'quest_reward_achievement' and policies.get('achievements') == 'omit':
                omitted.append(dict(table=table, row=row, reason='achievements omitted by caller policy')); continue
            immediate = row.get('is_immediate') == 'True'
            if not immediate and (row.get('is_immediate') != 'False' or deferred is None):
                pending.append(dict(table=table, row=row, reason='deferred reward timing is not established')); continue
            native, reason = lower_row(table, row, bindings)
            if reason:
                pending.append(dict(table=table, row=row, reason=reason)); continue
            groups[(row['objective_id'], 'immediate' if immediate else 'deferred')].append(
                dict(table=table, native=native, source=row))
    converted = [dict(objective_id=oid, objective=objectives[oid]['objective_name'], timing=timing, rewards=rewards)
                 for (oid, timing), rewards in sorted(groups.items(), key=lambda p: (int(p[0][0]), p[0][1]))]
    return dict(converted=converted, pending=pending, omitted=omitted, runtime_verified=False)


def bind(blob, model, bindings):
    report = plan(model, bindings)
    root = ET.fromstring(blob)
    quest = root.find('./Skald/Quest')
    if quest is None or quest.get('Name') != model['quest']:
        raise ValueError('Destination quest identity mismatch')
    nodes = quest.find('Nodes')
    if any(n.get('Name', '').startswith(PREFIX) for n in nodes):
        raise ValueError('Rewards already lowered')
    if not report['converted']:
        return blob, report
    for group in report['converted']:
        oid = group['objective_id']; state_name = 'objective_' + oid
        if nodes.find("State[@Name='" + state_name + "']") is None:
            raise ValueError('Missing native objective state ' + oid)
        name = PREFIX + oid + ('' if group['timing'] == 'immediate' else '_deferred')
        node = ET.SubElement(nodes, 'AddReward', Name=name)
        if group['timing'] == 'immediate':
            edge(node, state_name + '.OnCompleted', 'AddReward')
        else:
            # Caller policy 'quest_done': pay when the quest ends, and only for
            # an objective that was completed.
            gate = ET.SubElement(nodes, 'If', Name=name + '_if_completed')
            edge(gate, state_name + '.Completed', 'Condition')
            edge(gate, 'quest_progress.OnDone', 'Exec')
            edge(node, name + '_if_completed.True', 'AddReward')
        rewards = ET.SubElement(node, 'Rewards')
        for reward in group['rewards']:
            attributes = dict(reward['native']); tag = attributes.pop('tag')
            ET.SubElement(rewards, tag, attributes)
    return xml(root), report
