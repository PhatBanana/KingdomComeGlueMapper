"""Native converted terrain/road geometry for the offline surface bake.

Height samples retain the installed conversion's origin, quantization, palette
and holes. Terrain colour uses the authored base layer, not the already-lit
terrain cover texture. Layer blending is reported as an approximation.
"""
import argparse
import hashlib
import json
from pathlib import Path
import struct
import xml.etree.ElementTree as ET
import zipfile

import numpy as np

from compiled_terrain import parse
from upgrade_map import read
from water_volumes import read_water
from world_surface_scene import tile_origins


def terrain_sector(terrain,node,surfaces,approximate_undefined=False):
    size=node['size'];values=node['values']
    if size<2:return np.empty((0,3,3)),np.empty((0,3,2)),np.empty(0,dtype=np.int32),[]
    packed=np.frombuffer(terrain.data,'<u4',size*size,node['samples']).reshape(size,size)
    palette=np.frombuffer(terrain.data,np.uint8,node['surface_count'],node['palette'])
    local=packed&0xfffff
    # The file lists USED global types, not a dense local-index array. Native
    # Load_T reconstructs sparse local IDs from owned cells (excluding borders).
    owned=local[:-1,:-1].copy()
    used=np.unique(owned[owned<14])
    if len(used)>len(palette):raise ValueError('Terrain surface outside palette')
    lookup={int(tag):int(palette[i]) for i,tag in enumerate(used)}
    if np.any(owned==14):
        if not approximate_undefined:raise ValueError('Undefined terrain layer needs macro-cover colour or explicit approximation')
        # Preserve geometry and holes; extend the nearest authored base layer
        # into undefined cells instead of inventing an albedo/solid fill.
        valid=owned<14
        if not valid.any():raise ValueError('No authored terrain colour near undefined cells')
        while (owned==14).any():
            previous=owned.copy(); changed=False
            for dx,dy in ((-1,0),(1,0),(0,-1),(0,1)):
                shifted=np.roll(previous,(dx,dy),(0,1))
                eligible=(owned==14)&(shifted<14)
                if dx<0:eligible[-1]=False
                if dx>0:eligible[0]=False
                if dy<0:eligible[:,-1]=False
                if dy>0:eligible[:,0]=False
                owned[eligible]=shifted[eligible];changed|=bool(eligible.any())
            if not changed:raise ValueError('Undefined terrain island has no adjacent base layer')
    x=np.linspace(values[2],values[5],size); y=np.linspace(values[3],values[6],size)
    xx,yy=np.meshgrid(x,y,indexing='ij')
    zz=values[8]+(packed>>20)*values[9]
    points=np.stack((xx,yy,zz),axis=-1)
    # The surface tag at a cell origin owns that cell; tag 15 is the legacy
    # terrain-hole sentinel retained by the v28->v29 converter.
    i,j=np.nonzero(owned!=15)
    a=points[i,j];b=points[i+1,j];c=points[i+1,j+1];d=points[i,j+1]
    tris=np.concatenate((np.stack((a,b,c),axis=1),np.stack((a,c,d),axis=1)))
    tags=np.tile(owned[i,j],2);uv=np.empty((len(tris),3,2));bindings=[];ids=np.empty(len(tris),dtype=np.int32)
    for tag in np.unique(tags):
        surface=surfaces[lookup[int(tag)]]
        axis=int(surface.get('ProjectAxis','2'))
        if axis not in (0,1,2):raise ValueError('Unsupported terrain projection axis')
        axes=[a for a in range(3) if a!=axis]; mask=tags==tag
        uv[mask]=tris[mask][:,:,axes]*[float(surface.get('DetailScaleX',1)),float(surface.get('DetailScaleY',1))]
        ids[mask]=len(bindings);bindings.append([surface['DetailMaterial'],0])
    return tris,uv,ids,bindings


def road(data,offset,size,materials):
    bounds=np.array(struct.unpack_from('<6f',data,offset+4))
    v,i,t,p,s=struct.unpack_from('<5I',data,offset+84)
    if v==i==t==0:
        return np.empty((0,3,3)),np.empty((0,3,2)),np.empty(0,dtype=np.int32),[]
    if not v or i%3 or t!=v:raise ValueError('Invalid road buffers')
    vertices=np.frombuffer(data,'<f2',v*6,offset+112).reshape(v,6).astype(float)
    vertices[:,:3]+=(bounds[:3]+bounds[3:])/2
    indices=np.frombuffer(data,'<u2',i,offset+112+v*12).reshape(-1,3)
    if indices.max()>=v:raise ValueError('Road index outside vertex buffer')
    material=struct.unpack_from('<i',data,offset+108)[0]
    if not 0<=material<len(materials):raise ValueError('Road material outside table')
    return vertices[indices,:3],vertices[indices,4:6],np.zeros(i//3,dtype=np.int32),[[materials[material],0]]


def augment(scene,experimental_base_materials=False):
    scene=Path(scene);plan=json.loads((scene/'plan.json').read_text())
    if plan.get('landscape_added'):raise ValueError('Landscape already added; regenerate the base scene before changing it')
    records=json.loads((scene/'placements.json').read_text());jobs={tuple(j['origin']):j['placements'] for j in plan['tiles']}
    level=Path(plan['level'])
    for name,digest in plan['source_packages'].items():
        if hashlib.sha256(Path(name).read_bytes()).hexdigest()!=digest:raise ValueError('Scene changed; regenerate plan')
    with zipfile.ZipFile(level/'terrain.pak') as z:terrain=parse(read(z,'terrain/terrain.dat'))
    with zipfile.ZipFile(level/'level.pak') as z:root=ET.fromstring(read(z,'leveldata.xml'))
    surfaces={int(e.get('SurfaceTypeID')):dict(e.attrib) for e in root.find('SurfaceTypes')}
    counter={'terrain_sectors':0,'roads':0,'triangles':0,'undefined_terrain_cells':0}
    def add(name,geometry):
        triangles,uv,ids,bindings=geometry
        if not len(triangles):return
        h=hashlib.sha256()
        for array in (triangles,uv,ids):h.update(array.tobytes())
        h.update(json.dumps(bindings).encode());key=h.hexdigest()
        bounds=[triangles.min((0,1)).tolist(),triangles.max((0,1)).tolist()]
        np.savez(scene/'meshes'/(key+'.npz'),triangles=triangles,uv=uv,ids=ids)
        (scene/'meshes'/(key+'.json')).write_text(json.dumps({'key':key,'source':name,'triangles':len(triangles),
            'bindings':bindings,'bounds':bounds,'excluded_nodes':[]})+'\n')
        record={'mesh':name,'material':'','transform':[1,0,0,0,0,1,0,0,0,0,1,0],'cache_key':key,'layer':0}
        index=len(records);records.append(record)
        for origin in tile_origins(bounds):jobs.setdefault(origin,[]).append(index)
        counter['triangles']+=len(triangles)
    for node in terrain.nodes:
        if node['depth']!=6:continue
        add('terrain-sector:'+str(node['offset']),terrain_sector(terrain,node,surfaces,experimental_base_materials));counter['terrain_sectors']+=1
        if node['size']:
            tags=np.frombuffer(terrain.data,'<u4',node['size']**2,node['samples']).reshape(node['size'],node['size'])&0xfffff
            counter['undefined_terrain_cells']+=int((tags[:-1,:-1]==14).sum())
    def visit(data,offset,size,kind):
        if kind==11:
            add('road:'+str(offset),road(data,offset,size,terrain.tables['materials']['paths']));counter['roads']+=1
    read_water(terrain,visit)
    plan['landscape_added']=counter
    plan['pending_categories'].pop('terrain',None);plan['pending_categories'].pop('terrain_roads',None)
    plan['landscape_limitations']=['base terrain layer only; macro cover and layer blends not baked',
        'undefined terrain colours extended from adjacent authored layers' if experimental_base_materials else 'undefined terrain colours refused']
    plan['tiles']=[{'origin':list(k),'placements':v} for k,v in sorted(jobs.items())]
    (scene/'placements.json').write_text(json.dumps(records)+'\n')
    (scene/'plan.json').write_text(json.dumps(plan,indent=2)+'\n')
    print(json.dumps(counter,indent=2),flush=True)


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--scene',type=Path,required=True)
    p.add_argument('--experimental-base-materials',action='store_true')
    args=p.parse_args();augment(args.scene,args.experimental_base_materials)
