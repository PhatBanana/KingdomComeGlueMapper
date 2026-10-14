"""Reuse tiles after a GI eligibility-only change, proving decoded inputs equal.

The caller supplies the pre-change builder digest. This deliberately supports
only samples=2, experimental base materials, auto backend, unchanged rasterizer.
Use a fresh scene with regenerated placements/material caches, not edited hashes.
"""
import argparse
import hashlib
import json
from pathlib import Path
import numpy as np
from validate_world_surfaces import digest, stem
from voxel_lighting import validate_pair
from world_surface_tiles import code_digest, gpu_configuration, tile_signature


def vegetation_keys(scene, plan):
    if not plan.get('vegetation'):return []
    path=scene/'vegetation.npz'
    if digest(path)!=plan['vegetation']['sha256']:raise ValueError('Vegetation data changed')
    with np.load(path) as z:
        matrices,groups=z['transforms'],z['groups']
    keys=[]
    for matrix,group in zip(matrices,groups):
        cache=plan['vegetation']['groups'][str(int(group))]['cache_key']
        keys.append(hashlib.sha256(cache.encode()+matrix.tobytes()).digest())
    return keys


def reuse(scene, reference, reference_code):
    scene,reference=Path(scene),Path(reference)
    plan=json.loads((scene/'plan.json').read_text());old=json.loads((reference/'plan.json').read_text())
    for key in ('asset_catalog_digest','pak_root','overrides','landscape_limitations'):
        if plan.get(key)!=old.get(key):raise ValueError('Changed surface inputs: '+key)
    for name,sha in plan['source_packages'].items():
        if digest(name)!=sha:raise ValueError('Current source package changed')
    if digest(scene/'placements.json')!=digest(reference/'placements.json'):
        raise ValueError('Base placements changed; cannot use this reuse path')
    records=json.loads((scene/'placements.json').read_text())
    old_keys=vegetation_keys(reference,old);new_keys=vegetation_keys(scene,plan)
    old_jobs={tuple(j['origin']):j for j in old['tiles']}
    checked=set()
    def check_mesh(key):
        if key in checked:return
        a=reference/'meshes'/key;b=scene/'meshes'/key
        if json.loads(a.with_suffix('.json').read_text())!=json.loads(b.with_suffix('.json').read_text()):
            raise ValueError('Mesh metadata changed: '+key)
        with np.load(a.with_suffix('.npz')) as x,np.load(b.with_suffix('.npz')) as y:
            if set(x.files)!=set(y.files) or any(not np.array_equal(x[k],y[k]) for k in x.files):
                raise ValueError('Decoded mesh changed: '+key)
        checked.add(key)
    for record in records:
        if record.get('cache_key'):check_mesh(record['cache_key'])
    for group in old.get('vegetation',{}).get('groups',{}).values():check_mesh(group['cache_key'])
    destination=scene/'tiles';destination.mkdir(exist_ok=True)
    version=code_digest();config=gpu_configuration();reused=[]
    for job in plan['tiles']:
        previous=old_jobs.get(tuple(job['origin']))
        if previous is None or previous['placements']!=job['placements']:continue
        if sorted(old_keys[i] for i in previous.get('vegetation',[]))!=sorted(new_keys[i] for i in job.get('vegetation',[])):continue
        name=stem(job);src=reference/'tiles';report=json.loads((src/(name+'.json')).read_text())
        expected=tile_signature(reference_code,old['asset_catalog_digest'],old,previous,2,True,'auto',config)
        if report['signature']!=expected or report['status']!='built':
            raise ValueError('Reference builder/configuration not verified: '+name)
        idx=(src/(name+'.idx')).read_bytes();vox=(src/(name+'.vox')).read_bytes();validate_pair(idx,vox)
        if hashlib.sha256(idx+vox).hexdigest()!=report['sha256']:raise ValueError('Reference tile changed')
        if (destination/(name+'.json')).exists():raise FileExistsError(name)
        for suffix in ('.idx','.vox'):(destination/(name+suffix)).hardlink_to(src/(name+suffix))
        report['reuse']={'source':str(src/(name+'.json')),'source_signature':report['signature'],
                         'basis':'GI eligibility-only change; identical decoded meshes, placements, tile vegetation and asset catalog'}
        report['signature']=tile_signature(version,plan['asset_catalog_digest'],plan,job,2,True,'auto',config)
        report['vegetation_instances']=len(job.get('vegetation',[]))
        (destination/(name+'.json')).write_text(json.dumps(report,indent=2)+'\n')
        reused.append(name)
    result={'reused':len(reused),'rebuild':len(plan['tiles'])-len(reused),'reference_code':reference_code,'tiles':reused}
    (scene/'reuse-audit.json').write_text(json.dumps(result,indent=2)+'\n')
    return result


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--scene',type=Path,required=True);p.add_argument('--reference',type=Path,required=True)
    p.add_argument('--reference-code',required=True)
    a=p.parse_args();r=reuse(a.scene,a.reference,a.reference_code)
    print(json.dumps({k:v for k,v in r.items() if k!='tiles'},indent=2),flush=True)
