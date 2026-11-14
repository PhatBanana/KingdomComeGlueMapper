"""Per-quest conversion ledger: what was converted, what is residue, and why.

One ledger per quest and converter. Every source record is either converted or
listed here as a typed residue record; the counts are the numbers a brief
reports per test layer (checked / passed / residue). Converter C1 (objectives)
writes it today; later converters add their own `layers` and residue kinds.

Also here, because they are derived from the same data:

    walk_spec  the KCD1-expected objective sequence, as data for a quest_lab
               exhaustive walk (layer 2). This module does not run the lab.
    golden     the fixture a test compares against (layer 3): the emitted
               file's hash plus a structural summary, never source text.

Developer tooling; never imported by Setup. Nothing here is runtime-proven.
"""
from collections import Counter, defaultdict
import hashlib
import json
from pathlib import Path
import xml.etree.ElementTree as ET

from campaign_quest_graph import objective_identifier
import campaign_quest_places
import quest_source_equivalence

# First matching fragment wins. A reason that matches nothing is 'unclassified'
# and fails the ledger test, so a new reason cannot slip in untyped.
RESIDUE_KINDS = (
    ('place tracking requires a spatial adapter', 'place_unresolved'),
    ('unregistered place', 'place_unresolved'),
    ('place without an area', 'place_without_area'),
    ('place on another map', 'place_unresolved'),
    ('unsupported place count', 'place_unresolved'),
    ('expiration timeout', 'expiration_semantics'),
    ('timeout without a named clock', 'timeout_clock_unnamed'),
    ('timeout without a constant', 'timeout_on_expression'),
    ('timeout on a tracked objective', 'tracked_timeout'),
    ('function condition with a timeout', 'timeout_on_expression'),
    ('condition expression on a tracked objective', 'tracked_expression'),
    ('expression on a tracked objective', 'tracked_expression'),
    ('function condition on a tracked objective', 'tracked_expression'),
    ('undefined condition name', 'undefined_condition_name'),
    ('function expansion failed', 'expression_unbound'),
    ('expanded condition is not bound', 'expression_unbound'),
    ('item asset without a class', 'category_only_item'),
    ('unsupported item type filter', 'category_only_item'),
    ('unproven item category filter', 'category_only_item'),
    ('unmapped item', 'item_unregistered'),
    ('unsupported NPC selector', 'npc_selector'),
    ('unsupported NPC count', 'npc_selector'),
    ('unregistered soul', 'soul_unregistered'),
    ('constant-true objective with presentation-only tracking', 'marker_constant_true'),
    ('constant condition with a marker', 'marker_constant_true'),
    ('unknown asset kind', 'asset_kind_unknown'),
    ('duplicate tracked asset', 'asset_kind_unknown'),
    ('unsupported count', 'asset_kind_unknown'),
    ('unsupported minimum health', 'asset_kind_unknown'),
)


def residue_kind(reason):
    for fragment, kind in RESIDUE_KINDS:
        if fragment in reason: return kind
    return 'unclassified'


def residue(model, quest):
    """Type every `unsupported` record that is left after the lowerings."""
    lowerings = quest.get('lowerings', {})
    reasons = defaultdict(list)
    for name in ('tracking', 'policy', 'conditions'):
        for record in lowerings.get(name, {}).get('pending', []):
            reasons[objective_identifier(record['objective'])].extend(record.get('reasons') or [record['reason']])
    classes = {objective_identifier(o['name']): o['completion'] for o in quest_source_equivalence.expected(model)['objectives']}
    records = []
    for record in quest['unsupported']:
        kind, name = record['kind'], record.get('objective') or record.get('table')
        why = list(reasons.get(name, []))
        if kind == 'mixed_exclusive_transition':
            kinds, why = ['mixed_exclusive'], ['exclusive and non-exclusive predecessors on one join']
        elif kind == 'rewards':
            why = record.get('reasons', ['no reward lowering ran'])
            kinds = ['reward_unmapped']
        elif kind == 'objective_callbacks':
            kinds, why = ['objective_callbacks'], [record.get('reason', '')]
        else:
            if not why and classes.get(name, {}).get('kind') == 'expression':
                why = ['condition is not bound: ' + classes[name]['condition']]
                kinds = ['expression_unbound']
            else:
                if not why and classes.get(name, {}).get('why'): why = [classes[name]['why']]
                kinds = sorted({residue_kind(r) for r in why}) or ['unclassified']
        records.append(dict(kind=kind, item=name, residue_kinds=kinds, reasons=why))
    return records


def build(model, emitted_quest, lowered_quest, equivalence):
    """Ledger for one quest. `emitted_quest` is the emitter's report before the lowerings."""
    left = residue(model, lowered_quest)
    lowerings = lowered_quest.get('lowerings', {})
    tracking = lowerings.get('tracking', dict(converted=[], presentation=[]))
    classes = Counter(o['completion']['kind'] for o in quest_source_equivalence.expected(model)['objectives'])
    return dict(
        schema=1, converter='C1', quest=model['quest'], source_quest_id=model['quest_id'],
        counts=dict(before=dict(Counter(r['kind'] for r in emitted_quest['unsupported'])),
                    before_total=len(emitted_quest['unsupported']),
                    after=dict(Counter(r['kind'] for r in lowered_quest['unsupported'])),
                    after_total=len(lowered_quest['unsupported']),
                    after_by_residue_kind=dict(Counter(k for r in left for k in r['residue_kinds']))),
        source=dict(objectives=len(model['tables']['quest_objective']['rows']),
                    transitions=sum(r['enabled'] == 'True' for r in model['tables']['quest_transition']['rows']),
                    tracked_assets=len(model['tables'].get('quest_tracked_asset', {}).get('rows', [])),
                    reward_rows=sum(len(t['rows']) for n, t in model['tables'].items() if n.startswith('quest_reward')),
                    completion_classes=dict(classes)),
        converted=dict(resolved=dict(Counter(r['by'].removeprefix('campaign_quest_') for r in lowerings.get('resolved', []))),
                       quest_end=lowered_quest.get('converted_quest_end'),
                       local_conditions=len(lowered_quest.get('converted_conditions', [])),
                       linked_conditions=len(lowered_quest.get('converted_linked_conditions', [])),
                       function_conditions=[dict(objective=r['objective'], functions=r['functions'])
                                            for r in lowerings.get('conditions', {}).get('converted', [])]),
        residue=left,
        world_requirements=[dict(kind='TriggerArea', source_entity=e, asset=a)
                            for e, a in campaign_quest_places.world_requirements(tracking)],
        layers=dict(source_equivalence=dict(verdict=equivalence['verdict'], summary=equivalence['summary'],
                                            categories=equivalence['categories'], failures=equivalence['failures'],
                                            residue=equivalence['residue'])),
        runtime_verified=False)


def walk_spec(model):
    """The source's objective graph, as the data an exhaustive lab walk asserts.

    `completion` says who completes each objective. 'external' and
    'tracked_manual' are completed by a controller or a dialogue, which this
    converter does not see: a walk must supply them as scenario outcomes.
    `main_path` is every objective that can lead to Quest:End through enabled
    source transitions, in a topological order; `expected_end_states` is what
    every walk that reaches Quest:End must have completed.
    """
    exp = quest_source_equivalence.expected(model)
    by_id = {o['id']: o for o in exp['objectives']}
    ancestors, stack = set(), [exp['end']] if exp['end'] else []
    while stack:
        for p in exp['joins'].get(stack.pop(), dict(predecessors=[]))['predecessors']:
            if p != exp['begin'] and p not in ancestors:
                ancestors.add(p); stack.append(p)
    order, placed = [], set()
    while len(order) < len(ancestors):
        ready = sorted((i for i in ancestors - placed
                        if all(p == exp['begin'] or p not in ancestors or p in placed
                               for p in exp['joins'].get(i, dict(predecessors=[]))['predecessors'])), key=int)
        if not ready:
            ready = sorted(ancestors - placed, key=int)[:1]      # a source cycle; keep going, and say so
        order.extend(ready); placed.update(ready)

    def step(o):
        join = exp['joins'].get(o['id'])
        return dict(objective=o['name'], id=o['id'], hidden=o['hidden'], exclusive=o['exclusive'],
                    started_by=dict(join=join['join'], after=['Quest:Begin' if p == exp['begin'] else by_id[p]['name']
                                                              for p in join['predecessors']]) if join else 'external',
                    completion=o['completion']['kind'],
                    **({'duration': o['completion']['duration'], 'clock': o['completion']['clock']}
                       if o['completion']['kind'] == 'timed' else {}),
                    **({'condition': o['completion']['condition']} if o['completion']['kind'] == 'expression' else {}))
    end = exp['joins'].get(exp['end']) if exp['end'] else None
    return dict(schema=1, quest=model['quest'], start='Quest:Begin', end='Quest:End',
                end_join=dict(join=end['join'], after=[by_id[p]['name'] for p in end['predecessors']]) if end else None,
                expected_end_states=sorted(by_id[p]['name'] for p in (end or dict(predecessors=[]))['predecessors']),
                main_path=[step(by_id[i]) for i in order],
                off_path=[step(o) for o in exp['objectives'] if o['id'] not in ancestors],
                outcomes_the_walk_must_supply=sorted(by_id[i]['name'] for i in order
                                                     if by_id[i]['completion']['kind'] in ('external', 'tracked_manual', 'unestablished')),
                source='retail quest_objective, quest_transition and quest_tracked_asset tables')


def golden(ledger, blob):
    """Stable fixture: hash and structure of the output, and the ledger's numbers."""
    quest = ET.fromstring(blob).find('./Skald/Quest')
    nodes = quest.find('Nodes')
    # A journal binding's tag is its objective's name; count those as one kind.
    journal = {o.get('Name') for o in quest.find('Objectives')} if quest.find('Objectives') is not None else set()
    return dict(schema=1, quest=ledger['quest'], converter=ledger['converter'],
                emitted_sha256=hashlib.sha256(blob.replace(b'\r\n', b'\n')).hexdigest(),
                node_tags=dict(sorted(Counter('JournalBinding' if n.tag in journal else n.tag for n in nodes).items())),
                lowered_nodes=sorted(n.get('Name') for n in nodes
                                     if n.get('Name', '').startswith(('lowered_', 'source_condition_'))),
                counts=ledger['counts'], source=ledger['source'], converted=ledger['converted'],
                residue=ledger['residue'], world_requirements=ledger['world_requirements'],
                source_equivalence=dict(verdict=ledger['layers']['source_equivalence']['verdict'],
                                        summary=ledger['layers']['source_equivalence']['summary'],
                                        categories=ledger['layers']['source_equivalence']['categories']))


def write_json(path, payload):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str) + '\n', encoding='utf-8', newline='\n')


POLICIES = dict(deferred_rewards='quest_done', achievements='omit')


def convert(kcd1, kcd2, quests, with_quests=(), project='QuestConversion', policies=POLICIES):
    """Run C1 on retail sources with every referenced record assumed registered.

    This is the projection mode of quest_lowering_report (`assume=True`): the
    ledger then shows what the converter itself leaves, and `world_requirements`
    plus that report's `needs_registration` say what a package must provide.
    """
    from campaign_quest_graph import emit_project
    from campaign_quest_lowerings import lower
    from campaign_sources import RetailSourceReader
    from quest_lowering_report import build_bindings, load_context, place_classes, place_names, source_models
    source, target = load_context(kcd1, kcd2)
    with RetailSourceReader(Path(kcd1)) as reader:
        models = source_models(Path(kcd1), [*quests, *with_quests], reader)
        source = dict(source, place_classes=place_classes(reader, Path(kcd1), place_names(models)))
    bindings = build_bindings(models, source, target, True, policies=policies)
    files, emitted = emit_project(models, project)
    files, lowered = lower(files, emitted, models, bindings)
    checks = quest_source_equivalence.check_project(files, lowered, models, bindings)
    ledgers = [build(m, before, after, c) for m, before, after, c in zip(models, emitted['quests'], lowered['quests'], checks)]
    return dict(project=project, files=files, models=models, bindings=bindings, report=lowered, ledgers=ledgers)
