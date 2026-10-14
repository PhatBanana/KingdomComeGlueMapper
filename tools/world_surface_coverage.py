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


class HeightField:
    def __init__(self,terrain):
        self.heights=np.full((4097,4097),np.nan,dtype=np.float64)
        for node in terrain.nodes:
            if node['depth']!=6 or node['size']<2:continue
            size=node['size'];v=node['values'];x,y=round(v[2]),round(v[3])
            packed=np.frombuffer(terrain.data,'<u4',size*size,node['samples']).reshape(size,size)
            z=v[8]+(packed>>20)*v[9]
            q=np.linspace(0,size-1,65);lo=np.minimum(q.astype(int),size-2);f=q-lo
            expanded=(z[lo,:]*(1-f[:,None])+z[lo+1,:]*f[:,None])
            expanded=expanded[:,lo]*(1-f[None,:])+expanded[:,lo+1]*f[None,:]
            self.heights[x:x+65,y:y+65]=expanded
        if not np.isfinite(self.heights).all():raise ValueError('Terrain height coverage incomplete')

    def height(self,x,y):
        x=np.clip(x,0,4096);y=np.clip(y,0,4096)
        ix=np.minimum(x.astype(int),4095);iy=np.minimum(y.astype(int),4095)
        fx=x-ix;fy=y-iy;h=self.heights
        return (h[ix,iy]*(1-fx)+h[ix+1,iy]*fx)*(1-fy)+(h[ix,iy+1]*(1-fx)+h[ix+1,iy+1]*fx)*fy

    def normal(self,positions):
        x,y=positions[:,0],positions[:,1];r=.55
        h1=self.height(x-r,y-r);h2=self.height(x-r,y+r)
        h3=self.height(x+r,y-r);h4=self.height(x+r,y+r)
        a=np.stack((np.full(len(x),2*r),np.full(len(x),-2*r),h3-h2),axis=1)
        b=np.stack((np.full(len(x),2*r),np.full(len(x),2*r),h4-h1),axis=1)
        normal=np.cross(a,b);return normal/np.linalg.norm(normal,axis=1)[:,None]


def transforms(positions,scales,angles,alignment=0.,normals=None):
    positions=np.asarray(positions,float);scales=np.asarray(scales,float);angles=np.asarray(angles,float)
    if positions.ndim!=2 or positions.shape[1]!=3 or angles.shape!=positions.shape or scales.shape!=(len(positions),):raise ValueError('Invalid vegetation arrays')
    if not np.isfinite(positions).all() or not np.isfinite(scales).all() or np.any(scales<=0) or not np.isfinite(angles).all():raise ValueError('Invalid vegetation transform')
    # Bytes are Z,X,Y in the stream; caller supplies X,Y,Z. 255 is a full turn.
    x,y,z=(angles*(2*np.pi/255)).T
    sx,cx=np.sin(x),np.cos(x);sy,cy=np.sin(y),np.cos(y);sz,cz=np.sin(z),np.cos(z)
    rotation=np.empty((len(positions),3,3))
    rotation[:,0,:]=np.stack((cy*cz,sx*sy*cz-cx*sz,cx*sy*cz+sx*sz),axis=1)
    rotation[:,1,:]=np.stack((cy*sz,sx*sy*sz+cx*cz,cx*sy*sz-sx*cz),axis=1)
    rotation[:,2,:]=np.stack((-sy,sx*cy,cx*cy),axis=1)
    if alignment:
        if normals is None:raise ValueError('Aligned vegetation requires terrain normals')
        up=np.asarray(normals,dtype=float)*alignment+np.array([0,0,1])*(1-alignment)
        up/=np.linalg.norm(up,axis=1)[:,None]
        forward=np.cross(np.array([-1.,0,0]),up);forward/=np.linalg.norm(forward,axis=1)[:,None]
        right=np.cross(forward,up)
        basis=np.stack((right,forward,up),axis=2)
        yaw=np.zeros_like(rotation);yaw[:,0,0]=cz;yaw[:,0,1]=-sz;yaw[:,1,0]=sz;yaw[:,1,1]=cz;yaw[:,2,2]=1
        rotation=basis@yaw
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


def augment(source,output):
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
                else:
                    selected.setdefault(group,[]).append(cursor);counts['selected']+=1
            cursor+=104 if kind==1 else 64
    assets=Assets(plan['pak_root'],plan['overrides'])
    if assets.catalog_digest()!=plan['asset_catalog_digest']:raise ValueError('Asset catalog changed')
    height=HeightField(terrain);jobs={tuple(j['origin']):dict(j) for j in plan['tiles']}
    all_transforms=[];all_groups=[];metadata={};count=0;errors={}
    for group,offsets in sorted(selected.items()):
        definition=groups[group]
        try:meta=cache_mesh(output,assets,definition)
        except (ValueError,KeyError,FileNotFoundError) as error:
            errors[str(group)]=str(error);continue
        if not meta['triangles']:counts['proxy_only']+=len(offsets);continue
        values=np.array([struct.unpack_from('<4f',data,o+44) for o in offsets])
        angles=np.array([[data[o+62],data[o+63],data[o+61]] for o in offsets])
        matrices=transforms(values[:,:3],values[:,3],angles,definition['alignment'],height.normal(values[:,:3]) if definition['alignment'] else None)
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
    plan['vegetation']={'policy':POLICY,'groups':metadata,'counts':dict(counts),'serialized_node_modes':dict(node_modes),'sha256':hashlib.sha256((output/'vegetation.npz').read_bytes()).hexdigest()}
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
    coverage['hlod_vegetation']={'count':counts['total'],'policy':POLICY+'; all groups eligible; hidden/proxy exclusion; full placement transforms','included':count,'counts':dict(counts)}
    plan['category_policy']=coverage;plan['tiles']=[jobs[k] for k in sorted(jobs)]
    plan['status']='category coverage resolved; experimental bake and runtime validation required'
    plan['coverage_reference']='https://github.com/ValtoGameEngines/CryEngine/blob/release/Code/CryEngine/Cry3DEngine/SVO/VoxelSegment.cpp'
    plan['reuse_base_scene']=str(source.resolve())
    (output/'plan.json').write_text(json.dumps(plan,indent=2)+'\n')
    print(json.dumps({'counts':dict(counts),'tiles':len(jobs),'pending':plan['pending_categories']},indent=2),flush=True)


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--scene',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    a=p.parse_args();augment(a.scene,a.output)
