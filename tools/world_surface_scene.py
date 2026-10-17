"""Inventory installed scene geometry for resumable offline mode-1 conversion.

Reads actual installed HLOD/terrain tables, never a list of known houses. Mesh
payloads are cached once, while authored instance transforms remain separate.
The plan records every object category; incomplete coverage cannot be published
as a complete world bake.
"""
import argparse
from collections import Counter, defaultdict
import hashlib
import itertools
import json
from pathlib import Path
import struct
import zipfile

import numpy as np

from compiled_terrain import parse
from geometry_opacity import Assets, cgf_triangles, transform_triangles
from upgrade_map import read
from vegetation import verify_target_hlods
from water_volumes import read_water


def tile_origins(bounds, edge=256):
    """All intersecting tiles, including geometry crossing a placement's tile."""
    low,high=np.asarray(bounds,dtype=float)
    if not np.isfinite([low,high]).all() or np.any(low>high):raise ValueError('Invalid mesh bounds')
    start=np.maximum(np.floor(low/edge).astype(int),0)
    end=np.floor(high/edge).astype(int)
    if np.prod(np.maximum(end-start+1,0))>4096:raise ValueError('Unreasonable instance extent')
    return [tuple(int(x*edge) for x in cell) for cell in itertools.product(*(range(a,b+1) for a,b in zip(start,end)))]


def brush(data,offset,terrain):
    mesh=struct.unpack_from('<H',data,offset+40)[0]
    material=struct.unpack_from('<i',data,offset+96)[0]
    meshes=terrain.tables['meshes']['paths']; materials=terrain.tables['materials']['paths']
    if mesh>=len(meshes) or material>=len(materials) or material < -1:raise ValueError('Brush resource outside table')
    return {'mesh':meshes[mesh], 'material':materials[material] if material>=0 else '',
            'transform':list(struct.unpack_from('<12f',data,offset+44)),
            'layer':struct.unpack_from('<H',data,offset+28)[0],
            'render_flags':struct.unpack_from('<Q',data,offset+32)[0]}


def inventory(level):
    level=Path(level)
    with zipfile.ZipFile(level/'terrain.pak') as z:terrain=parse(read(z,'terrain/terrain.dat'))
    if terrain.version!=29:raise ValueError('Expected converted native terrain')
    records=[]
    def collect(data,offset,size,kind):
        if kind==1:records.append(brush(data,offset,terrain))
    _,counts=read_water(terrain,collect)
    with zipfile.ZipFile(level/'level.pak') as z:hlods=read(z,'terrain/hlods.dat')
    hcounts=verify_target_hlods(hlods)
    cursor=4
    while cursor<len(hlods):
        size=struct.unpack_from('<I',hlods,cursor)[0]; cursor+=4; end=cursor+size
        while cursor<end:
            kind=struct.unpack_from('<I',hlods,cursor)[0]
            if kind==1:records.append(brush(hlods,cursor,terrain))
            cursor+=104 if kind==1 else 64
    return records, {'terrain_objects':counts,'hlod_objects':hcounts,
        'terrain_leaf_sectors':sum(n['depth']==6 for n in terrain.nodes),
        'brush_placements':len(records),'layers':dict(Counter(r['layer'] for r in records))}


def plan(level,pak_root,output,overrides=()):
    output=Path(output); output.mkdir(parents=True,exist_ok=True)
    records,coverage=inventory(level); assets=Assets(pak_root,overrides)
    cache=output/'meshes';cache.mkdir(exist_ok=True)
    dependencies={}; errors={}; empty=[]; meshes={}; jobs=defaultdict(list)
    pairs=sorted({(r['mesh'],r['material']) for r in records})
    for number,(name,override) in enumerate(pairs):
        identity=name+'|'+override
        try:
            blob=assets.get(name)
            digest=hashlib.sha256(blob).hexdigest()
            key=hashlib.sha256((digest+'|'+override+'|node-matrix-v2-default-material').encode()).hexdigest()
            meta_path=cache/(key+'.json'); npz_path=cache/(key+'.npz')
            if not meta_path.exists() or not npz_path.exists():
                tris,info=cgf_triangles(blob,with_surface=True,material_override=override,allow_empty=True)
                bindings=[]; ids=[]; uv=[]
                for group in info['surfaces']:
                    mapping={}
                    for index in np.unique(group['material_ids']):
                        mapping[index]=len(bindings);bindings.append([group['material'],int(index)])
                    ids.append(np.array([mapping[i] for i in group['material_ids']],dtype=np.int32))
                    uv.append(group['uv'])
                meta={'key':key,'source':name,'override':override,'sha256':digest,'triangles':len(tris),
                    'bindings':bindings,'bounds':[tris.min((0,1)).tolist(),tris.max((0,1)).tolist()] if len(tris) else None,
                    'excluded_nodes':info['excluded_nodes'],
                    'default_material_nodes':info['default_material_nodes']}
                np.savez(npz_path,triangles=tris,uv=np.concatenate(uv) if uv else np.empty((0,3,2)),
                         ids=np.concatenate(ids) if ids else np.empty(0,dtype=np.int32))
                meta_path.write_text(json.dumps(meta)+'\n')
            meta=json.loads(meta_path.read_text())
            meshes[identity]=meta
            dependencies[identity]={'sha256':digest,'override':override}
            if not meta['triangles']:empty.append(identity)
        except (ValueError,KeyError,FileNotFoundError) as e:errors[identity]=str(e)
        if number%200==0:print(f'Mesh variants {number+1}/{len(pairs)}; failures {len(errors)}',flush=True)
    placed_triangles=0
    for i,record in enumerate(records):
        identity=record['mesh']+'|'+record['material'];meta=meshes.get(identity)
        if meta is None or not meta['triangles']:continue
        low,high=meta['bounds']
        corners=np.array(list(itertools.product(*zip(low,high))))
        matrix=np.asarray(record['transform']).reshape(3,4)
        if not np.isfinite(matrix).all() or abs(np.linalg.det(matrix[:,:3]))<1e-12:
            errors['placement:'+str(i)]='Invalid placement matrix';continue
        points=corners@matrix[:,:3].T+matrix[:,3]
        for origin in tile_origins([points.min(0),points.max(0)]):jobs[origin].append(i)
        record['cache_key']=meta['key'];placed_triangles+=meta['triangles']
    # Explicit accounting keeps a brush-only intermediate from being installed
    # as a completed all-world replacement.
    pending={'terrain':coverage['terrain_leaf_sectors']}
    labels={2:'vegetation',7:'decals',9:'water',11:'roads',23:'merged_vegetation'}
    for category,counts in (('terrain',coverage['terrain_objects']),('hlod',coverage['hlod_objects'])):
        for kind,count in counts.items():
            if int(kind)!=1:pending[category+'_'+labels.get(int(kind),str(kind))]=count
    fingerprints={str(Path(level)/n):hashlib.sha256((Path(level)/n).read_bytes()).hexdigest() for n in ('level.pak','terrain.pak')}
    report={'format':1,'status':'incomplete coverage; not installable','level':str(Path(level).resolve()),
        'pak_root':str(Path(pak_root).resolve()),'overrides':list(overrides),'coverage':coverage,
        'mesh_variants':len(pairs),'cached_mesh_variants':len(meshes),'proxy_only_variants':empty,
        'errors':errors,'pending_categories':pending,'source_packages':fingerprints,
        'asset_catalog_digest':assets.catalog_digest(),
        'placed_triangles':placed_triangles,'tiles':[{'origin':list(k),'placements':v} for k,v in sorted(jobs.items())]}
    (output/'placements.json').write_text(json.dumps(records)+'\n')
    (output/'plan.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps({k:v for k,v in report.items() if k not in ('tiles','proxy_only_variants')},indent=2),flush=True)
    return report


def main():
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('level','pak-root','output'):p.add_argument('--'+name,type=Path,required=True)
    p.add_argument('--override-pak',action='append',default=[])
    args=p.parse_args();plan(args.level,args.pak_root,args.output,args.override_pak)


if __name__=='__main__':main()
