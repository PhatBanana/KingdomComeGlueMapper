"""Build resumable, audited static-brush surface tiles from a scene plan.

This is an intermediate builder. A plan with pending geometry categories is
not a publishable world replacement. Failed materials/tiles are recorded and
never silently replaced with white surfaces or empty voxel files.
"""
import argparse
from collections import OrderedDict
from concurrent.futures import FIRST_COMPLETED, ProcessPoolExecutor, wait
from contextlib import ExitStack, nullcontext
import hashlib
import json
import multiprocessing
import os
from pathlib import Path
import time
import xml.etree.ElementTree as ET
import zipfile

import numpy as np

from bounded_pool import available_memory
from geometry_opacity import Assets, transform_triangles
from voxel_surfaces import load_surface, build_tile
from voxel_lighting import validate_pair


class TextureCache(OrderedDict):
    """Bound decoded-texture retention independently of temporary surfaces."""
    def __init__(self,limit=512*1024**2):super().__init__();self.limit=limit;self.bytes=0
    def __setitem__(self,key,value):
        if key in self:self.bytes-=super().__getitem__(key).nbytes
        super().__setitem__(key,value);self.bytes+=value.nbytes
        while len(self)>1 and self.bytes>self.limit:self.bytes-=self.popitem(last=False)[1].nbytes
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
    for name in ('world_surface_tiles.py','voxel_surfaces.py','voxel_raster_fast.py','voxel_raster_cuda.py','voxel_raster_cuda.cu','voxel_optix_shared.h','voxel_optix_device.cu','voxel_optix_host.h','geometry_opacity.py','world_surface_coverage.py'):
        h.update(Path(__file__).with_name(name).read_bytes())
    return h.hexdigest()


def gpu_configuration():
    return {k:os.environ.get(k,default) for k,default in [('GLUEMAPPER_GPU_BATCH','64'),('GLUEMAPPER_GPU_PIPELINE','1'),('GLUEMAPPER_OPTIX_TRIANGLES','0'),('GLUEMAPPER_GPU_ASYNC','0'),('GLUEMAPPER_GPU_GRAPHS','0')]}


def mesh_records(scene,progress=None,cancelled=lambda:False):
    """Every meshes/<key>.json record by key, through one index file.

    A scene has tens of thousands of mesh records and opening each costs a few
    milliseconds: about a minute per pass, paid by tile planning in every bake
    process and by each scene identity. Records are content-keyed, so the index
    is rebuilt whenever the folder's record names disagree with it. The rebuild
    is the one slow pass, so the setup worker indexes a scene once with progress
    and cancellation before the identity check, the planner and the workers read it."""
    scene=Path(scene);folder=scene/'meshes';index=scene/'meshes.json'
    if not folder.is_dir():return {}
    names={entry.name[:-5] for entry in os.scandir(folder) if entry.name.endswith('.json')}
    try:
        records=json.loads(index.read_text())
        if records.keys()==names:return records
    except (OSError,ValueError):pass
    records={}
    for number,name in enumerate(sorted(names)):
        if number%1000==0:
            if cancelled():raise InterruptedError('Cancelled while indexing scene meshes')
            if progress:progress('Index scene meshes',number,len(names),f'{number} of {len(names)} mesh records')
        records[name]=json.loads((folder/(name+'.json')).read_text())
    if progress:progress('Index scene meshes',len(names),len(names),f'{len(names)} mesh records indexed')
    pending=index.with_name(f'meshes.{os.getpid()}.tmp');pending.write_text(json.dumps(records));pending.replace(index)
    return records


def mesh_triangles(scene):
    return {key:record['triangles'] for key,record in mesh_records(scene).items() if isinstance(record.get('triangles'),int)}


def tile_signature(version,asset_digest,plan,job,samples,experimental_base_materials,backend,gpu_config):
    return hashlib.sha256(json.dumps([version,asset_digest,plan['source_packages'],plan.get('vegetation'),job,samples,experimental_base_materials,backend,gpu_config]).encode()).hexdigest()


def _bounded_setting(name,default,low,high):
    value=os.environ.get(name,str(default))
    if not value.isdigit() or not low<=int(value)<=high:raise ValueError(f'{name} must be {low}..{high}')
    return int(value)


GIB=1024**3
# Measured on a 64 GB machine (1,220-tile buildings bake): the setup worker itself holds about
# 10 GB during the bake, a tile process averages about 5 GB, and one preparing a dense tile
# peaked at 17 GB. Two dense tiles at once need room for both beside the worker.
WORKER_RESERVE=12*GIB;TILE_PROCESS=5*GIB;TWO_DENSE_TILES=40*GIB


def tile_workers(workers,available=None):
    """Concurrent tile processes, each running `workers` brick threads (24 threads: 6 tiles x 2 bricks),
    limited by the memory free when the bake starts."""
    default=max(1,min(6,(os.cpu_count() or 1)//(workers+1)))
    free=available_memory() if available is None else available
    if free is not None:default=max(1,min(default,int((free-WORKER_RESERVE)//TILE_PROCESS)))
    return _bounded_setting('GLUEMAPPER_BAKE_TILE_WORKERS',default,1,32)


def brick_threads(processes):
    """Brick threads per tile process: the cores the memory-limited process count leaves.

    Threads share their process's memory, so on a machine with little RAM (one or two
    tile processes) they keep every core busy without the memory another process needs.
    The rasterizer releases the GIL; tile bytes do not depend on the count (ordered bricks).
    Measured on the KCD1 scene (24 sampled CPU tiles, one process): voxel time 58 s at 2 threads,
    35 s at 4, 30 s at 8 and 30 s at 12, so the default stops at 8."""
    from voxel_surfaces import MAX_BRICK_WORKERS
    default=max(2,min(8,(os.cpu_count() or 1)//max(1,processes)))
    return _bounded_setting('GLUEMAPPER_BAKE_BRICK_WORKERS',default,1,MAX_BRICK_WORKERS)


def gpu_lanes():
    """Tiles rasterized on the GPU at the same time."""
    return _bounded_setting('GLUEMAPPER_GPU_LANES',1,1,4)


def heavy_slots(available=None):
    """Dense tiles held in memory at once. Gathering a dense tile's triangles stages several GB,
    so the limit covers preparation as well as rasterization; one slot unless two fit."""
    free=available_memory() if available is None else available
    return _bounded_setting('GLUEMAPPER_BAKE_HEAVY_TILES',2 if free is None or free>=TWO_DENSE_TILES else 1,1,8)


LIGHT_TEXTURE_CACHE=512*1024**2


def dense_texture_cache(available=None):
    """Decoded-texture cache of each dense-tile process, in bytes: an eighth of the memory free
    when the bake starts, between 512 MiB and 6 GiB. One dense KCD1 tile binds 4-6 GB of decoded
    textures and its materials hold them while it rasterizes, so a cache about that size adds
    little to the process's peak; 512 MiB re-decoded every texture of every dense tile."""
    free=available_memory() if available is None else available
    default=8*LIGHT_TEXTURE_CACHE if free is None else min(6*GIB,max(LIGHT_TEXTURE_CACHE,free//8))
    return _bounded_setting('GLUEMAPPER_BAKE_DENSE_TEXTURE_MB',default//2**20,1,64*1024)*2**20


HEAVY_TRIANGLES=1_000_000  # the hybrid crossover; estimates at or above it go to the dense processes
# Measured on the KCD1 scene (RTX 5090, one tile at a time): OptiX tiles took 2.0 GB more GPU memory
# at 1.0M triangles and 12.3 GB at 18.6M, about 2 GB of textures plus 690 bytes per triangle.
OPTIX_BASE=2*GIB;OPTIX_TRIANGLE=704;VRAM_RESERVE=GIB


def gpu_free_memory():
    """Free memory of the NVIDIA GPU in bytes from the driver's NVML library, or None when unknown.
    With several GPUs the smallest free amount is used, since CUDA may order devices differently."""
    import ctypes
    try:
        nvml=ctypes.CDLL('nvml.dll' if os.name=='nt' else 'libnvidia-ml.so.1')
        # Resolve every entry point before initialization. A partial/older driver
        # must retain the normal try-GPU/fallback path, not abort the whole bake.
        initialize=nvml.nvmlInit_v2;shutdown=nvml.nvmlShutdown
        get_count=nvml.nvmlDeviceGetCount_v2;get_handle=nvml.nvmlDeviceGetHandleByIndex_v2
        get_memory=nvml.nvmlDeviceGetMemoryInfo
    except (OSError,AttributeError):return None
    class Memory(ctypes.Structure):_fields_=[('total',ctypes.c_ulonglong),('free',ctypes.c_ulonglong),('used',ctypes.c_ulonglong)]
    if initialize():return None
    try:
        count=ctypes.c_uint()
        if get_count(ctypes.byref(count)) or not count.value:return None
        free=[]
        for index in range(count.value):
            device=ctypes.c_void_p();memory=Memory()
            if get_handle(index,ctypes.byref(device)) or get_memory(device,ctypes.byref(memory)):return None
            free.append(memory.free)
        return min(free)
    finally:shutdown()


def gpu_budget(lanes,free=None):
    """GPU memory one lane may use, from the memory free when the bake starts; None when unknown."""
    free=gpu_free_memory() if free is None else free
    return None if free is None else max(0,free-VRAM_RESERVE)//lanes


def select_backend(backend,triangles,budget):
    """Backend for one tile and why OptiX was skipped. Dense tiles go to OptiX only when their
    estimated GPU memory fits the lane's budget, so small cards do not fail late and redo the tile."""
    if backend!='auto':return backend,None
    if triangles<1_000_000:return 'compiled',None
    need=OPTIX_BASE+OPTIX_TRIANGLE*triangles
    if budget is not None and need>budget:
        return 'compiled',f'needs about {need/GIB:.1f} GiB of GPU memory; {budget/GIB:.1f} GiB free per GPU lane'
    return 'optix',None


class _TriangleEstimate:
    """Mesh-header triangle counts for a scene; shared by the bake workers and the submitting process."""
    def __init__(self,scene,plan):
        self.scene=Path(scene);self.plan=plan;self.records=json.loads((self.scene/'placements.json').read_text())
        self.vegetation=None;self.mesh_triangles=mesh_triangles(self.scene)
        if plan.get('vegetation'):
            with np.load(self.scene/'vegetation.npz') as data:self.vegetation=(None,data['groups'])

    def estimated_triangles(self,job):
        """Upper bound on a tile's triangles (whole meshes, before clipping), read from array headers only."""
        def count(key):
            if key not in self.mesh_triangles:
                with zipfile.ZipFile(self.scene/'meshes'/(key+'.npz')) as archive,archive.open('triangles.npy') as member:
                    version=np.lib.format.read_magic(member)
                    header=np.lib.format.read_array_header_1_0 if version==(1,0) else np.lib.format.read_array_header_2_0
                    self.mesh_triangles[key]=int(header(member)[0][0])
            return self.mesh_triangles[key]
        total=sum(count(self.records[record_id]['cache_key']) for record_id in job['placements'])
        if self.vegetation is not None:
            groups=self.plan['vegetation']['groups']
            total+=sum(count(groups[str(int(self.vegetation[1][record_id]))]['cache_key']) for record_id in job.get('vegetation',[]))
        return total


def dense_split(dense,processes,slots):
    """Processes for dense tiles and for light ones. Dense tiles get their own `slots` processes
    (bounding how many are in memory at once), so no light-tile process waits for a dense slot;
    the light tiles keep the rest of the memory-limited process count."""
    if not any(dense):return 0,processes
    if all(dense):return min(slots,processes),0
    heavy=min(slots,processes-1);return heavy,processes-heavy


def _placement_side(bounds,matrix,origin):
    """True when a placed mesh lies wholly inside the tile, False when wholly outside, None when it
    straddles or the transform is not plainly valid (the per-triangle test and its errors decide).

    The world box of an affine map of the local box bounds every transformed vertex; a 1 mm margin
    covers rounding, so the shortcut gives exactly the per-triangle test's answer."""
    if bounds is None:return None
    matrix=np.asarray(matrix,dtype=np.float64)
    if matrix.size!=12 or not np.isfinite(matrix).all():return None
    matrix=matrix.reshape(3,4);linear=matrix[:,:3]
    if abs(np.linalg.det(linear))<1e-12:return None
    lo,hi=bounds;a=linear*lo;b=linear*hi
    low=matrix[:,3]+np.minimum(a,b).sum(1);high=matrix[:,3]+np.maximum(a,b).sum(1)
    origin=np.asarray(origin,dtype=np.float64);margin=1e-3
    if np.any(high<origin-margin) or np.any(low>=origin+256+margin):return False
    if np.all(low>=origin+margin) and np.all(high<origin+256-margin):return True
    return None


class _TileBaker(_TriangleEstimate):
    """Per-process baking state. Decoded meshes, materials and textures are caches only, so a tile's
    bytes do not depend on which process bakes it or what it baked before."""
    def __init__(self,scene,output,samples,experimental_base_materials,backend,workers,gpu_budget=None,lanes=None,texture_bytes=LIGHT_TEXTURE_CACHE):
        self.scene=Path(scene);self.plan=json.loads((self.scene/'plan.json').read_text())
        self.records=json.loads((self.scene/'placements.json').read_text())
        self.assets=Assets(self.plan['pak_root'],self.plan['overrides']);self.texture_cache=TextureCache(texture_bytes);self.roots={};self.mesh_cache=MeshCache()
        self.mesh_bounds={}  # local vertex box per mesh key: 48 bytes each, kept for the whole bake
        self.destination=Path(output) if output is not None else self.scene/'tiles'
        self.vegetation=None
        if self.plan.get('vegetation'):  # digest verified once by build()
            with np.load(self.scene/'vegetation.npz') as data:self.vegetation=(data['transforms'],data['groups'])
        self.version=code_digest();self.asset_digest=self.assets.catalog_digest()
        self.samples=samples;self.experimental_base_materials=experimental_base_materials;self.backend=backend
        self.workers=workers;self.gpu_budget=gpu_budget;self.lanes=lanes;self.mesh_triangles=mesh_triangles(self.scene)

    def bake(self,number,total,job):
        return self._bake(number,total,job)

    def _bounds(self,key,tris):
        if key not in self.mesh_bounds:
            flat=np.asarray(tris,dtype=np.float64).reshape(-1,3)
            self.mesh_bounds[key]=(flat.min(0),flat.max(0)) if len(flat) and np.isfinite(flat).all() else None
        return self.mesh_bounds[key]

    def _bake(self,number,total,job):
        scene,plan,records,assets=self.scene,self.plan,self.records,self.assets
        texture_cache,roots,mesh_cache,destination,vegetation=self.texture_cache,self.roots,self.mesh_cache,self.destination,self.vegetation
        version,asset_digest=self.version,self.asset_digest
        samples,experimental_base_materials,backend,workers=self.samples,self.experimental_base_materials,self.backend,self.workers
        origin=job['origin'];stem='_'.join(f'{v:04d}' for v in [*(x+128 for x in origin),256])
        report_path=destination/(stem+'.json'); start=time.time()
        # Include the scene bytes, placement IDs and conversion policy in each
        # resume signature. A changed decoder or instance invalidates the tile.
        gpu_config=gpu_configuration()
        digest=tile_signature(version,asset_digest,plan,job,samples,experimental_base_materials,backend,gpu_config)
        if report_path.exists():
            try:
                old=json.loads(report_path.read_text())
                if old.get('signature')==digest and old.get('status')=='built':
                    idx=(destination/(stem+'.idx')).read_bytes();vox=(destination/(stem+'.vox')).read_bytes()
                    validate_pair(idx,vox)
                    if hashlib.sha256(idx+vox).hexdigest()==old['sha256']:
                        print(f'Tile {number+1}/{total} {stem}: verified existing',flush=True);return old
            except (OSError,ValueError,KeyError):
                print(f'Tile {number+1}/{total} {stem}: incomplete checkpoint; rebuilding',flush=True)
        audit={'tile':stem,'origin':origin,'signature':digest,'status':'failed','placements':len(job['placements']),'requested_backend':backend,'workers':workers}
        audit['gpu_config']=gpu_config
        try:
            triangles=[];uvs=[];ids=[];materials=[];mapping={};material_audit=[]
            def selected_records():
                for record_id in job['placements']:yield records[record_id]
                for record_id in job.get('vegetation',[]):
                    if vegetation is None:raise ValueError('Missing vegetation placement data')
                    matrices,groups=vegetation
                    group=plan['vegetation']['groups'][str(int(groups[record_id]))]
                    yield {'cache_key':group['cache_key'],'transform':matrices[record_id]}
            audit['vegetation_instances']=len(job.get('vegetation',[]))
            for record in selected_records():
                key=record['cache_key']
                if key not in mesh_cache:
                    meta=json.loads((scene/'meshes'/(key+'.json')).read_text())
                    with np.load(scene/'meshes'/(key+'.npz')) as data:
                        mesh_cache[key]=(meta,data['triangles'],data['uv'],data['ids'])
                meta,tris,uv,local_ids=mesh_cache[key]
                side=_placement_side(self._bounds(key,tris),record['transform'],origin)
                if side is False:continue
                world=transform_triangles(tris,record['transform'])
                if side:
                    hit=slice(None)  # wholly inside: every triangle passes the test below
                else:
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
            selected,skipped=select_backend(backend,len(triangles),self.gpu_budget)
            if skipped:audit['gpu_skipped_reason']=skipped
            fallback=None
            try:
                with self.lanes if self.lanes is not None and selected in ('cuda','optix') else nullcontext():
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
        print(f'Tile {number+1}/{total} {stem}: {audit["status"]} ({audit["seconds"]}s) '+audit.get('error',''),flush=True)
        return audit


_BAKER=None


def _start_baker(arguments,lanes,texture_bytes):
    global _BAKER
    _BAKER=_TileBaker(*arguments,lanes=lanes,texture_bytes=texture_bytes)


def _bake_in_worker(task):
    number,total,job=task
    return _BAKER.bake(number,total,job)


def build(scene, *, only_origin=None, samples=2, experimental_base_materials=False, backend='compiled', output=None,workers=1,start_index=1,progress=None,cancelled=lambda:False):
    if os.environ.get('GLUEMAPPER_OPTIX_TRIANGLES')=='1' and output is None:
        raise ValueError('Experimental hardware triangles require an isolated --output directory; boundary parity is not established')
    scene=Path(scene); plan=json.loads((scene/'plan.json').read_text())
    if plan['errors']:
        details='; '.join(f'{name}: {reason}' for name,reason in list(plan['errors'].items())[:3])
        raise ValueError(f"Resolve scene geometry errors before baking: {details}. See {scene/'plan.json'}")
    for name,digest in plan['source_packages'].items():
        if hashlib.sha256(Path(name).read_bytes()).hexdigest()!=digest:raise ValueError('Scene packages changed; regenerate plan')
    assets=Assets(plan['pak_root'],plan['overrides'])
    destination=Path(output) if output is not None else scene/'tiles';destination.mkdir(parents=True,exist_ok=True)
    if plan.get('vegetation'):
        path=scene/'vegetation.npz'
        if hashlib.sha256(path.read_bytes()).hexdigest()!=plan['vegetation']['sha256']:raise ValueError('Vegetation placement data changed')
    jobs=plan['tiles']
    if not 1<=start_index<=len(jobs):raise ValueError('Start index outside scene plan')
    jobs=jobs[start_index-1:]
    if only_origin is not None:jobs=[j for j in jobs if j['origin']==list(only_origin)]
    if not jobs:raise ValueError('No tiles selected')
    if plan.get('asset_catalog_digest')!=assets.catalog_digest():
        raise ValueError('Asset catalog changed or was not fingerprinted; regenerate scene and landscape plan')
    if workers=='auto':
        # Memory sets the process count exactly as for two threads each; the spare
        # cores then become brick threads inside those processes.
        processes=tile_workers(2) if len(jobs)>1 else 1
        workers=brick_threads(processes)
    else:
        processes=tile_workers(workers) if len(jobs)>1 else 1
    arguments=(scene,output,samples,experimental_base_materials,backend,workers,gpu_budget(gpu_lanes()) if backend=='auto' else None)
    finished={}

    def summary():
        done=[finished[n] for n in sorted(finished)]
        return done,{'status':('incomplete category coverage; not installable' if plan['pending_categories'] else 'experimental complete-category bake; validation required'),
                     'pending_categories':plan['pending_categories'],'selected_tiles':len(jobs),'start_index':start_index,
                     'total_scene_tiles':len(plan['tiles']),'processed_tiles':len(done),'built':sum(r['status']=='built' for r in done),
                     'failed':[{'tile':r['tile'],'error':r.get('error','Unknown failure')} for r in done if r['status']!='built']}

    def record(number,audit):
        finished[number]=audit
        ((destination if output is not None else scene)/'build-progress.json').write_text(json.dumps(summary()[1],indent=2)+'\n')

    if processes==1:
        baker=_TileBaker(*arguments,texture_bytes=dense_texture_cache())  # the one process bakes the dense tiles too
        for number,job in enumerate(jobs):
            if cancelled():raise InterruptedError('Bake cancelled between tiles; completed tiles retained.')
            if progress:progress('Bake lighting tiles',number,len(jobs),'Preparing tile '+str(number+1))
            record(number,baker.bake(number,len(jobs),job))
    else:
        # Tiles are independent: each process keeps its own caches. Dense tiles (estimated at the
        # hybrid crossover or above) go to their own processes, at most `heavy_slots()` of them, so
        # their memory stays bounded and they keep one large texture cache warm; light tiles never
        # wait behind them. GPU lanes are shared by both pools.
        if cancelled():raise InterruptedError('Bake cancelled between tiles; completed tiles retained.')
        context=multiprocessing.get_context('spawn')
        slots=heavy_slots();lanes=context.BoundedSemaphore(gpu_lanes())
        estimate=_TriangleEstimate(scene,plan)
        dense=[]
        for number,job in enumerate(jobs):
            if cancelled():raise InterruptedError('Bake cancelled while planning tile order; completed tiles retained.')
            if progress:progress('Plan lighting tile order',number,len(jobs),f'Checking tile {number+1} of {len(jobs)}')
            dense.append(estimate.estimated_triangles(job)>=HEAVY_TRIANGLES)
        del estimate
        heavy,light=dense_split(dense,processes,slots);cache=dense_texture_cache()
        print(f'Baking {len(jobs)} tiles in {processes} processes ({workers} brick threads each; '
              f'{heavy} for the {sum(dense)} dense tile(s) with a {cache/GIB:.1f} GiB texture cache, '
              f'{light} for the rest; {gpu_lanes()} GPU lane(s))',flush=True)
        groups=[(size,[n for n in range(len(jobs)) if dense[n]==kind],texture)
                for size,kind,texture in ((light,False,LIGHT_TEXTURE_CACHE),(heavy,True,cache)) if size]
        with ExitStack() as stack:
            # Submit one tile per process and refill as tiles finish, checking for
            # cancellation before each start, so a cancelled bake starts no new tile
            # and shutdown only waits for the tiles already running. Each group is
            # [pool, processes, queued tile numbers, running].
            queues=[[stack.enter_context(ProcessPoolExecutor(max_workers=size,mp_context=context,initializer=_start_baker,initargs=(arguments,lanes,texture))),
                     size,iter(numbers),0] for size,numbers,texture in groups]
            pending={}
            def refill():
                for queue in queues:
                    while queue[3]<queue[1]:
                        if cancelled():raise InterruptedError('Bake cancelled between tiles; completed tiles retained.')
                        number=next(queue[2],None)
                        if number is None:break
                        pending[queue[0].submit(_bake_in_worker,(number,len(jobs),jobs[number]))]=(number,queue);queue[3]+=1
            try:
                refill()
                while pending:
                    done,_=wait(pending,timeout=1,return_when=FIRST_COMPLETED)
                    for future in done:
                        number,queue=pending.pop(future);queue[3]-=1;record(number,future.result())
                    if pending and cancelled():raise InterruptedError('Bake cancelled between tiles; completed tiles retained.')
                    if progress:progress('Bake lighting tiles',len(finished),len(jobs),f'{len(finished)} of {len(jobs)} tiles')
                    refill()
            except BaseException:
                for future in pending:future.cancel()
                raise
    results,final=summary()
    ((destination if output is not None else scene)/'build-progress.json').write_text(json.dumps(final,indent=2)+'\n')
    if progress:progress('Bake lighting tiles',len(jobs),len(jobs),'All tile results recorded')
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
