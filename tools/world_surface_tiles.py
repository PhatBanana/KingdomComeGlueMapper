"""Build resumable, audited static-brush surface tiles from a scene plan.

This is an intermediate builder. A plan with pending geometry categories is
not a publishable world replacement. Failed materials/tiles are recorded and
never silently replaced with white surfaces or empty voxel files.
"""
import argparse
from collections import OrderedDict
import hashlib
import json
import os
from pathlib import Path
import time
import xml.etree.ElementTree as ET

import numpy as np

from geometry_opacity import Assets, transform_triangles
from voxel_surfaces import load_surface, build_tile
from voxel_lighting import validate_pair


class TextureCache(OrderedDict):
    """Bound decoded-texture retention independently of temporary surfaces."""
    def __init__(self,limit=512*1024**2):super().__init__();self.limit=limit
    def __setitem__(self,key,value):
        super().__setitem__(key,value)
        while len(self)>1 and sum(x.nbytes for x in self.values())>self.limit:self.popitem(last=False)
    def __getitem__(self,key):
        value=super().__getitem__(key);self.move_to_end(key);return value


class MeshCache(OrderedDict):
    """Retain decoded shared meshes across tiles within a fixed memory budget."""
    def __init__(self,limit=512*1024**2):super().__init__();self.limit=limit;self.bytes=0
    def __getitem__(self,key):
        value=super().__getitem__(key);self.move_to_end(key);return value
    def __setitem__(self,key,value):
        size=sum(a.nbytes for a in value[1:])
        if key in self:self.bytes-=sum(a.nbytes for a in super().__getitem__(key)[1:])
        super().__setitem__(key,value);self.bytes+=size
        while len(self)>1 and self.bytes>self.limit:
            _,old=self.popitem(last=False);self.bytes-=sum(a.nbytes for a in old[1:])


def code_digest():
    h=hashlib.sha256()
    for name in ('world_surface_tiles.py','voxel_surfaces.py','voxel_raster_fast.py','voxel_raster_cuda.py','voxel_raster_cuda.cu','voxel_optix_shared.h','voxel_optix_device.cu','voxel_optix_host.h','geometry_opacity.py'):
        h.update(Path(__file__).with_name(name).read_bytes())
    return h.hexdigest()


def build(scene, *, only_origin=None, samples=2, experimental_base_materials=False, backend='compiled', output=None,workers=1,start_index=1):
    if os.environ.get('GLUEMAPPER_OPTIX_TRIANGLES')=='1' and output is None:
        raise ValueError('Experimental hardware triangles require an isolated --output directory; boundary parity is not established')
    scene=Path(scene); plan=json.loads((scene/'plan.json').read_text())
    if plan['errors']:raise ValueError('Resolve scene geometry errors before baking')
    for name,digest in plan['source_packages'].items():
        if hashlib.sha256(Path(name).read_bytes()).hexdigest()!=digest:raise ValueError('Scene packages changed; regenerate plan')
    records=json.loads((scene/'placements.json').read_text())
    assets=Assets(plan['pak_root'],plan['overrides']); texture_cache=TextureCache(); roots={};mesh_cache=MeshCache()
    destination=Path(output) if output is not None else scene/'tiles';destination.mkdir(parents=True,exist_ok=True)
    jobs=plan['tiles']
    if not 1<=start_index<=len(jobs):raise ValueError('Start index outside scene plan')
    jobs=jobs[start_index-1:]
    if only_origin is not None:jobs=[j for j in jobs if j['origin']==list(only_origin)]
    if not jobs:raise ValueError('No tiles selected')
    results=[]; version=code_digest();asset_digest=assets.catalog_digest()
    if plan.get('asset_catalog_digest')!=asset_digest:
        raise ValueError('Asset catalog changed or was not fingerprinted; regenerate scene and landscape plan')
    for number,job in enumerate(jobs):
        origin=job['origin'];stem='_'.join(f'{v:04d}' for v in [*(x+128 for x in origin),256])
        report_path=destination/(stem+'.json'); start=time.time()
        # Include the scene bytes, placement IDs and conversion policy in each
        # resume signature. A changed decoder or instance invalidates the tile.
        gpu_config={k:os.environ.get(k,default) for k,default in [('GLUEMAPPER_GPU_BATCH','64'),('GLUEMAPPER_GPU_PIPELINE','1'),('GLUEMAPPER_OPTIX_TRIANGLES','0'),('GLUEMAPPER_GPU_ASYNC','0'),('GLUEMAPPER_GPU_GRAPHS','0')]}
        digest=hashlib.sha256(json.dumps([version,asset_digest,plan['source_packages'],job,samples,experimental_base_materials,backend,gpu_config]).encode()).hexdigest()
        if report_path.exists():
            old=json.loads(report_path.read_text())
            if old.get('signature')==digest and old.get('status')=='built':
                idx=(destination/(stem+'.idx')).read_bytes(); vox=(destination/(stem+'.vox')).read_bytes()
                validate_pair(idx,vox)
                if hashlib.sha256(idx+vox).hexdigest()==old['sha256']:
                    results.append(old);print(f'Tile {number+1}/{len(jobs)} {stem}: verified existing',flush=True);continue
        audit={'tile':stem,'origin':origin,'signature':digest,'status':'failed','placements':len(job['placements']),'requested_backend':backend,'workers':workers}
        audit['gpu_config']=gpu_config
        try:
            triangles=[];uvs=[];ids=[];materials=[];mapping={};material_audit=[]
            for record_id in job['placements']:
                record=records[record_id];key=record['cache_key']
                if key not in mesh_cache:
                    meta=json.loads((scene/'meshes'/(key+'.json')).read_text())
                    with np.load(scene/'meshes'/(key+'.npz')) as data:
                        mesh_cache[key]=(meta,data['triangles'],data['uv'],data['ids'])
                meta,tris,uv,local_ids=mesh_cache[key]
                world=transform_triangles(tris,record['transform'])
                low=world.min(1); high=world.max(1)
                hit=np.all(high>=origin,axis=1)&np.all(low<np.asarray(origin)+256,axis=1)
                if not hit.any():continue
                remap=np.zeros(len(meta['bindings']),dtype=np.int32)
                for local in np.unique(local_ids[hit]):
                    name,subset=meta['bindings'][local];identity=(name,subset)
                    if identity not in mapping:
                        if name not in roots:
                            roots[name]=ET.fromstring(assets.get(name if name.endswith('.mtl') else name+'.mtl'))
                        root=roots[name];subs=root.find('SubMaterials');selected=subset if subs is not None else 0
                        subs=list(subs) if subs is not None else [root]
                        if selected>=len(subs):raise ValueError('Subset outside material: '+str(identity))
                        try:material,limits=load_surface(subs[selected],assets,texture_cache,experimental_base=experimental_base_materials)
                        except ValueError as e:raise ValueError(str(identity)+': '+str(e)) from e
                        if limits and material.coverage and not experimental_base_materials:
                            raise ValueError('Layered shader requires explicit base-material policy: '+str(identity))
                        mapping[identity]=len(materials);materials.append(material)
                        material_audit.append({'material':name,'subset':subset,'limitations':limits})
                    remap[local]=mapping[identity]
                triangles.append(world[hit]);uvs.append(uv[hit]);ids.append(remap[local_ids[hit]])
            triangles=np.concatenate(triangles) if triangles else np.empty((0,3,3))
            uvs=np.concatenate(uvs) if uvs else np.empty((0,3,2))
            ids=np.concatenate(ids) if ids else np.empty(0,dtype=np.int32)
            audit['preparation_seconds']=time.time()-start
            raster_start=time.perf_counter()
            # Conservative crossover between the measured small house (25k)
            # and dense scene (10.5m). It is a policy, not universal autotuning.
            selected=('optix' if len(triangles)>=1_000_000 else 'compiled') if backend=='auto' else backend
            fallback=None
            try:
                idx,vox,validation=build_tile(triangles,uvs,ids,materials,origin,samples=samples,backend=selected,allow_empty=True,workers=workers if selected=='compiled' else 1)
            except (RuntimeError,MemoryError,OSError) as error:
                if backend!='auto' or selected!='optix':raise
                fallback=f'{type(error).__name__}: {error}'
            if fallback is not None:
                # Leave the exception scope first so failed GPU staging arrays
                # can be released before allocating the CPU fallback.
                import gc
                gc.collect();selected='compiled';audit['gpu_fallback_reason']=fallback
                print('OptiX unavailable for '+stem+'; using CPU: '+fallback,flush=True)
                idx,vox,validation=build_tile(triangles,uvs,ids,materials,origin,samples=samples,backend=selected,allow_empty=True,workers=workers)
            audit['backend']=selected
            audit['voxel_seconds']=time.perf_counter()-raster_start
            for suffix,blob in (('.idx',idx),('.vox',vox)):
                temporary=destination/(stem+suffix+'.tmp');temporary.write_bytes(blob);temporary.replace(destination/(stem+suffix))
            audit.update(status='built',triangles=len(triangles),materials=material_audit,validation=validation,
                         empty=not validation['blocks'],sha256=hashlib.sha256(idx+vox).hexdigest())
        except (ValueError,KeyError,FileNotFoundError,RuntimeError,MemoryError) as e:
            audit['error']=str(e)
        audit['seconds']=round(time.time()-start,3)
        temporary=report_path.with_suffix('.json.tmp');temporary.write_text(json.dumps(audit,indent=2)+'\n');temporary.replace(report_path)
        results.append(audit)
        summary={'status':'intermediate static-brush conversion; not installable',
                 'pending_categories':plan['pending_categories'],'selected_tiles':len(jobs),
                 'start_index':start_index,'total_scene_tiles':len(plan['tiles']),
                 'processed_tiles':len(results),'built':sum(r['status']=='built' for r in results),
                 'failed':[{'tile':r['tile'],'error':r['error']} for r in results if r['status']!='built']}
        ((destination if output is not None else scene)/'build-progress.json').write_text(json.dumps(summary,indent=2)+'\n')
        print(f'Tile {number+1}/{len(jobs)} {stem}: {audit["status"]} ({audit["seconds"]}s) '+audit.get('error',''),flush=True)
    return results


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--scene',type=Path,required=True)
    p.add_argument('--origin',nargs=3,type=int)
    p.add_argument('--samples',type=int,choices=(1,2,4,8),default=2)
    p.add_argument('--experimental-base-materials',action='store_true')
    p.add_argument('--backend',choices=('compiled','cuda','optix','auto'),default='compiled')
    p.add_argument('--workers',type=int,choices=(1,2,3,4),default=1,help='Concurrent CPU bricks (bounded queue; shared textures)')
    p.add_argument('--start-index',type=int,default=1,help='One-based plan tile to start a separately recorded continuation')
    p.add_argument('--output',type=Path,help='Separate tile/report destination for backend comparisons')
    args=p.parse_args();results=build(args.scene,only_origin=args.origin,samples=args.samples,
                            experimental_base_materials=args.experimental_base_materials,backend=args.backend,output=args.output,workers=args.workers,start_index=args.start_index)
    if any(r['status']!='built' for r in results):raise SystemExit(1)


if __name__=='__main__':main()
