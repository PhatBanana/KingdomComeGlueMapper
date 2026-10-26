"""Standalone developer CLI; never imported by consumer Setup."""
import argparse
import json
from pathlib import Path
import sys


def main(argv=None):
    parser = argparse.ArgumentParser(description='Evaluate converted Storm roles offline, without launching KCD2.')
    sub = parser.add_subparsers(dest='command', required=True)
    for name, text in (('inventory', 'Storm program, tables and souls; no verdict'),
                       ('audit', 'Roles per converted soul, service contracts and findings')):
        p = sub.add_parser(name, help=text)
        p.add_argument('package', type=Path, help='Converted package directory (holding Data/)')
        p.add_argument('--target', type=Path, required=True, help='Retail KCD2 directory (read only)')
        p.add_argument('--output', type=Path, required=True)
        if name == 'audit':
            p.add_argument('--strict', action='store_true', help='Review findings also fail')
            p.add_argument('--native-selfcheck', type=int, default=0, metavar='N',
                           help='Also evaluate the first N native souls to measure unsupported coverage')
    run = sub.add_parser('run', help='Run JSON assertion scenarios')
    run.add_argument('scenarios', type=Path, nargs='+')
    run.add_argument('--output', type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == 'audit':
            from .audit import run as run_audit
            report = run_audit(args.package, args.target, args.output, args.native_selfcheck)
            v = report['verdict']
            print(json.dumps(dict(v, souls=report['souls']['converted'], unsupported=report['unsupported'],
                                  report=str((args.output / 'audit.html').resolve())), indent=2))
            if v['status'] == 'FAIL' or report['unsupported']: return 1
            return 1 if args.strict and v['reviews'] else 0
        if args.command == 'inventory':
            from .mounts import Mounts
            from .program import Program
            from .tables import load
            mounts = Mounts.from_paths(args.package, args.target)
            program, tables = Program(mounts), load(mounts)
            report = dict(schema=1, native_runtime_verified=False, program=program.inventory(),
                          souls=[dict(soul=s.name, file=s.file, **{k: s.get(k) for k in (
                              'soul_archetype_id', 'social_class_id', 'factionName', 'skald_character_name',
                              'voice_group_name')}) for s in tables.souls],
                          table_files={k: v for k, v in tables.files.items()}, provenance=mounts.provenance())
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding='utf-8')
            print(json.dumps(dict(souls=len(tables.souls), sources=sum(t['sources'] for t in report['program']['tasks']),
                                  report=str(args.output.resolve()))))
            return 0
        from .report import write_runs
        from .runner import run_file
        results = [r for p in args.scenarios for r in run_file(p)]
        write_runs(results, args.output)
        print(json.dumps(dict(results=[dict(name=r['name'], status=r['status']) for r in results],
                              report=str((args.output / 'report.html').resolve())), indent=2))
        return 0 if all(r['status'] == 'PASS' for r in results) else 1
    except (FileNotFoundError, OSError) as exc:
        print('storm_lab could not run: %s' % exc, file=sys.stderr)
        return 2


if __name__ == '__main__': raise SystemExit(main())
