"""Run the contract checks over a package, optionally against retail statistics."""
from collections import Counter
from datetime import datetime, timezone
import os
from pathlib import Path
import traceback

from . import ERROR, FAIL, REVIEW, UNSUPPORTED, VERSION, checks, materials, native
from .archives import Archives, package_paks
from .report import write_audit


def verdict(results, strict=False):
    statuses = Counter(r['status'] for r in results)
    if statuses[FAIL] or statuses[ERROR]: return 'FAIL'
    if statuses[REVIEW]: return 'REVIEW'
    if statuses[UNSUPPORTED]: return 'INCOMPLETE'
    return 'NO_FINDINGS_IN_MODELLED_SCOPE'


def exit_code(report, strict=False):
    bad = {FAIL, ERROR} | ({REVIEW, UNSUPPORTED} if strict else set())
    return 1 if any(c['status'] in bad for c in report['checks']) else 0


def execute(context, selected=None):
    out = []
    for name, check in checks.CHECK_IDS.items():
        if selected and name not in selected: continue
        try: out.append(check(context).report())
        except Exception as exc:  # A crashed check is an ERROR, never a pass.
            out.append(dict(id=name, title=name, status=ERROR, scope='', counts=[], findings=[
                dict(severity='error', code='check_crashed', subject=name, detail=f'{type(exc).__name__}: {exc}')],
                findings_truncated=0, skipped=[], thresholds=[], details=dict(traceback=traceback.format_exc())))
    return out


def build_report(context, results, package_label, target_info):
    contracts = [dict(id=i, status=UNSUPPORTED, reason=r) for i, r in checks.CONTRACTS]
    return dict(schema=1, tool='asset_lab', version=VERSION, native_runtime_verified=False,
                generated_utc=datetime.now(timezone.utc).isoformat(timespec='seconds'),
                package=dict(path=package_label, archives=context.package.fingerprints,
                             members=len(context.package.members)),
                target=target_info, verdict=verdict(results),
                thresholds=[t for r in results for t in r['thresholds']],
                checks=results, contracts=contracts,
                summary=dict(Counter(r['status'] for r in results)))


def target_summary(stats, cached):
    if stats is None: return None
    return dict(root=stats['root'], fingerprint=stats['fingerprint'], paks=stats['paks'], members=stats['members'],
                from_cache=cached, dds_members=stats['dds']['members'], dds_families=stats['dds']['families']['total'],
                retail_cgf_files=stats['cgf']['files'], retail_materials=stats['materials']['leaves'],
                retail_hlod_levels=sorted(stats['hlod']['levels']))


def run(package, output, target=None, cache=None, selected=None, limit=200, progress=lambda *_: None):
    package = Path(package)
    archives = Archives(package_paks(package), 'package')
    stats = view = None
    cached = False
    if target:
        stats, view, cached = native.load(target, cache, progress)
    context = checks.Context(archives, view, stats, limit)
    try:
        results = execute(context, selected)
        report = build_report(context, results, package.as_posix(), target_summary(stats, cached))
    finally:
        archives.close()
        if view is not None: view.close()
    write_audit(report, output)
    return report


def inventory(package, output_path, target=None):
    """What exists, without a verdict."""
    import json
    archives = Archives(package_paks(package), 'package')
    context = checks.Context(archives, None, None)
    extensions = Counter(os.path.splitext(k)[1] or '(none)' for k in archives.keys())
    families = context.families()
    formats = Counter(x['info']['format'] for x in families if x['info'])
    mats, broken = checks._materials(context)
    report = dict(schema=1, tool='asset_lab', version=VERSION, kind='inventory', package=Path(package).as_posix(),
                  archives=archives.fingerprints, members=len(archives.members), extensions=dict(extensions.most_common()),
                  dds=dict(families=len(families), formats=dict(formats.most_common()),
                           largest_piece_bytes=max((x['piece_bytes'] for x in families), default=0)),
                  materials=dict(leaves=len(mats), xml_errors=len(broken),
                                 shaders=dict(Counter(materials.shader_key(m['shader']) for m in mats).most_common())),
                  hlods=len(archives.members.get('terrain/hlods.dat', [])))
    archives.close()
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    Path(output_path).write_text(json.dumps(report, indent=2), encoding='utf-8')
    return report
