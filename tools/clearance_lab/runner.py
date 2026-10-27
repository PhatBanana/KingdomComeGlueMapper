"""Assertion-based JSON scenarios over a package or an inline synthetic world.

Scenario::

  {"name": "...",
   "world": {...inline world...}            # or
   "package": "path", "target": "KCD2 dir", "kcd1": "optional KCD1 dir",
   "assumptions": {...optional overrides...},
   "assertions": [
     {"check": "boundary_closure", "status": "PASS"},
     {"category": "boundary_gap", "count": {"min": 1, "max": 1}},
     {"category": "interaction_overlap", "severity": "defect", "near": [x, y], "within": 2.0, "expect": "present"}],
   "all_checks": true}                       # default: true for packages, false for inline worlds

An assertion naming something the audit did not produce is FAIL, and a check
reported UNSUPPORTED makes the scenario UNSUPPORTED (never PASS).
"""
import json
import math
from pathlib import Path

from . import Unsupported
from .audit import audit
from .source import load_package


def normalize_world(w):
    w = dict(w)
    w.setdefault('roads', []); w.setdefault('interactions', []); w.setdefault('unsupported', [])
    w['volumes'] = [dict(v, matrix=tuple(v['matrix']), local_min=tuple(v['local_min']), local_max=tuple(v['local_max']),
                         world_aabb=tuple(v.get('world_aabb') or _aabb(v)), origin=v.get('origin', 'package'),
                         mesh=v.get('mesh', v['id']), material=v.get('material', ''), layer=v.get('layer', 0),
                         bounds_source=v.get('bounds_source', 'scenario')) for v in w.get('volumes', [])]
    from .geometry import quat_matrix
    its = []
    for i in w['interactions']:
        i = dict(i); i['pos'] = tuple(i['pos'])
        i['matrix'] = tuple(i['matrix']) if 'matrix' in i else quat_matrix(*i.get('rotate', (1, 0, 0, 0)), position=i['pos'])
        i.setdefault('id', i['name']); i.setdefault('cls', i['kind'])
        its.append(i)
    w['interactions'] = its
    w['roads'] = [dict(r, center=[tuple(p) for p in r['center']]) for r in w['roads']]
    w['extent'] = tuple(w['extent'])
    return w


def _aabb(v):
    from .geometry import box_corners
    c = box_corners(v['matrix'], v['local_min'], v['local_max'])
    return tuple(min(p[a] for p in c) for a in range(3)) + tuple(max(p[a] for p in c) for a in range(3))


def evaluate(report, assertion):
    findings = [f for c in report['checks'] for f in c['findings'] if c['status'] != 'INFO' or assertion.get('include_source')]
    if 'check' in assertion:
        c = next((c for c in report['checks'] if c['name'] == assertion['check']), None)
        if c is None: return dict(assertion, passed=False, actual='missing check')
        return dict(assertion, passed=c['status'] == assertion['status'], actual=c['status'])
    sel = [f for f in findings if f['category'] == assertion['category']
           and ('severity' not in assertion or f['severity'] == assertion['severity'])]
    if 'near' in assertion:
        x, y = assertion['near']; r = assertion.get('within', 1.0)
        sel = [f for f in sel if math.hypot(f['x']-x, f['y']-y) <= r]
    if 'count' in assertion:
        lo, hi = assertion['count'].get('min', 0), assertion['count'].get('max', math.inf)
        return dict(assertion, passed=lo <= len(sel) <= hi, actual=len(sel))
    want = assertion.get('expect', 'present') == 'present'
    return dict(assertion, passed=bool(sel) == want, actual=len(sel))


def run_scenario(scenario, base=Path('.')):
    name = scenario.get('name', 'scenario')
    try:
        if 'world' in scenario: world = normalize_world(scenario['world'])
        else:
            world = load_package(base / scenario['package'], scenario.get('target'), scenario.get('kcd1'))
        report = audit(world, scenario.get('assumptions'))
    except Unsupported as exc:
        return dict(name=name, status='UNSUPPORTED', error=str(exc), assertions=[])
    except Exception as exc:  # reported, never swallowed into PASS
        return dict(name=name, status='ERROR', error=f'{type(exc).__name__}: {exc}', assertions=[])
    results = [evaluate(report, a) for a in scenario.get('assertions', [])]
    # Package scenarios answer for every check; inline worlds only for the checks
    # (or finding categories) they assert on. Either way UNSUPPORTED never passes.
    every = scenario.get('all_checks', 'world' not in scenario)
    asserted = {a.get('check') for a in scenario.get('assertions', [])}
    cats = {a.get('category') for a in scenario.get('assertions', [])}
    owner = dict(interaction_overlap='interaction_clearance', duplicate_volume='duplicate_volumes',
                 boundary_gap='boundary_closure', boundary_missing='boundary_closure', boundary_disconnected='boundary_closure',
                 road_crosses_barrier='road_crossings', road_blocked='road_crossings', road_reaches_map_edge='road_crossings')
    asserted |= {owner.get(c) for c in cats}
    unsupported = [c['name'] for c in report['checks'] if c['status'] == 'UNSUPPORTED' and (every or c['name'] in asserted)]
    status = ('FAIL' if not all(r['passed'] for r in results) else 'UNSUPPORTED' if unsupported
              else 'PASS' if results else 'UNSUPPORTED')
    return dict(name=name, status=status, assertions=results, unsupported_checks=unsupported,
                error=None if results else 'no assertions', report=report)


def run_file(path):
    path = Path(path)
    return run_scenario(json.loads(path.read_text(encoding='utf-8')), path.parent)
