"""Matched offline GPU batch experiments, retaining failures and byte comparisons."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--scene',type=Path,required=True)
    p.add_argument('--origin',type=int,nargs=3,required=True)
    p.add_argument('--reference',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True)
    p.add_argument('--hardware',action='store_true',help='Include non-parity experimental hardware triangles')
    a=p.parse_args()
    if a.output.exists():p.error('Use a fresh benchmark output directory')
    a.output.mkdir(parents=True)
    stem='_'.join(f'{v:04d}' for v in [*(x+128 for x in a.origin),256])
    reference=[(a.reference/(stem+e)).read_bytes() for e in ('.idx','.vox')]
    variants=[(f'batch{n}',n,1,0,0,0) for n in (8,16,32,64)]
    variants += [('serial32',32,0,0,0,0),('async32',32,1,1,0,0),('graphs32',32,1,1,1,0)]
    if a.hardware:variants.append(('triangles32',32,1,0,0,1))
    results=[]
    for name,batch,pipeline,async_copy,graphs,hardware in variants:
        env=dict(os.environ)
        for key,value in [('GPU_BATCH',batch),('GPU_PIPELINE',pipeline),('GPU_ASYNC',async_copy),('GPU_GRAPHS',graphs),('OPTIX_TRIANGLES',hardware)]:env['GLUEMAPPER_'+key]=str(value)
        folder=a.output/name
        cmd=[sys.executable,str(Path(__file__).with_name('world_surface_tiles.py')),'--scene',str(a.scene),'--origin',*[str(v) for v in a.origin],'--experimental-base-materials','--backend','optix','--output',str(folder)]
        run=subprocess.run(cmd,env=env,capture_output=True,text=True)
        (a.output/(name+'.log')).write_text(run.stdout+run.stderr)
        path=folder/(stem+'.json')
        r=json.loads(path.read_text()) if path.exists() else {}
        equal=run.returncode==0 and all((folder/(stem+e)).read_bytes()==blob for e,blob in zip(('.idx','.vox'),reference))
        result={'variant':name,'returncode':run.returncode,'seconds':r.get('seconds'),'voxel_seconds':r.get('voxel_seconds'),'preparation_seconds':r.get('preparation_seconds'),'byte_identical':equal,'experimental_hardware':bool(hardware),'error':r.get('error'),'gpu_config':r.get('gpu_config')}
        results.append(result);(a.output/'comparison.json').write_text(json.dumps(results,indent=2)+'\n')
        print(json.dumps(result),flush=True)
    if any(r['returncode'] or (not r['byte_identical'] and not r['experimental_hardware']) for r in results):raise SystemExit(1)


if __name__=='__main__':main()
