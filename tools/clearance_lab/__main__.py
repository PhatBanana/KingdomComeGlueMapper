"""Standalone developer CLI; never imported by consumer Setup.

Exit codes: 0 everything passed; 1 FAIL/UNSUPPORTED/ERROR (and REVIEW with
--strict); 2 the input could not be read at all.
"""
import argparse
import json
from pathlib import Path

from . import Unsupported


def main(argv=None):
    parser = argparse.ArgumentParser(description='Interaction clearance and boundary walk check (offline).')
    sub = parser.add_subparsers(dest='command', required=True)
    for name, text in (('inventory', 'List designer volumes, interactions and roads (no verdict)'),
                       ('audit', 'Check every interaction, duplicate, the boundary ring and road crossings')):
        p = sub.add_parser(name, help=text)
        p.add_argument('package', type=Path, help='Finished package (folder containing Data/ or the Data folder)')
        p.add_argument('--target', type=Path, required=True, help='KCD2 install (native SurfaceTypes.xml and proxy .mtl)')
        p.add_argument('--kcd1', type=Path, help='Optional KCD1 install: add the every-source-volume regression reconstruction')
        p.add_argument('--no-roads', action='store_true', help='Skip road records (the road check then reports UNSUPPORTED)')
        p.add_argument('--output', type=Path, required=True)
        if name == 'audit': p.add_argument('--strict', action='store_true', help='REVIEW findings also fail')
    run = sub.add_parser('run', help='Run JSON scenarios and write JSON/HTML/JUnit reports')
    run.add_argument('scenarios', type=Path, nargs='+')
    run.add_argument('--output', type=Path, required=True)
    args = parser.parse_args(argv)

    if args.command == 'run':
        from .runner import run_file
        from .report import junit, html
        results = [run_file(p) for p in args.scenarios]
        args.output.mkdir(parents=True, exist_ok=True)
        (args.output/'results.json').write_text(json.dumps(dict(schema=1, native_runtime_verified=False, results=results),
                                                           indent=1, ensure_ascii=False), encoding='utf-8')
        junit([dict(name=r['name'], status=r['status'], message=r.get('error'),
                    detail=[a for a in r['assertions'] if not a['passed']]) for r in results], args.output, 'Clearance scenarios')
        for i, r in enumerate(results):
            if r.get('report'): (args.output/f'scenario-{i:02d}.html').write_text(html(r['report'], r['name']), encoding='utf-8')
        print(json.dumps([dict(name=r['name'], status=r['status'], error=r.get('error')) for r in results], indent=2))
        return 0 if all(r['status'] == 'PASS' for r in results) else 1

    from .source import load_package
    from .audit import audit, inventory
    from .report import write_audit
    try:
        world = load_package(args.package, args.target, args.kcd1, with_roads=not args.no_roads)
    except (Unsupported, OSError, KeyError) as exc:
        print(json.dumps(dict(status='ERROR', error=f'{type(exc).__name__}: {exc}'))); return 2
    if args.command == 'inventory':
        args.output.parent.mkdir(parents=True, exist_ok=True)
        payload = dict(schema=1, source=world['source'], inventory=inventory(world), unsupported=world['unsupported'],
                       surface_table=world['surface_table'], hashes=world['hashes'])
        args.output.write_text(json.dumps(payload, indent=1), encoding='utf-8')
        print(json.dumps(payload['inventory'], indent=1)[:3000]); return 0
    report = audit(world)
    write_audit(report, args.output)
    print(json.dumps(dict(status=report['status'], checks={c['name']: dict(status=c['status'], findings=len(c['findings']))
                                                          for c in report['checks']},
                          report=str((args.output/'report.html').resolve())), indent=2))
    if report['status'] in ('FAIL', 'UNSUPPORTED', 'ERROR'): return 1
    return 1 if (args.strict and report['status'] == 'REVIEW') else 0


if __name__ == '__main__': raise SystemExit(main())
