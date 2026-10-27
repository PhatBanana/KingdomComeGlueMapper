"""JSON scenarios: build a package from generated members and assert on the check results."""
import base64
import json
from pathlib import Path

from . import ERROR, FAIL, PASS, checks, native, synth
from .archives import Archives, package_paks
from .audit import execute


def build_members(spec):
    blobs = {}
    for path, item in spec.items():
        if 'text' in item: blobs[path] = item['text'].encode('utf-8')
        elif 'base64' in item: blobs[path] = base64.b64decode(item['base64'])
        elif 'dds' in item:
            d = item['dds']
            family = synth.make_family(d['width'], d['height'], d.get('format', 'BC7'), d.get('mips'),
                                       d.get('streamed', 0), d.get('payload', True))
            blobs.update(synth.blobs(path, family))
        else: raise ValueError(f'Member {path}: expected text, base64 or dds')
    return blobs


def run_scenario(data, base=Path('.')):
    if 'package' in data: package = Archives(package_paks(base / data['package']), 'package')
    else: package = Archives.blobs(build_members(data.get('members', {})), 'scenario')
    stats = view = None
    if 'target' in data:
        contract = dict(data['target'].get('contract') or {})
        if not contract: raise ValueError('target needs an explicit non-empty "contract" object (retail statistics)')
        stats = native.synthetic(contract.pop('max_member_bytes', 67108864), **contract)
        view = Archives.blobs(build_members(data.get('native_members', {})), 'contract')
    context = checks.Context(package, view, stats)
    selected = data.get('checks')
    unknown = set(selected or ()) - set(checks.CHECK_IDS)
    if unknown: raise ValueError('Unknown checks: ' + ', '.join(sorted(unknown)))
    results = {r['id']: r for r in execute(context, selected)}
    assertions = []
    for want in data.get('assertions', []):
        got = results.get(want['check'])
        if got is None:
            assertions.append(dict(label=f'{want["check"]} ran', ok=False, observed='check was not selected'))
            continue
        codes = {f['code'] for f in got['findings']} | {c['code'] for c in got['counts']}
        ok = True
        if 'status' in want and got['status'] != want['status']: ok = False
        if not set(want.get('codes_include', ())) <= codes: ok = False
        if set(want.get('codes_exclude', ())) & codes: ok = False
        label = want.get('label') or f'{want["check"]} is {want.get("status", "as stated")}'
        assertions.append(dict(label=label, ok=ok, observed=dict(status=got['status'], codes=sorted(codes),
                                                                  skipped=got['skipped'])))
    if not assertions: raise ValueError('Scenario has no assertions')
    return dict(name=data.get('name', 'unnamed'), status=PASS if all(a['ok'] for a in assertions) else FAIL,
                assertions=assertions, checks=list(results.values()))


def run_file(path):
    path = Path(path)
    try:
        data = json.loads(path.read_text(encoding='utf-8'))
        return run_scenario(data, path.parent)
    except Exception as exc:
        return dict(name=path.stem, status=ERROR, error=f'{type(exc).__name__}: {exc}', assertions=[], checks=[])
