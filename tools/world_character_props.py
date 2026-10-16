"""Recover omitted static CDF props with their source collision settings.

This supplies bind-pose geometry and collision, not animated interactions.
Selection follows source class and physics flags, never prop or location names.
"""
from contextlib import ExitStack
from pathlib import Path
import hashlib
import xml.etree.ElementTree as E
import zipfile
from entity_visuals import collect_visuals
from static_assets import asset_pack, character_definition
from campaign_entity_links import native_guid
from upgrade_map import xml


def build(mission, source, output, *, reuse_output=False):
    source,output=Path(source),Path(output)
    output.mkdir(parents=True,exist_ok=reuse_output)
    root=E.fromstring(mission); existing={e.get('Name') for e in root}
    next_id=max((int(e.get('EntityId','0')) for e in root),default=0)+1
    records=[]
    with ExitStack() as stack:
        z=stack.enter_context(zipfile.ZipFile(source/'Data/Levels/rataje/level.pak'))
        visuals,_=collect_visuals(z,source.parent)
        chosen=[v for v in visuals if v['source_class']=='AnimObject' and v['model'].endswith('.cdf')
                and v['entity'].find('Properties/Physics') is not None
                and v['entity'].find('Properties/Physics').get('bPhysicalize')=='1'
                and v['entity'].find('Properties/Physics').get('bRigidBody','0')=='0']
        index,emitted,material,mesh=asset_pack(stack,source.parent,'glueitems/character_props/',str(output))
        models={}
        for v in chosen:
            entity=v['entity']
            if entity.get('Name') in existing:continue
            variant=(v['model'],v['material'])
            if variant not in models:
                name='glueitems/character_props/'+hashlib.sha256(repr(variant).encode()).hexdigest()[:20]+'.cdf'
                character_definition(index,emitted,material,mesh,v['model'],name)
                models[variant]=name
            entity.find('Properties').set('object_Model',models[variant])
            if v['material']:entity.set('Material',material(v['material']))
            if next_id==0x7777:next_id+=1
            if next_id>=65534:raise ValueError('Static entity ID space exhausted')
            entity.set('EntityId',str(next_id));next_id+=1
            entity.set('EntityGuid',native_guid(int(hashlib.sha256(('character_prop/'+v['source_id']).encode()).hexdigest()[:16],16)))
            root.append(entity);existing.add(entity.get('Name'))
            records.append({k:value for k,value in v.items() if k!='entity'})
        for path,payload in emitted.items():
            dest=output/'converted'/path;dest.parent.mkdir(parents=True,exist_ok=True)
            dest.write_bytes(payload.read_bytes() if isinstance(payload,Path) else payload)
    return xml(root),dict(converted=records,source_collision_preserved=True,
                         animated_interactions_converted=False,runtime_verified=False)
