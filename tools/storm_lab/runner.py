"""Assertion scenarios.

A scenario is JSON::

    {"name": "...",
     "package": "<package dir>", "target": "<KCD2 dir>",          # or
     "blobs": {"mod": {"Libs/Storm/storm.xml": "<xml>", ...}, "native": {...}},
     "assertions": [
        {"soul": "rat_pesek", "has_role": "POZDRAV_MUZ"},
        {"soul": "rat_pesek", "lacks_role": "SMLOUVANI_MUZ"},
        {"soul": "rat_pesek", "role_status": {"POZDRAV_MUZ": "DEFINITE"}},
        {"soul": "rato_innkeeper1", "contract": "trade", "status": "PASS"},
        {"finding": "merchant-role-on-non-keeper", "count": 0}]}

has_role passes only for a DEFINITE role; a CONDITIONAL role (fork, unsupported
selector) makes the assertion UNSUPPORTED, never PASS. Relative paths resolve
against the scenario file.
"""
import json
from pathlib import Path

from .audit import run as run_audit
from .mounts import Mounts


def _check(a, report):
    roles = report['roles_by_soul']
    if 'contract' in a:
        rows = [c for c in report['contracts'] if c['contract'] == a['contract'] and c['soul'] == a.get('soul')]
        if not rows: return 'FAIL', 'no %s contract row for %s' % (a['contract'], a.get('soul'))
        actual = rows[0]['status']
        if actual == 'UNSUPPORTED' and a.get('status') != 'UNSUPPORTED': return 'UNSUPPORTED', 'contract is UNSUPPORTED'
        return ('PASS' if actual == a.get('status', 'PASS') else 'FAIL'), 'contract status ' + actual
    if 'finding' in a:
        n = sum(f['kind'] == a['finding'] for f in report['findings'])
        return ('PASS' if n == a.get('count', 0) else 'FAIL'), '%d findings of kind %s' % (n, a['finding'])
    soul = roles.get(a.get('soul'))
    if soul is None: return 'FAIL', 'no converted soul ' + str(a.get('soul'))
    if 'has_role' in a:
        st = soul['roles'].get(a['has_role'])
        if st is None: return 'FAIL', 'role absent'
        if st['status'] != 'DEFINITE': return 'UNSUPPORTED', 'role is conditional on ' + ', '.join(st['deps'])
        return 'PASS', 'role definite'
    if 'lacks_role' in a:
        st = soul['roles'].get(a['lacks_role'])
        if st is None: return 'PASS', 'role absent'
        if st['status'] != 'DEFINITE': return 'UNSUPPORTED', 'role is conditional on ' + ', '.join(st['deps'])
        return 'FAIL', 'role present'
    if 'role_status' in a:
        bad = {r: (soul['roles'].get(r) or {}).get('status', 'ABSENT') for r, want in a['role_status'].items()
               if (soul['roles'].get(r) or {}).get('status', 'ABSENT') != want}
        return ('PASS' if not bad else 'FAIL'), json.dumps(bad)
    return 'UNSUPPORTED', 'unknown assertion ' + json.dumps(a)


def run_scenario(spec, base=Path('.')):
    name = spec.get('name', 'scenario')
    try:
        if 'blobs' in spec:
            mounts = Mounts.blobs(spec['blobs'].get('mod'), spec['blobs'].get('native'))
            report = run_audit(None, None, mounts=mounts)
        else:
            resolve = lambda p: (base / p) if p and not Path(p).is_absolute() else (Path(p) if p else None)
            report = run_audit(resolve(spec.get('package')), resolve(spec.get('target')))
    except Exception as exc:  # report, do not crash the batch
        return dict(name=name, status='ERROR', error='%s: %s' % (type(exc).__name__, exc), assertions=[])
    assertions = []
    for a in spec.get('assertions', []):
        status, detail = _check(a, report)
        assertions.append(dict(a, status=status, detail=detail))
    statuses = {a['status'] for a in assertions}
    status = 'FAIL' if 'FAIL' in statuses else 'UNSUPPORTED' if 'UNSUPPORTED' in statuses else 'PASS'
    if not assertions: status = 'UNSUPPORTED'
    return dict(name=name, status=status, assertions=assertions, verdict=report['verdict'],
                unsupported=report['unsupported'])


def run_file(path):
    path = Path(path)
    spec = json.loads(path.read_text(encoding='utf-8'))
    specs = spec if isinstance(spec, list) else [spec]
    return [run_scenario(s, path.parent) for s in specs]
