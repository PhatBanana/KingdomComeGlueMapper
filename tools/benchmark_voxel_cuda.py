"""Matched CPU/CUDA house benchmark; never installs or overwrites world tiles."""
import argparse
import hashlib
import json
from pathlib import Path
import time
import numpy as np
from geometry_opacity import Assets
from voxel_surfaces import load_scene, build_tile


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--manifest',type=Path,required=True)
    p.add_argument('--pak-root',type=Path,required=True)
    p.add_argument('--report',type=Path,required=True)
    p.add_argument('--accepted',type=Path)
    p.add_argument('--gpu',choices=('cuda','optix'),default='cuda')
    a=p.parse_args()
    t,u,i,m,_=load_scene(json.loads(a.manifest.read_text()),Assets(a.pak_root))
    origin=(np.floor(t.min((0,1))/256)*256).astype(int)
    stem='_'.join(f'{int(x):04d}' for x in (* (origin+128),256))
    rows=[];reference=None
    for backend in ('compiled',a.gpu,'compiled',a.gpu):
        start=time.perf_counter();idx,vox,_=build_tile(t,u,i,m,origin,backend=backend)
        row={'backend':backend,'seconds':time.perf_counter()-start,'sha256':hashlib.sha256(idx+vox).hexdigest()}
        if reference is None:reference=(idx,vox)
        row['cpu_bytes_equal']=(idx,vox)==reference
        if a.accepted:row['accepted_bytes_equal']=(idx,vox)==tuple((a.accepted/(stem+s)).read_bytes() for s in ('.idx','.vox'))
        rows.append(row);print(json.dumps(row),flush=True)
    a.report.parent.mkdir(parents=True,exist_ok=True)
    a.report.write_text(json.dumps({'triangles':len(t),'materials':len(m),'runs':rows},indent=2)+'\n')
    if not all(r['cpu_bytes_equal'] and r.get('accepted_bytes_equal',True) for r in rows):raise SystemExit('Backend output mismatch')


if __name__=='__main__':main()
