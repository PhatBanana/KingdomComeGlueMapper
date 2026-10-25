"""Developer-only exhaustive clothing registration/pair audit."""
import argparse
import json
from pathlib import Path
from clothing_lab.catalog import Catalog
from clothing_lab.matrix import run_matrix, run_full_layers
from clothing_lab.repair import build_candidate


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--package',required=True,type=Path)
    parser.add_argument('--target',required=True,type=Path)
    parser.add_argument('--output',required=True,type=Path)
    parser.add_argument('--overlay',type=Path)
    parser.add_argument('--build-layer-candidate',type=Path)
    parser.add_argument('--rules-only',action='store_true')
    parser.add_argument('--full-layers',choices=('Female','Male'))
    parser.add_argument('--resume-from',type=Path,action='append')
    parser.add_argument('--pair-range',type=int,nargs=2,metavar=('START','STOP'))
    args=parser.parse_args()
    if args.pair_range and not 0 <= args.pair_range[0] < args.pair_range[1]:parser.error('Invalid pair range')
    if args.build_layer_candidate:
        report=build_candidate(args.package,args.target,args.build_layer_candidate)
        print(json.dumps(dict(corrected=len(report['corrections']),unresolved=report['unresolved'])),flush=True)
        args.overlay=args.build_layer_candidate
    catalog=Catalog(args.package,args.target,args.overlay)
    progress=lambda value:print(value,flush=True)
    report=(run_full_layers(catalog,args.full_layers,args.output,progress=progress) if args.full_layers
            else run_matrix(catalog,args.output,not args.rules_only,progress,args.resume_from,args.pair_range))
    print(json.dumps(report,indent=2),flush=True)


if __name__=='__main__':main()
