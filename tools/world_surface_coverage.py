"""Resolve static GI category coverage without changing the accepted base scene.

Water/decal/merged render nodes are not standalone static voxelizer inputs in
CryEngine's reference GatherObjects path. Native KCD2 group GI eligibility
selects foliage, with its full scaled/rotated/terrain-aligned placement.
This remains an experimental offline bake, not a claim of native bake parity.
"""
import argparse
from collections import Counter
import hashlib
import itertools
import json
from pathlib import Path
import shutil
import struct
import zipfile
import numpy as np
from compiled_terrain import parse
from geometry_opacity import Assets, cgf_triangles
from upgrade_map import read
from vegetation import verify_target_hlods
from water_volumes import read_water
from world_surface_scene import tile_origins
from vegetation_gi import POLICY,GI_ENABLED,eligible_instance
from vegetation_tilt import HeightField,bake as bake_tilt


def gi_mode(flags):
    return ((flags>>10)&1)|(((flags>>16)&1)<<1)|(((flags>>23)&1)<<2)


def vegetation_group(terrain,index):
    table=terrain.tables['vegetation']
    if not 0<=index<len(table['paths']):raise ValueError('Vegetation group outside table')
    offset=table['offset']+index*360
    flags=struct.unpack_from('<I',terrain.data,offset+332)[0]
    material=struct.unpack_from('<i',terrain.data,offset+336)[0]
    paths=terrain.tables['materials']['paths']
    if not -1<=material<len(paths):raise ValueError('Vegetation material outside table')
    alignment=struct.unpack_from('<f',terrain.data,offset+280)[0]
    if not np.isfinite(alignment) or not 0<=alignment<=1:raise ValueError('Invalid terrain alignment')
    return {'mesh':table['paths'][index], 'material':paths[material] if material>=0 else '',
            'alignment':alignment,'gi_enabled':bool(flags&256),'flags':flags}


def transforms(positions,scales,angles):
    positions=np.asarray(positions,float);scales=np.asarray(scales,float);angles=np.asarray(angles,float)
    if positions.ndim!=2 or positions.shape[1]!=3 or angles.shape!=positions.shape or scales.shape!=(len(positions),):raise ValueError('Invalid vegetation arrays')
    if not np.isfinite(positions).all() or not np.isfinite(scales).all() or np.any(scales<=0) or not np.isfinite(angles).all():raise ValueError('Invalid vegetation transform')
    # Bytes are Z,X,Y in the stream; caller supplies X,Y,Z. 255 is a full turn.
    # KCD2 terrain alignment is baked into the X/Y bytes (vegetation_tilt).
    x,y,z=(angles*(2*np.pi/255)).T
    sx,cx=np.sin(x),np.cos(x);sy,cy=np.sin(y),np.cos(y);sz,cz=np.sin(z),np.cos(z)
    rotation=np.empty((len(positions),3,3))
    rotation[:,0,:]=np.stack((cy*cz,sx*sy*cz-cx*sz,cx*sy*cz+sx*sz),axis=1)
    rotation[:,1,:]=np.stack((cy*sz,sx*sy*sz+cx*cz,cx*sy*sz-sx*cz),axis=1)
    rotation[:,2,:]=np.stack((-sy,sx*cy,cx*cy),axis=1)
    result=np.empty((len(positions),3,4));result[:,:,:3]=rotation*scales[:,None,None];result[:,:,3]=positions
    return result


def cache_mesh(scene,assets,group):
    blob=assets.get(group['mesh']);digest=hashlib.sha256(blob).hexdigest()
    key=hashlib.sha256((digest+'|'+group['material']+'|node-matrix-v1').encode()).hexdigest()
    path=scene/'meshes'/(key+'.json')
    if not path.exists():
        tris,info=cgf_triangles(blob,with_surface=True,material_override=group['material'],allow_empty=True)
        bindings=[];ids=[];uv=[]
        for surface in info['surfaces']:
            remap={}
            for local in np.unique(surface['material_ids']):
                remap[local]=len(bindings);bindings.append([surface['material'],int(local)])
            ids.append(np.array([remap[i] for i in surface['material_ids']],np.int32));uv.append(surface['uv'])
        meta={'key':key,'source':group['mesh'],'override':group['material'],'sha256':digest,'triangles':len(tris),
              'bindings':bindings,'bounds':[tris.min((0,1)).tolist(),tris.max((0,1)).tolist()] if len(tris) else None,'excluded_nodes':info['excluded_nodes']}
        np.savez(scene/'meshes'/(key+'.npz'),triangles=tris,uv=np.concatenate(uv) if uv else np.empty((0,3,2)),ids=np.concatenate(ids) if ids else np.empty(0,np.int32))
        path.write_text(json.dumps(meta)+'\n')
    return json.loads(path.read_text())


def augment(source,output,include_vegetation=True):
    source,output=Path(source),Path(output)
    if output.exists():raise FileExistsError('Use a fresh coverage scene')
    plan=json.loads((source/'plan.json').read_text())
    if plan.get('vegetation'):raise ValueError('Vegetation already added')
    for name,digest in plan['source_packages'].items():
        if hashlib.sha256(Path(name).read_bytes()).hexdigest()!=digest:raise ValueError('Source package changed')
    output.mkdir(parents=True);(output/'meshes').mkdir()
    # Immutable cache files can be shared, while plans and tile outputs stay isolated.
    for file in (source/'meshes').iterdir():
        (output/'meshes'/file.name).hardlink_to(file)
    shutil.copy2(source/'placements.json',output/'placements.json')
    with zipfile.ZipFile(Path(plan['level'])/'terrain.pak') as z:terrain=parse(read(z,'terrain/terrain.dat'))
    with zipfile.ZipFile(Path(plan['level'])/'level.pak') as z:data=read(z,'terrain/hlods.dat')
    verify_target_hlods(data)
    groups={i:vegetation_group(terrain,i) for i in range(len(terrain.tables['vegetation']['paths']))}
    for group in groups.values():
        group['source_gi_enabled']=group['gi_enabled']
        group['source_flags']=group['flags']
        group['flags']|=GI_ENABLED
        group['gi_enabled']=True
    selected={};counts=Counter();node_modes=Counter();cursor=4
    while cursor<len(data):
        size=struct.unpack_from('<I',data,cursor)[0];cursor+=4;end=cursor+size
        while cursor<end:
            kind=struct.unpack_from('<I',data,cursor)[0]
            if kind==2:
                group=struct.unpack_from('<H',data,cursor+40)[0]
                if group not in groups:raise ValueError('Unknown HLOD vegetation group')
                flags=struct.unpack_from('<Q',data,cursor+32)[0];node_modes[gi_mode(flags)]+=1
                counts['total']+=1
                if not groups[group]['source_gi_enabled']:counts['legacy_gi_disabled_upgraded']+=1
                if not eligible_instance(flags):counts['hidden_or_proxy']+=1
                elif include_vegetation:
                    selected.setdefault(group,[]).append(cursor);counts['selected']+=1
                else:counts['excluded_by_preset']+=1
            cursor+=104 if kind==1 else 64
    assets=Assets(plan['pak_root'],plan['overrides'])
    if assets.catalog_digest()!=plan['asset_catalog_digest']:raise ValueError('Asset catalog changed')
    height=HeightField(terrain) if include_vegetation else None
    if include_vegetation:
        # Same idempotent tilt bake as the package stage, so older packages bake identically.
        from lod_ratio_metadata import imported
        data,_=bake_tilt(terrain.data,data,imported,height)
    jobs={tuple(j['origin']):dict(j) for j in plan['tiles']}
    all_transforms=[];all_groups=[];metadata={};count=0;errors={}
    for group,offsets in sorted(selected.items()):
        definition=groups[group]
        try:meta=cache_mesh(output,assets,definition)
        except (ValueError,KeyError,FileNotFoundError) as error:
            errors[str(group)]=str(error);continue
        if not meta['triangles']:counts['proxy_only']+=len(offsets);continue
        values=np.array([struct.unpack_from('<4f',data,o+44) for o in offsets])
        angles=np.array([[data[o+62],data[o+63],data[o+61]] for o in offsets])
        matrices=transforms(values[:,:3],values[:,3],angles)
        corners=np.array(list(itertools.product(*zip(*meta['bounds']))))
        points=corners[None,:,:]@matrices[:,:,:3].transpose(0,2,1)+matrices[:,None,:,3]
        low=points.min(1);high=points.max(1)
        metadata[str(group)]={**definition,'cache_key':meta['key'],'instances':len(offsets)}
        for i,bounds in enumerate(zip(low,high)):
            for origin in tile_origins(bounds):
                jobs.setdefault(origin,{'origin':list(origin),'placements':[]}).setdefault('vegetation',[]).append(count+i)
        all_transforms.append(matrices);all_groups.append(np.full(len(matrices),group,np.uint16));count+=len(matrices)
        print(f'Vegetation group {group}: {len(matrices)} instances; {count} total',flush=True)
    if errors:
        (output/'coverage-errors.json').write_text(json.dumps(errors,indent=2));raise ValueError('Vegetation mesh failures: '+str(errors))
    np.savez(output/'vegetation.npz',transforms=np.concatenate(all_transforms) if all_transforms else np.empty((0,3,4)),groups=np.concatenate(all_groups) if all_groups else np.empty(0,np.uint16))
    policy=POLICY if include_vegetation else 'excluded by Buildings preset; no forest surface contribution'
    plan['vegetation']={'policy':policy,'groups':metadata,'counts':dict(counts),'serialized_node_modes':dict(node_modes),'sha256':hashlib.sha256((output/'vegetation.npz').read_bytes()).hexdigest()}
    excluded=Counter()
    def inspect(d,o,s,k):
        if k in (7,9,23):
            if gi_mode(struct.unpack_from('<Q',d,o+32)[0]):raise ValueError(f'Nonzero GI mode on excluded category {k}')
            excluded[{7:'terrain_decals',9:'terrain_water',23:'terrain_merged_vegetation'}[k]]+=1
    read_water(terrain,inspect)
    coverage={}
    for name,n in excluded.items():
        if plan['pending_categories'].get(name)!=n:raise ValueError('Coverage count mismatch: '+name)
        coverage[name]={'count':n,'policy':'excluded from standalone static surface voxelization; reference GatherObjects does not collect this render-node type; serialized GI mode is zero'}
        del plan['pending_categories'][name]
    if plan['pending_categories'].get('hlod_vegetation')!=counts['total']:raise ValueError('Vegetation count mismatch')
    del plan['pending_categories']['hlod_vegetation']
    coverage['hlod_vegetation']={'count':counts['total'],'policy':policy,'included':count,'counts':dict(counts)}
    plan['category_policy']=coverage;plan['tiles']=[jobs[k] for k in sorted(jobs)]
    plan['status']='category coverage resolved; experimental bake and runtime validation required'
    plan['coverage_reference']='https://github.com/ValtoGameEngines/CryEngine/blob/release/Code/CryEngine/Cry3DEngine/SVO/VoxelSegment.cpp'
    plan['reuse_base_scene']=str(source.resolve())
    (output/'plan.json').write_text(json.dumps(plan,indent=2)+'\n')
    print(json.dumps({'counts':dict(counts),'tiles':len(jobs),'pending':plan['pending_categories']},indent=2),flush=True)


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--scene',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    a=p.parse_args();augment(a.scene,a.output)
