"""Whole-package diagnostic: roles per converted soul, contracts and findings."""
from collections import Counter, defaultdict
from pathlib import Path

from . import VERSION
from .contracts import findings, generated_trade_dialogs, keepers, trade_contract
from .engine import Engine
from .mounts import Mounts
from .program import Program
from .selectors import ASSUMPTIONS
from .tables import load


def evaluate(mounts, native_selfcheck=0, tasks=None):
    program = Program(mounts)
    tables = load(mounts, native_souls=bool(native_selfcheck))
    engine = Engine(program, tables, tasks)
    converted = [s for s in tables.souls if s.converted]
    results = {s.name: engine.run(s) for s in converted}
    native = {}
    if native_selfcheck:
        for soul in [s for s in tables.souls if not s.converted][:native_selfcheck]:
            native[soul.name] = engine.run(soul, record_ops=False)
    return program, tables, engine, results, native


def ambient(results):
    """Which native role sources reach converted souls, per source file."""
    by_file = defaultdict(lambda: dict(souls=set(), definite=set(), conditional=set(), rules=set()))
    for name, r in results.items():
        for role, st in r.roles.items():
            for src in st.sources:
                if src['layer'] != 'native': continue
                entry = by_file[src['file']]
                entry['souls'].add(name); entry['rules'].add(src['rule'])
                (entry['definite'] if st.definite else entry['conditional']).add(role)
    return {f: dict(souls=len(e['souls']), rules=sorted(e['rules']), definite_roles=sorted(e['definite']),
                    conditional_roles=sorted(e['conditional'] - e['definite']))
            for f, e in sorted(by_file.items())}


def sensitivity(results):
    """Rules that are False only because of an inferred semantic, grouped by assumption."""
    grouped = defaultdict(lambda: defaultdict(set))
    for name, r in results.items():
        for alt in r.alternatives:
            key = (alt['file'], alt['rule'], tuple(o.get('name') or o['op'] for o in alt['operations']))
            for dep in alt['deps']:
                grouped[dep.split(':', 1)[1]][key].add(name)
    return {a: [dict(file=f, rule=rule, operations=list(ops), souls=sorted(s)) for (f, rule, ops), s in
                sorted(rows.items(), key=lambda kv: (-len(kv[1]), kv[0]))] for a, rows in sorted(grouped.items())}


def run(package, target, output=None, native_selfcheck=0, mounts=None):
    mounts = mounts or Mounts.from_paths(package, target)
    program, tables, engine, results, native = evaluate(mounts, native_selfcheck)
    shop_keepers = keepers(mounts)
    contracts = trade_contract(program, tables, results, shop_keepers, generated_trade_dialogs(mounts))
    found = findings(program, tables, results, shop_keepers)
    unsupported = Counter(); assumptions = Counter(); status = Counter()
    for r in results.values():
        unsupported.update(r.unsupported); assumptions.update(r.assumptions); status.update(r.rules)
    voice = Counter((bool(s.get('skald_character_name')), s.get('voice_group_name')) for s in
                    (r.soul for r in results.values()))
    report = dict(
        schema=1, tool='storm_lab', version=VERSION, native_runtime_verified=False,
        package=str(package) if package else None, target=str(target) if target else None,
        program=program.inventory(),
        souls=dict(converted=len(results), keepers=len(shop_keepers),
                   voice_shapes=[dict(has_character=k[0], voice_group=k[1], souls=n) for k, n in voice.most_common()],
                   native_voice_shapes=[dict(has_character=k[0], voice_group=k[1], souls=n)
                                        for k, n in tables.native_shapes.most_common()]),
        rule_evaluations=dict(status), unsupported=dict(unsupported.most_common()),
        assumptions_used=dict(assumptions.most_common()), assumptions=ASSUMPTIONS,
        unknown_operations=dict(engine.unknown_operations),
        contracts=contracts, findings=found, ambient=ambient(results), sensitivity=sensitivity(results),
        roles_by_soul={n: r.as_dict() for n, r in sorted(results.items())},
        table_overrides=tables.overrides[:500],
        provenance=mounts.provenance())
    if native:
        n_unsupported = Counter(); n_status = Counter()
        for r in native.values():
            n_unsupported.update(r.unsupported); n_status.update(r.rules)
        report['native_selfcheck'] = dict(souls=len(native), rule_evaluations=dict(n_status),
                                          unsupported=dict(n_unsupported.most_common(40)))
    report['verdict'] = verdict(report)
    if output is not None:
        from .report import write_audit
        write_audit(report, Path(output))
    return report


def verdict(report):
    errors = [f for f in report['findings'] if f['severity'] == 'error']
    reviews = [f for f in report['findings'] if f['severity'] == 'review']
    failing = [c for c in report['contracts'] if c['status'] != 'PASS']
    return dict(status='FAIL' if errors or failing else 'PASS_WITH_REVIEW' if reviews else 'PASS',
                errors=len(errors), reviews=len(reviews), contracts_failing=len(failing),
                note='PASS means the modeled Storm semantics and contracts hold; it is not native-runtime verification.')
