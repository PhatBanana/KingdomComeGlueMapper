"""Run via python -m clothing_lab with tools on PYTHONPATH, or clothing_lab_test.py."""
import argparse
import json
from pathlib import Path
from .service import Lab


def main():
    parser=argparse.ArgumentParser(description='Read-only character and clothing validation against packaged KCD2 components.')
    parser.add_argument('--package',required=True,type=Path)
    parser.add_argument('--target',required=True,type=Path,help='KCD2 installation providing native clothing rules')
    parser.add_argument('--source',type=Path,help='KCD1 installation, required for all source souls')
    parser.add_argument('--overlay',type=Path,help='Separate developer candidate layered over the package')
    parser.add_argument('--mode',choices=('presets','souls','singles','pairs','layers'),default='presets')
    parser.add_argument('--body',help='Character preset ID for custom combinations')
    parser.add_argument('--gender',choices=('All','Male','Female'),default='All')
    parser.add_argument('--geometry',action='store_true',help='Also run opaque-surface and penetration diagnostics')
    parser.add_argument('--lod',type=int,default=0,choices=range(5))
    parser.add_argument('--limit',type=int,default=1000)
    parser.add_argument('--offset',type=int,default=0)
    parser.add_argument('--reports',type=Path,default=Path('reports/clothing-lab'))
    parser.add_argument('--strict',action='store_true',help='Fail for review findings, incomplete coverage, or unconverted source souls too')
    args=parser.parse_args()
    if args.mode=='souls' and not args.source: parser.error('--source is required for souls')
    lab=Lab(args.reports); lab.open(args.package,args.target,args.overlay)
    options={k:str(v) if isinstance(v,Path) else v for k,v in vars(args).items()}
    lab.run(options);lab.worker.join()
    state=lab.poll();print(json.dumps({k:v for k,v in state.items() if k!='results'},indent=2))
    if state.get('error'): return 2
    report=json.loads(Path(state['report']).read_text())
    if any(r['status'] in ('error','source_error') for r in report['results']): return 1
    if args.strict and (not report['complete'] or any(r['status']!='checked' for r in report['results'])): return 1
    return 0


if __name__=='__main__': raise SystemExit(main())
