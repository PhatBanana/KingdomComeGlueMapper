"""Stage native cross-style prayer interactions at authored KCD1 church spots."""
import argparse
import copy
import json
import math
from pathlib import Path
import xml.etree.ElementTree as ET
import zipfile

from build_horse_trader_test import digest, rewrite
from build_smithing_voice import wrapper
from campaign_entity_links import append_links, guid_value
from chairs import inventory
from character_blacksmith_jobs import pose, vector
from cooking_pots import rotate
from entity_visuals import quaternion_product
from region_travel import guid
from seating_animations import HELPERS, ANIMATIONS
from upgrade_map import read, xml

SITES = {'12746':'Rattay lower church', '12824':'Rattay upper church',
         '9869':'Talburg castle chapel', '11950':'Sasau monastery',
         '10157':'Uzhitz church', '12275':'Sasau church'}
SCHEDULER='tables/ai/scheduler.xml'
FILES=('objects_mission0.xml','waitinglinks.xml',HELPERS,ANIMATIONS,SCHEDULER)
OPEN_WORLD='Quests/GlueTravel/smithing_voice/open_world.xml'
PRAYER='Quests/Final/Barbora/open_world/perky/zaklady_bohoslovectvi__modlitba.xml'

# Reviewed source altar brushes. The trigger sits on the approach-facing edge;
# the separate animation anchor stays on the floor, outside the altar mesh.
ALTARS = {
    '12824': ((2682.81372,641.11523,100.96488), (2680.55,640.837,100.358), 1.0),
    '9869': ((2338.87573,2757.18994,110.07301), (2337.25,2757.05,110.07301), 0.5),
    '11950': ((992.30103,1697.27197,39.65410), (990.25,1696.35,39.56950), 0.7),
    '12275': ((868.68036,1171.66711,29.60938), (868.05,1169.8,29.32676), 0.7),
}


def attach_altars(files):
    """Relocate existing native pairs without replacing their IDs or links."""
    root=ET.fromstring(files['objects_mission0.xml'])
    animations=ET.fromstring(files[ANIMATIONS]); report=[]
    # Church prayer is available without the roadside-cross perk. Native
    # perkPraying already selects dialogue for both theology states.
    for node in root:
        if node.get('Name','').startswith('gm_church_pray_') and node.get('Name','').endswith('_trigger'):
            node.find('Properties/Click').set('guidRequiredScriptPerk','')
    for key,(altar,floor,edge) in ALTARS.items():
        nodes={role:next(e for e in root if e.get('Name')==f'gm_church_pray_{key}_{role}') for role in ('spot','trigger')}
        dx,dy=altar[0]-floor[0],altar[1]-floor[1]
        length=math.hypot(dx,dy); dx/=length;dy/=length
        yaw=math.atan2(-dx,dy)
        q=(math.cos(yaw/2),0,0,math.sin(yaw/2))
        trigger=(altar[0]-dx*edge,altar[1]-dy*edge,floor[2]+1.05)
        for role,p,rotation in [('spot',floor,q),('trigger',trigger,(math.cos((yaw+math.pi)/2),0,0,math.sin((yaw+math.pi)/2)))]:
            nodes[role].set('Pos',','.join(map(str,p)))
            nodes[role].set('Rotate',','.join(map(str,rotation)))
        click=nodes['trigger'].find('Properties/Click')
        click.set('fActiveDistance','2.5')
        click.find('Angle').set('fAngleTolerance','100')
        row=next(e for e in animations.find('SmartObjectAnimationss') if e.get('EntityGuid')==str(guid_value(nodes['spot'].get('EntityGuid'))))
        transform=row.find('SmartObjectTransform')
        transform.set('Position',nodes['spot'].get('Pos'));transform.set('Rotation',nodes['spot'].get('Rotate'))
        report.append(dict(location=SITES[key],source_id=key,altar=altar,position=floor,interaction_position=trigger))
    return dict(files,**{'objects_mission0.xml':xml(root),ANIMATIONS:xml(animations)}),report


def convert(files,source,native):
    root=ET.fromstring(files['objects_mission0.xml'])
    if any(e.get('Name','').startswith('gm_church_pray_') for e in root):
        raise ValueError('Church prayer already installed')
    src,_,_=inventory(source)
    donors={e.get('EntityId'):e for e in ET.fromstring(read(native,'objects_mission0.xml'))}
    spot,trigger=donors['30110'],donors['30109']
    if spot.find('Properties').get('guidSmartObjectType')!='2cae9c25-e346-4812-80e8-67761475df6c':
        raise ValueError('Native prayer contract changed')
    if trigger.find('Properties/Click').get('guidRequiredScriptPerk')!='d23569a9-0f9a-4328-8eb5-2bbc0d0ccdd4':
        raise ValueError('Native prayer perk gate changed')
    helpers=ET.fromstring(files[HELPERS])
    collection=next(e for e in ET.fromstring(read(native,HELPERS)) if e.get('HelperSetName')=='GenU_PrayKneelingGround')
    if not any(e.get('HelperSetName')=='GenU_PrayKneelingGround' for e in helpers):helpers.append(copy.deepcopy(collection))
    animation_hash=collection.find('SmartObjectHelperSetAnimationCollection').get('HashValue')
    animations=ET.fromstring(files[ANIMATIONS]);scheduler=ET.fromstring(files[SCHEDULER])
    next_id=max(int(e.get('EntityId','0')) for e in root)+1
    network=[];report=[]
    for key,label in SITES.items():
        target=src[key]
        if target.get('EntityClass')!='TagPoint' or target.get('Layer'):
            raise ValueError('Prayer target is not an active authored point: '+key)
        q=vector(target,'Rotate');p=vector(target)
        dq=vector(spot,'Rotate');delta=quaternion_product(q,(dq[0],-dq[1],-dq[2],-dq[3]))
        rotated=rotate(delta,vector(spot));offset=tuple(a-b for a,b in zip(p,rotated))
        nodes=[]
        for role,donor in [('spot',spot),('trigger',trigger)]:
            node=pose(donor,delta,offset)
            for attr in ('Prefab','Layer','EditorLayer','ParentId','ParentGuid'):node.attrib.pop(attr,None)
            node.set('Name',f'gm_church_pray_{key}_{role}')
            node.set('EntityId',str(next_id));next_id+=1
            node.set('EntityGuid',guid(f'church-prayer/{key}/{role}'))
            nodes.append(node)
        a,b=nodes
        link=b.find('EntityLinks/Link');link.set('TargetId',a.get('EntityId'));link.set('TargetGuid',a.get('EntityGuid'))
        network.append((b.get('EntityGuid'),a.get('EntityGuid'),'prayingSpot'))
        for node in nodes:
            ET.SubElement(scheduler.find('Schedulers'),'C_SmartHub',EntityGuid=str(guid_value(node.get('EntityGuid'))),IgnoreDeadEnds='false',StupidHub='false')
        row=ET.SubElement(animations.find('SmartObjectAnimationss'),'SmartObjectAnimations',
                          EntityGuid=str(guid_value(a.get('EntityGuid'))),Hash=animation_hash,AllowRuntimeAnimValidationFallback='true')
        ET.SubElement(row,'SmartObjectTransform',Position=a.get('Pos'),Rotation=a.get('Rotate','1,0,0,0'))
        root.extend(nodes)
        report.append(dict(location=label,source_id=key,source_name=target.get('Name'),position=p,rotation=q,
                           interaction_position=vector(b),entities=[e.get('Name') for e in nodes]))
    updated=dict(files)
    updated.update({'objects_mission0.xml':xml(root),'waitinglinks.xml':append_links(files['waitinglinks.xml'],network),
                    HELPERS:xml(helpers),ANIMATIONS:xml(animations),SCHEDULER:xml(scheduler)})
    return updated,report


def dialogue(open_world,scripts,recordings):
    root=ET.fromstring(open_world);host=root.find('Skald/Gameplay')
    if any(e.get('Name')=='perky' for e in host.find('Nodes')):raise ValueError('Existing prayer/perk module needs review')
    ET.SubElement(host.find('Definitions'),'Definition',File='../church_prayer/perky.xml')
    ET.SubElement(host.find('Nodes'),'perky',Name='perky')
    blob=read(scripts,PRAYER);prayer=ET.fromstring(blob)
    keys=[e.find('Text').get('StringName') for e in prayer.iter('Response') if e.find('Text') is not None]
    paths=['dialog/open_world/perky/tmck_'+key+'.ogg' for key in keys]
    missing=set(paths)-recordings
    if missing:raise ValueError('Missing native prayer recordings: '+str(sorted(missing)))
    return {OPEN_WORLD:xml(root),'Quests/GlueTravel/church_prayer/perky.xml':wrapper('perky','zaklady_bohoslovectvi__modlitba','prayer.xml'),
            'Quests/GlueTravel/church_prayer/prayer.xml':blob},paths


def build(library,mod,output):
    if output.exists():raise FileExistsError(output)
    game=library/'KCD2Mod';level='Data/Levels/kcd1_travel/level.pak';travel='Data/gluemappertravel.pak'
    recordings=set()
    for p in (game/'Localization').glob('*.pak'):
        if 'english' in p.name.lower():
            with zipfile.ZipFile(p) as z:recordings.update(z.namelist())
    with zipfile.ZipFile(mod/level) as installed,zipfile.ZipFile(library/'KingdomComeDeliverance/Data/Levels/rataje/level.pak') as source,zipfile.ZipFile(game/'Data/Levels/trosecko/level.pak') as native:
        files={n:read(installed,n) for n in FILES}
        existing=any(e.get('Name','').startswith('gm_church_pray_') for e in ET.fromstring(files['objects_mission0.xml']))
        if existing: updated=files
        else: updated,_=convert(files,source,native)
        updated,sites=attach_altars(updated)
    with zipfile.ZipFile(mod/travel) as z,zipfile.ZipFile(game/'Data/Scripts.pak') as scripts:
        if existing:
            resources={};paths=[]
        else:
            resources,paths=dialogue(read(z,OPEN_WORLD),scripts,recordings)
    modid=ET.parse(mod/'mod.manifest').findtext('info/modid')
    resources.update({f'Mods/{modid}/Data/Levels/kcd1_travel/{n}':updated[n] for n in (ANIMATIONS,SCHEDULER)})
    changes={level:updated,travel:resources}
    report=dict(sites=sites,prayer_recordings=paths,installed=False,runtime_verified=False,baseline={},packages={})
    for relative,replacements in changes.items():
        report['baseline'][relative]=digest(mod/relative)
        target=output/'package'/relative;rewrite(mod/relative,target,replacements)
        with zipfile.ZipFile(mod/relative) as a,zipfile.ZipFile(target) as b:
            assert {i.filename:(i.CRC,i.file_size) for i in a.infolist() if i.filename not in replacements}=={i.filename:(i.CRC,i.file_size) for i in b.infolist() if i.filename not in replacements}
            assert all(read(b,n)==v for n,v in replacements.items())
        report['packages'][relative]=digest(target)
    (output/'report.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(dict(sites=len(sites),recordings=len(paths),installed=False)))


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for key in ('library','mod','output'):p.add_argument('--'+key,type=Path,required=True)
    build(**vars(p.parse_args()))
