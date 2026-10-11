"""Native persistent item slots for authored, initially pickable world items."""
import math
import xml.etree.ElementTree as ET
import numpy as np
from campaign_entity_links import native_guid
from entity_visuals import quaternion_product as qmul
from upgrade_map import xml

PREFIX = 'gm_world_item_'


def rotation(matrix):
    """Quaternion (w,x,y,z) from an orthonormal column-vector matrix."""
    m=np.asarray(matrix,dtype=float)
    if not np.allclose(m.T@m,np.eye(3),atol=1e-5) or not np.isclose(np.linalg.det(m),1,atol=1e-5):
        raise ValueError('Item slot has a non-rigid local transform')
    trace=np.trace(m)
    if trace>0:
        s=math.sqrt(trace+1)*2
        return (s/4,(m[2,1]-m[1,2])/s,(m[0,2]-m[2,0])/s,(m[1,0]-m[0,1])/s)
    i=int(np.argmax(np.diag(m)));j=(i+1)%3;k=(i+2)%3
    s=math.sqrt(1+m[i,i]-m[j,j]-m[k,k])*2
    q=[0.,0.,0.,0.];q[0]=(m[k,j]-m[j,k])/s;q[i+1]=s/4
    q[j+1]=(m[j,i]+m[i,j])/s;q[k+1]=(m[k,i]+m[i,k])/s
    return tuple(q)


def placement_transform(record):
    pos,rot,scale=(record[k] for k in ('position','rotation','scale'))
    e=record['entity']
    if e.get('EntityClass')=='ItemSlot':
        p=e.find('Properties')
        rows=[tuple(map(float,p.get('vectorPIMatRow'+str(i+1),default).split(',')))
              for i,default in enumerate(('1,0,0','0,1,0','0,0,1','0,0,0'))]
        if any(len(r)!=3 or not all(map(math.isfinite,r)) for r in rows):raise ValueError('Invalid slot transform')
        local=rotation(np.array(rows[:3]).T)
        if max(scale)-min(scale)>1e-4 and max(abs(v) for v in local[1:])>1e-5:
            raise ValueError('Nonuniform item-slot parent scale creates shear')
        offset=qmul(qmul(rot,(0,*(rows[3][i]*scale[i] for i in range(3)))),(rot[0],-rot[1],-rot[2],-rot[3]))[1:]
        pos=tuple(pos[i]+offset[i] for i in range(3));rot=qmul(rot,local)
    return pos,rot,scale


def convert(files, placements, registered):
    root=ET.fromstring(files['objects_mission0.xml'])
    existing=list(root.iter('Entity'))
    if any(e.get('Name','').startswith(PREFIX) for e in existing):raise ValueError('World pickups already installed')
    guids={e.get('EntityGuid','').lower() for e in existing}
    next_id=max((int(e.get('EntityId','0')) for e in existing),default=0)+1
    converted=[];remove=set()
    for record in placements:
        source=record['entity'];props=source.find('Properties');key=source.get('EntityId')
        identity=record['item_id']
        if identity not in registered:raise ValueError('Unregistered pickup '+identity)
        if props.get('nAmount','1')!='1':raise ValueError('Item slot quantity needs an explicit native stack contract')
        if float(props.get('fRespawn','0'))!=0:raise ValueError('Source respawn units need explicit conversion')
        if props.get('ScriptCommand',''):raise ValueError('Source pickup script needs conversion')
        target_guid=native_guid(int(source.get('EntityGuid'),16))
        if target_guid in guids:raise ValueError('Pickup entity GUID collision: '+target_guid)
        guids.add(target_guid)
        pos,rot,scale=placement_transform(record)
        vector=lambda v:','.join(format(n,'.10g') for n in v)
        entity=ET.SubElement(root,'Entity',Name=PREFIX+key,EntityId=str(next_id),EntityGuid=target_guid,
            EntityClass='ItemSlot',Pos=vector(pos),Rotate=vector(rot),Scale=vector(scale),CastShadowMinSpec='1')
        next_id+=1
        p=ET.SubElement(entity,'Properties',guidItemClassId=registered[identity],bOnlyNPC='0',bSpawnOnStart='1',
            bHasItemPhysics='0',bInvisibleContent='0',bDisableDynamicSpawning='0',
            bOwnedByHome='1',bSaveBorrowedItem='1',nRestockPeriodDays='0',nDestockPeriodDays='0',
            ItemHealth=props.get('fHealth','-1'),Condition='-1',Blood='0',nQuality='0',
            bInteractiveCollisionClass=props.get('bInteractiveCollisionClass','0'))
        ET.SubElement(p,'Script',Misc='')
        remove.add('glue_item_'+key)
        converted.append(dict(source_id=key,source_name=source.get('Name'),source_class=source.get('EntityClass'),
            item_id=identity,entity_guid=target_guid,position=pos,source_links=[dict(l.attrib) for l in source.findall('EntityLinks/Link')]))
    removed=0
    for parent in root.iter():
        for child in list(parent):
            if child.get('Name') in remove:parent.remove(child);removed+=1
    result=dict(files);result['objects_mission0.xml']=xml(root)
    return result,dict(converted=len(converted),visuals_replaced=removed,records=converted,
        ownership='Native bOwnedByHome; ownership depends on registered homes in the destination world',
        persistence='Native ItemSlot bSaveBorrowedItem; restocking disabled',runtime_verified=False)
