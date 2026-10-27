"""Standalone developer CLI; never imported by consumer Setup."""
import argparse
import json
from pathlib import Path

from . import checks
from .audit import exit_code, inventory, run as run_audit
from .report import write_run
from .scenario import run_file


def main(argv=None):
    parser = argparse.ArgumentParser(description='Check converted render/stream assets against retail-derived contracts without launching KCD2.')
    sub = parser.add_subparsers(dest='command', required=True)
    inv = sub.add_parser('inventory', help='List what a package holds (no verdict)')
    inv.add_argument('package', type=Path, help='Mod folder with Data/*.pak, or one .pak')
    inv.add_argument('--output', type=Path, required=True, help='JSON file to write')
    audit = sub.add_parser('audit', help='Run every contract check and write JSON, HTML and JUnit reports')
    audit.add_argument('package', type=Path, help='Mod folder with Data/*.pak, or one .pak')
    audit.add_argument('--target', type=Path, help='Retail KCD2 install; thresholds are derived from it. Without it, native-dependent checks are UNSUPPORTED')
    audit.add_argument('--native-cache', type=Path, help='JSON cache of retail statistics, reused while the install is unchanged')
    audit.add_argument('--check', action='append', choices=sorted(checks.CHECK_IDS), help='Limit to these checks (repeatable)')
    audit.add_argument('--max-findings', type=int, default=200, help='Findings listed per check; counts stay exact')
    audit.add_argument('--strict', action='store_true', help='Also exit 1 for review findings and UNSUPPORTED checks')
    audit.add_argument('--output', type=Path, required=True)
    run = sub.add_parser('run', help='Run JSON scenarios that assert on check results')
    run.add_argument('scenarios', type=Path, nargs='+')
    run.add_argument('--output', type=Path, required=True)
    args = parser.parse_args(argv)
    if args.command == 'inventory':
        report = inventory(args.package, args.output)
        print(json.dumps(dict(members=report['members'], dds_families=report['dds']['families'],
                              materials=report['materials']['leaves'], report=str(args.output.resolve())), indent=2))
        return 0
    if args.command == 'run':
        reports = [run_file(p) for p in args.scenarios]
        write_run(reports, args.output)
        print(json.dumps(dict(results=[dict(name=r['name'], status=r['status'], error=r.get('error')) for r in reports],
                              report=str((args.output / 'report.html').resolve())), indent=2))
        return 0 if all(r['status'] == 'PASS' for r in reports) else 1
    report = run_audit(args.package, args.output, args.target, args.native_cache, args.check, args.max_findings,
                       progress=lambda stage: print('retail baseline:', stage, flush=True))
    print(json.dumps(dict(verdict=report['verdict'], summary=report['summary'], unsupported_contracts=len(report['contracts']),
                          report=str((args.output / 'audit.html').resolve())), indent=2))
    return exit_code(report, args.strict)


if __name__ == '__main__': raise SystemExit(main())
