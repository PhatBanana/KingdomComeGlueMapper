"""Stage source-authored far objects in a native spatial switching hierarchy.

Keeps every existing near record. Ambiguous source groups stay near-only and
are reported; never enable a proxy by guessing a resource index.
"""
import argparse
from collections import defaultdict, Counter
from contextlib import ExitStack
import json
import math
from pathlib import Path
import struct
import xml.etree.ElementTree as ET
import zipfile
from building_brushes import read_brush, convert_brush, resource_table, is_uberlod_proxy
from compiled_terrain import parse
from game_paths import GameLibrary
from water_volumes import read_water
from static_assets import asset_pack
from campaign_package import write_asset_shards
from spatial_hlod import Group, read_groups, world_hierarchy, serialize, record_bounds, records
from upgrade_map import read, xml


def polygon_contains(point, polygon):
    x,y=point;inside=False
    for a,b in zip(polygon,polygon[1:]+polygon[:1]):
        if (a[1]>y)!=(b[1]>y) and x<(b[0]-a[0])*(y-a[1])/(b[1]-a[1])+a[0]:inside=not inside
    return inside


def native_proxy_flags(level):
    with zipfile.ZipFile(Path(level)/'level.pak') as z:
        tree=ET.fromstring(read(z,'terrain/hlods.xml'));data=read(z,'terrain/hlods.dat')
    flags=Counter()
    for parent in tree.iter('HLod'):
        offset=int(parent.get('DataOffset'));size=int(parent.get('DataSize'))
        own=records(data[offset+4:offset+size])
        for child in parent:
            index=int(child.get('ProxyIndex','-1'))
            if index<0:continue
            if index>=len(own) or len(own[index])!=104:raise ValueError('Native proxy linkage contract differs')
            flags[struct.unpack_from('<Q',own[index],32)[0]]+=1
    if not flags:raise ValueError('No native reference proxies')
    # Differences in native flags must be reviewed instead of silently ORed.
    return flags.most_common(1)[0][0],dict(flags)


def build(library, level, output, native_level, compiler=None, source_level="rataje"):
    level,output=Path(level),Path(output);output.mkdir(parents=True,exist_ok=False)
    cache=output/'assets';cache.mkdir();prefix='gluebuild/world_proxies/'
    report={'unresolved':[],'empty_groups':[]}
    proxy_flags,report['native_proxy_flags']=native_proxy_flags(native_level)
    with ExitStack() as stack:
        source_z=stack.enter_context(zipfile.ZipFile(library/f'KingdomComeDeliverance/Data/Levels/{source_level}/level.pak'))
        source=parse(read(source_z,'terrain/terrain.dat'))
        authored=ET.fromstring(read(source_z,'terrain/uberlods.xml'))
        tz=stack.enter_context(zipfile.ZipFile(level/'terrain.pak'));lz=stack.enter_context(zipfile.ZipFile(level/'level.pak'))
        target=parse(read(tz,'terrain/terrain.dat'));old_tree=ET.fromstring(read(lz,'terrain/hlods.xml'))
        near=read_groups(old_tree,read(lz,'terrain/hlods.dat'))
        report['near_records']=len(near)
        source_proxies=defaultdict(list);source_layers=defaultdict(set)
        def collect(data,offset,size,kind):
            if kind!=1:return
            r=read_brush(data,offset,source.tables['meshes']['paths'],source.tables['materials']['paths'])
            source_layers[bytes(data[offset+4:offset+28])+bytes(data[offset+40:offset+88])].add(r['layer'])
            if is_uberlod_proxy(r['path']):source_proxies[tuple(round(v,2) for v in r['position'])].append(r)
        read_water(source,collect)
        layers=ET.fromstring(read(source_z,'leveldata.xml')).find('Layers')
        allowed={0}|{int(n.get('Id')) for n in layers if n.get('Name','').split('{')[0].endswith(('_state0','_state0_prefabs'))}
        report['inactive_groups']=[]
        groups={};vegetation={};brush_regions=[]
        for entry in authored:
            key=entry.get('Id');near_objects=entry.findall('NearObject')
            far=[f for f in entry.findall('FarObject') if int(f.get('LayerId','0')) in allowed]
            if not far:
                report['inactive_groups'].append(key);continue
            if len(far)!=1 or len(near_objects)!=1:
                report['unresolved'].append({'id':key,'reason':'multiple source members'});continue
            far=far[0];shape=entry.find('SwitchShape')
            pos=tuple(map(float,far.get('Position').split(',')))
            bb=tuple(map(float,(far.get('BoundsMin')+','+far.get('BoundsMax')).split(',')))
            candidates=source_proxies.get(tuple(round(v,2) for v in pos),[])
            if not candidates:
                candidates=[r for bucket in source_proxies.values() for r in bucket if math.dist(r['position'],pos)<.001]
            candidates=[r for r in candidates if r['layer']==int(far.get('LayerId','0')) and
                        max(abs(a-b) for a,b in zip(struct.unpack_from('<6f',source.data,r['offset']+4),bb))<.05]
            if len(candidates)!=1:
                report['unresolved'].append({'id':key,'reason':'ambiguous/missing source proxy','candidates':len(candidates)});continue
            center=tuple(map(float,shape.get('Center').split(',')));radius=float(shape.get('Radius'))
            kind=near_objects[0].get('MemberType')
            group=Group('source_'+key,'Vegetation' if kind=='UberlodVegetation' else 'Cluster',center,radius)
            groups[key]=(group,candidates[0])
            if kind=='UberlodVegetation':
                cell=int(near_objects[0].get('VegetationCellIndex'));cell=(cell%64,cell//64)
                if cell in vegetation:raise ValueError('Overlapping source vegetation groups')
                vegetation[cell]=key
            elif kind=='UberlodBrushes':
                poly=[tuple(map(float,p.get('Coord').split(','))) for p in entry.findall('Shape/Point')]
                if len(poly)<3:raise ValueError('Invalid source brush polygon')
                brush_regions.append((key,poly))
            else:raise ValueError('Unknown source near-object member type')
        fallback=defaultdict(list);ambiguous=set()
        for record in near:
            kind=struct.unpack_from('<I',record)[0]
            pos=struct.unpack_from('<3f',record,44) if kind==2 else tuple(struct.unpack_from('<f',record,i)[0] for i in (56,72,88))
            cell=(math.floor(pos[0]/64),math.floor(pos[1]/64))
            match=[vegetation[cell]] if kind==2 and cell in vegetation else []
            if kind==1:
                original_layers=source_layers.get(record[4:28]+record[44:92],set())
                match=[key for key,poly in brush_regions if groups[key][1]['layer'] in original_layers and polygon_contains(pos[:2],poly)]
            if len(match)==1:groups[match[0]][0].records.append(record)
            else:
                ambiguous.update(match);fallback[(kind,*cell)].append(record)
        _,emitted,_,mesh_bytes=asset_pack(stack,library,prefix,cache)
        meshes=list(target.tables['meshes']['paths']);mesh_ids={};leaves=[]
        for key,(group,source_record) in groups.items():
            if not group.records:
                report['empty_groups'].append(key);continue
            # Expand bounds to retain all detail records. Authored switching
            # radius remains the minimum; no geometry is dropped by grouping.
            group.radius=max([group.radius]+[math.dist(group.center,record_bounds(r)[0])+record_bounds(r)[1] for r in group.records])
            if key in ambiguous:
                report['unresolved'].append({'id':key,'reason':'overlapping brush membership'})
                leaves.append(group);continue
            resource=(source_record['mesh'],source_record['material'])
            try:
                if resource not in mesh_ids:
                    name=prefix+'mesh'+str(len(mesh_ids))+'.cgf'
                    material=source.tables['materials']['paths'][resource[1]] if resource[1]>=0 else None
                    payload=mesh_bytes(source_record['path'],material)
                    emitted[name]=payload;mesh_ids[resource]=len(meshes);meshes.append(name)
                proxy=bytearray(convert_brush(source.data,source_record['offset'],mesh_ids[resource],-1))
                struct.pack_into('<Q',proxy,32,proxy_flags)
                group.proxy=bytes(proxy)
            except (ValueError,KeyError,FileNotFoundError) as e:
                report['unresolved'].append({'id':key,'reason':str(e),'mesh':source_record['path']})
            leaves.append(group)
        for key,rs in sorted(fallback.items()):
            bs=[record_bounds(r) for r in rs]
            low=[min(c[a]-s for c,s in bs) for a in range(3)];high=[max(c[a]+s for c,s in bs) for a in range(3)]
            center=tuple((a+b)/2 for a,b in zip(low,high));radius=max(math.dist(center,c)+s for c,s in bs)
            leaves.append(Group('remaining_'+'_'.join(map(str,key)),'Vegetation' if key[0]==2 else 'Cluster',center,radius,rs))
        if Counter(r for g in leaves for r in g.records)!=Counter(near):raise ValueError('Near records changed/lost/duplicated')
        from region_travel_ground import Heightfield
        from hlod_spatial_metadata import normalize as native_grid
        height = Heightfield(target.data)
        tree,hlods,summary=serialize(world_hierarchy(leaves, height=height));report.update(summary)
        _, report['vegetation_grid'] = native_grid(tree, hlods, height, validate_only=True)
        mesh_start=target.tables['meshes']['offset']-4;material_start=target.tables['materials']['offset']-4
        terrain=bytearray(target.data[:mesh_start]+resource_table(meshes)+target.data[material_start:])
        struct.pack_into('<I',terrain,4,len(terrain));parsed=parse(bytes(terrain))
        if parsed.data[parsed.nodes[0]['offset']:]!=target.data[target.nodes[0]['offset']:]:raise ValueError('Terrain/merged vegetation changed')
        packages=output/'packages';packages.mkdir()
        for z,filename in ((tz,'terrain.pak'),(lz,'level.pak')):
            with zipfile.ZipFile(packages/filename,'x',zipfile.ZIP_STORED) as dest:
                for n in z.namelist():
                    data=terrain if n.lower()=='terrain/terrain.dat' else hlods if n.lower()=='terrain/hlods.dat' else xml(tree) if n.lower()=='terrain/hlods.xml' else read(z,n)
                    dest.writestr(n,data)
        shards,_=write_asset_shards(packages,((n,p.read_bytes()) for n,p in emitted.items()),streaming_compiler=compiler)
        report['asset_archives']=shards
        report['runtime_verified']=False
    (output/'report.json').write_text(json.dumps(report,indent=2)+'\n')
    return report


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--library',type=GameLibrary,required=True);p.add_argument('--level',type=Path,required=True)
    p.add_argument('--source-level', default='rataje')
    p.add_argument('--native-level',type=Path,required=True);p.add_argument('--output',type=Path,required=True);p.add_argument('--rc',type=Path)
    a=p.parse_args();r=build(a.library,a.level,a.output,a.native_level,a.rc,a.source_level)
    print(json.dumps({k:len(v) if isinstance(v,list) else v for k,v in r.items()}))
