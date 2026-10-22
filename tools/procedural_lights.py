"""Expand active KCD1 fire prefabs into native light/particle entities.

The source supplies placements and light parameters. KCD2 supplies the property
schema and particle definitions. Cooking-controlled flames keep their existing
native lifecycle instead of getting a second, permanently lit emitter.
"""
import copy
from collections import Counter
from pathlib import Path
import xml.etree.ElementTree as E
import zipfile

from chairs import inventory
from cooking_pots import rotate, vector
from entity_visuals import world_transform, quaternion_product as qmul
from region_travel import guid
from upgrade_map import read, xml
from world_lighting import defaults, overlay, shadow_spec

PREFIX = 'gm_fire_light_'


def transform(parent, child):
    p,q,s=parent
    cp,cq,cs=world_transform(child,{})
    offset=rotate(q,tuple(cp[i]*s[i] for i in range(3)))
    return tuple(p[i]+offset[i] for i in range(3)),qmul(q,cq),tuple(s[i]*cs[i] for i in range(3))


def expand(prefab, archetypes, schema, effects):
    """Resolve a whole prefab before emitting anything; unknown parts fail closed."""
    result=[]
    for obj in prefab.findall('Objects/Object'):
        kind=obj.get('EntityClass')
        if kind in ('PrefabRoot','TagPoint'):continue
        props=obj.find('Properties')
        if obj.get('Type')=='EntityArchetype':
            donor=archetypes.get(obj.get('Prototype','').lower())
            if donor is None or donor.get('Class')!='Light':
                raise ValueError('Missing light archetype '+str(obj.get('Prototype')))
            kind='Light';props=copy.deepcopy(donor.find('Properties'))
            overlay(props,obj.find('Properties'))
        if kind=='Light':
            native=copy.deepcopy(schema);overlay(native,props,supported_only=True)
            native.set('bSaved_by_game','0')
            shadow=native.find('Shadows');shadow.set('nCastShadows',shadow_spec(shadow.get('nCastShadows')))
            for node,key in [('Projector','texture_Texture'),('Options','file_deferred_clip_geom'),
                             ('Style','flare_Flare'),('Style','lightanimation_LightAnimation')]:
                if native.find(node).get(key):raise ValueError('Unmapped light resource '+key)
            props=native
        elif kind=='ParticleEffect':
            name=props.get('ParticleEffect','') if props is not None else ''
            if name.lower() not in effects:raise ValueError('Missing native particle '+name)
            props=copy.deepcopy(props);props.set('ParticleEffect',effects[name.lower()])
            props.set('bActive','1');props.set('bSaved_by_game','0')
        else:raise ValueError('Unsupported fire prefab component '+str(kind))
        node=E.Element('Entity',EntityClass=kind)
        for key in ('Pos','Rotate','Scale','ViewDistRatio'):
            if obj.get(key):node.set(key,obj.get(key))
        node.append(props);result.append((obj.get('Id'),node))
    if not result:raise ValueError('Empty fire prefab')
    return result


def append_group(root, key, parent, components):
    names={e.get('Name'):e for e in root}
    next_id=max(int(e.get('EntityId','0')) for e in root)+1
    added=0
    for identity,template in components:
        name=PREFIX+key+'_'+identity.strip('{}').lower()
        p,q,s=transform(parent,template)
        node=copy.deepcopy(template)
        node.set('Name',name);node.set('EntityGuid',guid('fire-light/'+key+'/'+identity.lower()))
        node.set('Pos',vector(p));node.set('Rotate',vector(q));node.set('Scale',vector(s))
        node.set('CastShadowMinSpec','1')
        existing=names.get(name)
        if existing is not None:
            node.set('EntityId',existing.get('EntityId'))
            if E.tostring(node)!=E.tostring(existing):raise ValueError('Changed registered light '+name)
            continue
        if next_id==0x7777:next_id+=1
        if next_id>=65534:raise ValueError('Light registration exceeds static entity IDs')
        node.set('EntityId',str(next_id));next_id+=1
        root.append(node);added+=1
    return added


def table_candle(root, native):
    """Use the native small candle's mesh, flame offsets and flickering light."""
    tables=[e for e in root if e.get('Name')=='gm_forge_loft_table']
    if not tables:return 0
    table=tables[0];parent=world_transform(table,{})
    anchor=E.Element('Entity',Pos='.21,-.19,.75041')
    parent=transform(parent,anchor)
    prefab=E.fromstring(read(native,'Prefabs/staticlights/candleSmall.xml'))
    components=[]
    for obj in prefab.findall('Objects/Object'):
        if obj.get('Type')=='Decal':continue
        node=E.Element('Entity',**{k:v for k,v in obj.attrib.items() if k in ('Pos','Rotate','Scale','ViewDistRatio')})
        if obj.get('Type')=='Brush':
            node.set('EntityClass','BasicEntity')
            if obj.get('Material'):node.set('Material',obj.get('Material'))
            props=E.SubElement(node,'Properties',object_Model=obj.get('Prefab'),bSaved_by_game='0')
            E.SubElement(props,'Physics',bPhysicalize='1',bRigidBody='0',Mass='-1',Density='-1')
        elif obj.get('Type')=='Prefab':
            particle=E.fromstring(read(native,'Prefabs/'+obj.get('PrefabTemplateName')+'.xml'))
            children=particle.findall('Objects/Object')
            if len(children)!=1 or children[0].get('EntityClass')!='ParticleEffect':raise ValueError('Native candle particle changed')
            node.set('EntityClass','ParticleEffect');node.append(copy.deepcopy(children[0].find('Properties')))
        elif obj.get('EntityClass')=='Light':
            node.set('EntityClass','Light');node.append(copy.deepcopy(obj.find('Properties')))
        else:raise ValueError('Unknown native candle component')
        components.append((obj.get('Id'),node))
    if Counter(n.get('EntityClass') for _,n in components)!=Counter({'Light':1,'ParticleEffect':1,'BasicEntity':1}):
        raise ValueError('Native candle must include mesh, flame and light')
    return append_group(root,'loft_table',parent,components)


def build(mission, source, target):
    root=E.fromstring(mission);source,target=Path(source),Path(target)
    from cooking_pots import inventory as pots
    from world_environment import native_catalog
    effects,_=native_catalog(target)
    with zipfile.ZipFile(source/'Data/Levels/rataje/level.pak') as z:
        entities,selected,deferred=inventory(z,'ProceduralObject')
        _,cooking,_=pots(z)
    existing={e.get('Name') for e in root}
    controlled=set()
    for pot,owner,kind in cooking:
        donor='16229' if kind=='camp' else '24041'
        if 'gm_cooking_'+pot.get('EntityId')+'_'+donor in existing:
            controlled.update(l.get('TargetId') for l in owner.findall('EntityLinks/Link')
                              if l.get('Name','').startswith('fireProcedural'))
    with zipfile.ZipFile(source/'Data/GameData.pak') as z:
        library=E.fromstring(read(z,'Prefabs/fires.xml'))
        prefabs={library.get('Name')+'.'+p.get('Name'):p for p in library}
        archetypes={p.get('Id').lower():p for p in E.fromstring(read(z,'Libs/EntityArchetypes/Lights.xml'))}
    with zipfile.ZipFile(target/'Data/Scripts.pak') as z:
        schema=defaults(read(z,'Scripts/Entities/Lights/Light.lua'))
    report=dict(version=1,records=[],added=0,runtime_verified=False,
                inactive_procedurals=len(deferred),controlled_fireplaces=0)
    compiled={}
    for e in selected:
        props=e.find('Properties')
        if props is None or props.get('filePrefabLibrary','').lower()!='prefabs/fires.xml':continue
        key=e.get('EntityId');variation=props.find('ObjectVariation').get('sPrefabVariation')
        record=dict(source_id=key,variation=variation);report['records'].append(record)
        if key in controlled:
            record['status']='existing_cooking_lifecycle';report['controlled_fireplaces']+=1;continue
        if variation not in compiled:
            try:compiled[variation]=expand(prefabs[variation],archetypes,schema,effects)
            except (KeyError,ValueError) as error:compiled[variation]=str(error)
        parts=compiled[variation]
        if isinstance(parts,str):record.update(status='unsupported',reason=parts);continue
        report['added']+=append_group(root,key,world_transform(e,entities),parts)
        record.update(status='registered',entities=len(parts))
    with zipfile.ZipFile(target/'Data/IPL_GameData.pak') as z:
        report['table_candle_added']=table_candle(root,z)
    report['coverage']=dict(Counter(r['status'] for r in report['records']))
    return xml(root),report


def upgrade(package,source,target):
    from setup_package_upgrade import rewrite
    from upgrade_map import digest
    package=Path(package);path='Data/Levels/kcd1_travel/level.pak'
    with zipfile.ZipFile(package/path) as z:before=read(z,'objects_mission0.xml')
    after,report=build(before,source,target)
    if before!=after:rewrite(package,path,{'objects_mission0.xml':after})
    return {path:digest(package/path)},report
