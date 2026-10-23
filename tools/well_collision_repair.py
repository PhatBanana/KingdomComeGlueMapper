"""Restore the native well prefab safety mesh using its compiled donor geometry."""
import math
import struct
import zipfile
from pathlib import Path
import xml.etree.ElementTree as E
from upgrade_map import read, xml
from cooking_pots import rotate, vector
from entity_visuals import quaternion_product as qmul
from character_water_work import identity


def upgrade(package, source, target):
    from character_water_native import load
    from compiled_terrain import parse
    from room_layout import geometry
    from setup_package_upgrade import rewrite
    from setup_campaign import digest
    package = Path(package)
    level = 'Data/Levels/kcd1_travel/level.pak'
    with zipfile.ZipFile(package/level) as z: mission = E.fromstring(read(z, 'objects_mission0.xml'))
    holders = [e for e in mission if e.get('Name','').startswith('gm_schedule_water_source_') and e.get('Name','').endswith('_holder')]
    if source is None or target is None: raise ValueError('Both games are required to restore well safety geometry')
    target = Path(target)
    contract = load(target); donor = contract['well']
    # Wells without a refill worker still require their authored safety surface.
    # Match the exact exported Well contract and an actually imported visual.
    from chairs import inventory
    from entity_visuals import world_transform
    model = contract['group']['animObject'].find('Properties').get('object_Model').lower().removeprefix('data/')
    names = {e.get('Name') for e in mission}
    with zipfile.ZipFile(Path(source)/'Data/Levels/rataje/level.pak') as z:
        entities, _, _ = inventory(z)
    for key, entity in entities.items():
        props = entity.find('Properties')
        if (not key or 'glue_item_'+key not in names or props is None or
                entity.get('EntityClass') != 'AnimObject' or
                props.get('soclasses_SmartObjectHelpers') != 'Well' or
                props.get('object_Model','').lower() != model): continue
        p,q,s = world_transform(entity, entities)
        if any(abs(v-1)>.001 for v in s): raise ValueError('Scaled source well requires a safety adapter')
        holders.append(E.Element('Entity',Name='gm_schedule_water_source_'+key+'_holder',
            EntityGuid=entity.get('EntityGuid'),Pos=vector(p),Rotate=vector(q)))
    if not holders: return {}, dict(repaired=[], runtime_verified=False)
    with zipfile.ZipFile(target/'Data/IPL_GameData.pak') as z:
        prefab = E.fromstring(read(z, 'Prefabs/Water/well.xml'))
    designers = prefab.findall("Objects/Object[@Type='Designer']")
    if len(designers) != 1: raise ValueError('Native well requires one authored safety collider')
    collider = designers[0]
    def pose(e):
        return tuple(map(float,e.get('Pos','0,0,0').split(','))), tuple(map(float,e.get('Rotate','1,0,0,0').split(',')))
    cp,cq = pose(collider); dp,dq = pose(donor)
    prefab_holder = prefab.find("Objects/Object[@EntityClass='SmartObjectHolder']")
    hp,hq = pose(prefab_holder)
    inverse = (hq[0],-hq[1],-hq[2],-hq[3])
    cp = rotate(inverse,tuple(a-b for a,b in zip(cp,hp)))
    cq = qmul(inverse,cq)
    expected = tuple(a+b for a,b in zip(dp,rotate(dq,cp)))
    with zipfile.ZipFile(target/'Data/Levels/trosecko/terrain.pak') as z: tables = parse(read(z,'terrain/terrain.dat')).tables
    matches=[]
    with zipfile.ZipFile(target/'Data/Levels/trosecko/level.pak') as z:
        data=read(z,'terrain/hlods.dat'); cursor=4
        while cursor<len(data):
            end=cursor+4+struct.unpack_from('<I',data,cursor)[0];cursor+=4
            while cursor<end:
                kind=struct.unpack_from('<I',data,cursor)[0]
                if kind==1:
                    matrix=struct.unpack_from('<12f',data,cursor+44)
                    if math.dist(expected,tuple(matrix[i] for i in (3,7,11)))<.002:
                        mi=struct.unpack_from('<H',data,cursor+40)[0]; ma=struct.unpack_from('<i',data,cursor+96)[0]
                        if ma>=0 and tables['materials']['paths'][ma].lower()==collider.get('Material').lower():
                            matches.append(tables['meshes']['paths'][mi])
                cursor+={1:104,2:64}[kind]
        if len(matches)!=1: raise ValueError('Native well collider does not resolve to one compiled mesh')
        entry=matches[0].replace('%level%/','').lower()
        mesh=read(z,next(n for n in z.namelist() if n.lower()==entry))
    model='Objects/gluemapper/well_safety.cgf'; material='Materials/gluemapper/well_safety.mtl'
    # Same native surface semantics, with the retail invisible shader.
    mat=E.Element('Material',Name='well_safety',Shader='Nodraw',MtlFlags='525312',GenMask='0',StringGenMask='',SurfaceType='mat_player_only',Opacity='1',VoxelCoverage='0')
    repaired=[]
    for holder in holders:
        name=holder.get('Name').removesuffix('_holder')+'_safety'
        existing=[e for e in mission if e.get('Name')==name]
        p,q=pose(holder); offset=rotate(q,cp)
        node=geometry(dict(name=name,model=model))
        node.attrib.update(Name=name,EntityGuid=identity('well-safety/'+holder.get('EntityGuid')),
            EntityId=existing[0].get('EntityId') if existing else str(max(int(e.get('EntityId','0')) for e in mission)+1),
            Pos=vector(tuple(a+b for a,b in zip(p,offset))),Rotate=vector(qmul(q,cq)),Material=material)
        if existing:
            from character_city_benches import signature
            if len(existing)!=1 or signature(existing[0])!=signature(node):raise ValueError('Conflicting well safety geometry')
        else: mission.append(node);repaired.append(holder.get('Name'))
    files={}
    if repaired:
        rewrite(package,level,{'objects_mission0.xml':xml(mission)})
        files[level]=digest(package/level)
        archive='Data/gluemappertravel.pak'
        rewrite(package,archive,{model:mesh,material:xml(mat)});files[archive]=digest(package/archive)
    return files,dict(repaired=repaired,native_source=matches[0],runtime_verified=False)
