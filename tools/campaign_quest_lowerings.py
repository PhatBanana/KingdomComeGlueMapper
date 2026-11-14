"""Run the post-emission quest lowerings and reconcile the conversion report.

Call after quest emission (and after campaign_quest_items.bind when a caller
still uses it). `lower` applies, per quest:

    campaign_quest_tracking  counted item / named-NPC / area tracking and its predicate
    campaign_quest_conditions  objective conditions that name a source function
    campaign_quest_policy    never-automatic and timed completion policies
    campaign_quest_rewards   objective rewards as native Reward nodes

and then removes an `unsupported` record only when the adapter that owns it
reports that record fully lowered. Partly lowered reward tables stay in the
report with their remaining rows. Nothing is emitted for a record an adapter
left pending, and nothing here claims runtime behaviour.

Bindings (all optional; a missing one leaves the rows that need it pending):

    player_asset        native alias of the player soul asset
    item_map            {source item id: target item class id}
    registered_items    target item class ids that exist in the package
    item_categories     {source item id: source item_category_id}
    soul_assets         {source soul id: SoulAsset alias declared by the project}
    place_assets        {source entity name: dict(alias=TriggerAreaAsset alias,
                         entity_class=source EntityClass)}
    condition_functions {source dialogue_functions name: expression}
    factions            {source faction_id: target faction name}
    money_changes, reputation_changes, exp_changes   {source id: target row name}
    exp_targets         {source rpg_attr: ('StatReward' | 'SkillReward', Type)}
    perks               {source perk id: target perk name}
    registered          {'money_change' | 'reputation_change' | 'xp_change' |
                         'xp_target' | 'faction' | 'perk': names in the package}
    policies            {'deferred_rewards': 'quest_done', 'achievements': 'omit'}
"""
import copy
import hashlib

from campaign_quest_graph import objective_identifier
import campaign_quest_conditions
import campaign_quest_policy
import campaign_quest_rewards
import campaign_quest_tracking


def enable_tracked_predicate():
    """Let the shared condition compiler resolve IsObjectiveTrackedCompleted.

    It maps the source predicate to the `<objective>_TrackedCompleted` output
    port. The compiler still fails closed for a quest whose port was not
    emitted, so call this only for quests that went through `lower`.
    """
    from campaign_dialogue_conditions import OBJECTIVE
    OBJECTIVE.setdefault('IsObjectiveTrackedCompleted', campaign_quest_tracking.PREDICATE)


def reconcile(unsupported, tracking, policy, rewards, conditions=None):
    """Return (remaining, resolved) for one quest's emitter `unsupported` list."""
    tracked = {objective_identifier(r['objective']): r for r in tracking['converted']}
    tracked.update({objective_identifier(r['objective']): r for r in tracking.get('bound_by_quest_items', [])})
    shown = {objective_identifier(r['objective']) for r in tracking['presentation']}
    policies = {objective_identifier(r['objective']): r for r in policy['converted']}
    functions = {objective_identifier(r['objective']): r for r in (conditions or {}).get('converted', [])}
    reward_pending = {}
    for record in rewards['pending']:
        reward_pending.setdefault(record['table'], []).append(record)
    remaining, resolved = [], []
    for record in unsupported:
        kind, name = record['kind'], record.get('objective')
        if kind == 'tracked_completion' and name in tracked:
            resolved.append(dict(kind=kind, objective=name, by='campaign_quest_tracking',
                                 how=tracked[name].get('mode', 'campaign_quest_items')))
        elif kind == 'tracked_completion' and name in shown:
            resolved.append(dict(kind=kind, objective=name, by='campaign_quest_tracking',
                                 how='presentation only; no counted asset'))
        elif kind == 'completion_policy' and name in tracked:
            resolved.append(dict(kind=kind, objective=name, by='campaign_quest_tracking',
                                 how=tracked[name].get('mode', 'campaign_quest_items')))
        elif kind == 'completion_policy' and name in policies:
            resolved.append(dict(kind=kind, objective=name, by='campaign_quest_policy',
                                 how=policies[name]['policy']))
        elif kind == 'completion_policy' and name in functions:
            resolved.append(dict(kind=kind, objective=name, by='campaign_quest_conditions',
                                 how='expanded ' + ', '.join(functions[name]['functions'])))
        elif kind == 'rewards':
            left = reward_pending.get(record['table'], [])
            if left:
                remaining.append(dict(record, rows=[p['row'] for p in left],
                                      reasons=sorted({p['reason'] for p in left}),
                                      lowered_rows=len(record['rows']) - len(left)))
            else:
                resolved.append(dict(kind=kind, table=record['table'], by='campaign_quest_rewards',
                                     rows=len(record['rows'])))
        else:
            remaining.append(record)
    return remaining, resolved


def lower(files, report, models, bindings):
    """Apply every lowering to emitted quest files. Inputs are not modified."""
    project = report['project']
    by_name = {m['quest']: m for m in models}
    files, report = dict(files), copy.deepcopy(report)
    for quest in report['quests']:
        model = by_name[quest['quest']]
        path = project + '/' + model['quest'] + '.xml'
        blob = files[path]
        blob, tracking = campaign_quest_tracking.bind(blob, model, bindings)
        blob, conditions = campaign_quest_conditions.bind(blob, model, bindings)
        blob, policy = campaign_quest_policy.bind(blob, model)
        blob, rewards = campaign_quest_rewards.bind(blob, model, bindings)
        files[path] = blob
        before = quest['unsupported']
        quest['unsupported'], resolved = reconcile(before, tracking, policy, rewards, conditions)
        quest['lowerings'] = dict(tracking=tracking, policy=policy, rewards=rewards, conditions=conditions,
                                  resolved=resolved,
                                  unsupported_before=len(before), unsupported_after=len(quest['unsupported']),
                                  runtime_verified=False)
    report['files'] = {name: hashlib.sha256(blob).hexdigest() for name, blob in files.items()}
    report['lowerings_runtime_verified'] = False
    return files, report
