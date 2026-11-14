"""Walk the KCD1 quests the mod ports, on the lowered container `setup_kcd1_quests.plan_quest` builds in memory.

Offline: reads retail KCD1/KCD2 (and a built package when a quest needs one), writes only the report.
Also reruns the stage's own `--lab` scenarios against the lowered quest, with an explicit world.
"""
import json
from pathlib import Path

from .runner import Runner
from .source import Source
from .walk import ASSUMED, BAG, NPC_BAG, PLAYER, Walk, external_contracts, slice_container, table
from .objects import SOUL


def world(aliases, npc):
    return dict(assets=dict(aliases), assumptions=dict(ASSUMED, **{'delivery.player_inventory': BAG}), objects={
        PLAYER: {SOUL: {'properties': {'Inventory': BAG}}}, BAG: Walk.bag({}),
        npc: {SOUL: {'properties': {'Inventory': NPC_BAG}}}, NPC_BAG: Walk.bag({})})


def waived_rewards(accepted_pending):
    """'quest_reward_reputation:<objective>:<target>' rows the selection declares the package cannot pay."""
    found = {}
    for entry in accepted_pending:
        table_name, objective, target = entry.split(':', 2)
        if table_name != 'quest_reward_reputation':
            raise ValueError('Unknown accepted pending row: ' + entry)
        kind = 'faction_reputation' if target.startswith('faction_') else 'soul_reputation'
        found[(objective, kind)] = found.get((objective, kind), 0) + 1
    return found


def walk_planned(row, resources, report, model, source_dialogues, money=None, **options):
    """One quest on its planned resources ({archive path: bytes})."""
    import setup_kcd1_quests as stage
    from campaign_quest_graph import objective_identifier
    quest = row['quest']
    dialogues = [row['namespace'] + '_' + topic for _, topic in row['branches']]
    blobs, kept, externals = slice_container(resources, stage.ENTRY, [quest, *dialogues])
    # The walk's world is the travel save: no other quest of the container has been started.
    contracts = external_contracts(externals, {name: 'Unchanged' for name in externals})
    blobs[stage.PROJECT.lower()] = resources[stage.PROJECT]       # objective state types
    npc = report['evidence']['soul'].lower()
    aliases = {stage.PLAYER_ASSET: PLAYER, stage.DIALOGUE_PLAYER: PLAYER}
    aliases.update({alias: npc for alias in report['npc_assets'].values()})
    # On the KCD1 side the story quests the giver waits for count as completed (the port's premise for that save).
    wanted = row['prerequisites']
    other = ({name: state[:1].upper() + state[1:] for name, state in wanted.items()} if isinstance(wanted, dict)
             else {name: 'Completed' for name in wanted})
    source = Source.blobs(blobs)
    result = Walk(source, stage.CONTAINER, quest, dialogues, model, source_dialogues, npc, aliases, other_quests=other,
                  waived=waived_rewards(row['accepted_pending']), money=money, identifier=objective_identifier, contracts=contracts,
                  **options).run()
    result['container_nodes'] = len(kept)
    result['external_quests'] = {n: 'Unchanged' for n in externals}
    result['accepted_pending'] = list(row['accepted_pending'])
    # The stage's own scenarios, on the lowered quest instead of the unlowered emission.
    import inspect
    accepted = inspect.signature(stage.lab_scenarios).parameters
    runs, uncovered = stage.lab_scenarios(model, **{k: v for k, v in dict(
        order=row.get('lab_order'), prerequisites=row['prerequisites']).items() if k in accepted})
    lab = []
    quest_source = Source.blobs({k: v for k, v in blobs.items() if k != stage.ENTRY.lower()})
    for scenario in runs:
        outcome = Runner(dict(scenario, **world(aliases, npc)), source=quest_source).run()
        lab.append(dict(name=outcome['name'], status=outcome['status'], error=outcome['error']))
    result['lab_scenarios'] = lab
    result['lab_listed_unsupported'] = [u['name'] for u in uncovered]
    if any(s['status'] != 'PASS' for s in lab) and result['status'] == 'PASS':
        result['status'] = 'FAIL' if any(s['status'] == 'FAIL' for s in lab) else 'UNSUPPORTED'
    return result


def run(kcd1, kcd2, package=None, only=(), output=None, progress=lambda *a: None, **options):
    import setup_kcd1_quests as stage
    import quest_lowering_report as lowering
    from campaign_dialogue import load_many
    from campaign_sources import RetailSourceReader
    kcd1 = Path(kcd1)
    with RetailSourceReader(kcd1) as reader:
        money_rows = lowering.source_rows(reader, kcd1, 'quest/money_change')
    money = {r['money_change_id']: 'kcd1_' + r['name'] for r in money_rows}
    results, skipped, resources = [], {}, None
    for row in stage.QUESTS:
        if package is None and row.get('needs_package'):
            skipped[row['quest']] = 'needs --package'
            continue
        progress('plan', row['quest'])
        planned, report = stage.plan_quest(row, kcd1, kcd2, package, base=resources if package is not None else None)
        if package is not None: resources = planned
        if only and row['quest'] not in only: continue
        with RetailSourceReader(kcd1) as reader:
            model = stage.source_model(kcd1, row['quest'], reader)
        source_dialogues = load_many(kcd1, [(None, topic) for _, topic in row['branches']])
        progress('walk', row['quest'])
        result = walk_planned(row, planned, report, model, source_dialogues, money=money, **options)
        result['controller_pending'] = report.get('controller_pending')
        results.append(result)
    summary = dict(schema=1, quests=results, skipped=skipped, native_runtime_verified=False,
                   scope='Lowered container built in memory by setup_kcd1_quests.plan_quest; KCD1 reference from source tables')
    if output is not None:
        output = Path(output); output.mkdir(parents=True, exist_ok=True)
        (output / 'walk.json').write_text(json.dumps(summary, indent=2, default=str), encoding='utf-8')
        (output / 'walk.md').write_text(table(results), encoding='utf-8')
    return summary
