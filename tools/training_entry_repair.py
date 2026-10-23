"""Apply source arena entry to fresh and resumed gameplay packages."""
import hashlib
import json
from pathlib import Path
import xml.etree.ElementTree as E
import zipfile
from upgrade_map import read, xml

RECORD='training-entry-repair.json'


def upgrade(package, source, target):
    from setup_gameplay import ENTRY, PROJECT
    from setup_training_upgrade import validate
    from setup_package_upgrade import rewrite
    from setup_campaign import digest
    from setup_quest_invitation import graph_digest
    from campaign_sources import RetailSourceReader
    from campaign_training_entry import resolve, stage
    from campaign_quest_start_placement import unique
    from campaign_entity_links import append_links
    package=Path(package)
    training=validate(package)
    travel='Data/gluemappertravel.pak'; level='Data/Levels/kcd1_travel/level.pak'
    with zipfile.ZipFile(package/travel) as z:
        entry=E.fromstring(read(z,ENTRY));project=E.fromstring(read(z,PROJECT))
    with zipfile.ZipFile(package/level) as z:
        mission=E.fromstring(read(z,'objects_mission0.xml'));waiting=read(z,'waitinglinks.xml')
    if (package/RECORD).exists():
        receipt=json.loads((package/RECORD).read_text())
        for guid,expected in receipt['entities'].items():
            e=unique((e for e in mission if e.get('EntityGuid')==guid),'entry entity')
            if graph_digest(e)!=expected:raise ValueError('Training entry entity changed')
        for name,expected in receipt['nodes'].items():
            n=unique(entry.findall(".//Nodes/*[@Name='"+name+"']"),'entry node')
            if graph_digest(n)!=expected:raise ValueError('Training entry graph changed')
        for a,b,label in receipt['links']:
            e=unique((e for e in mission if e.get('EntityGuid')==a),'entry link origin')
            unique((l for l in e.findall('EntityLinks/Link') if l.get('TargetGuid')==b and l.get('Name')==label),'entry entity link')
            pairs=E.fromstring(waiting).findall("WaitingLinks/WaitingLink[@SourceId='"+a+"'][@TargetId='"+b+"']/LinkDefinition")
            unique((p for p in pairs if p.text==label),'entry network link')
        unique(project.findall(".//CutsceneHolderAsset[@Name='"+receipt['asset']+"']"),'entry scene asset')
        return {},dict(receipt,changed=False)
    if source is None or target is None:raise ValueError('Both games are required for arena entry upgrade')
    source,target=Path(source),Path(target)
    selection=training['selection'];quest=selection['quest'];stem='gm_training_'+quest
    with RetailSourceReader(source) as reader:
        records=reader(source,{'quest':('Scripts.pak','Libs/AI/quests/'+quest.lower()+'.xml'),
                               'arena':('Scripts.pak','Libs/AI/final/sa_duel.xml')})
    entities={}
    with zipfile.ZipFile(source/'Data/Levels/rataje/level.pak') as z:
        for n in z.namelist():
            key=n.replace('\\','/').lower()
            if key=='objects_mission0.xml' or key.startswith('layers/') and key.endswith('.xml'):
                for e in E.fromstring(read(z,n)).iter('Entity'):
                    if e.get('EntityId'):
                        e.tail=None
                        if e.get('EntityId') in entities and E.tostring(entities[e.get('EntityId')])!=E.tostring(e):
                            raise ValueError('Conflicting source entry entity copies')
                        entities[e.get('EntityId')]=e
        plan=resolve(records['quest']['data'],records['arena']['data'],selection['request'],quest,list(entities.values()),z)
    # This is a native content selection, verified against its shipped table.
    # Actor identities, positions and orientations remain source-derived.
    scene='trainingGrounds_teleport'
    with zipfile.ZipFile(target/'Data/Tables.pak') as z:
        table=E.fromstring(read(z,'Libs/Tables/ui/cutscene.xml'))
        unique(table.findall(".//FaderCutscene[@Name='"+scene+"']"),'native arena fader')
    actor=unique((e for e in mission if e.get('EntityGuid')==training['compiled_route']['actor']),'training actor')
    unique(project.findall(".//SoulAsset[@Name='"+selection['player_asset']+"']"),'registered player asset')
    links,guids=stage(mission,project,entry,stem,actor,plan,scene,selection['player_asset'])
    changes={ENTRY:xml(entry),PROJECT:xml(project)}
    rewrite(package,travel,changes)
    rewrite(package,level,{'objects_mission0.xml':xml(mission),'waitinglinks.xml':append_links(waiting,links)})
    nodes=entry.find('Skald/Level/Nodes')
    for n in nodes:
        if n.get('Name','').startswith(stem):training['graph_nodes'][n.get('Name')]=graph_digest(n)
    for path,payload in changes.items():
        if path in training['resources'][travel]:training['resources'][travel][path]=hashlib.sha256(payload).hexdigest()
    training['host']['arena_entry_requires_scene_release']=True
    def save(name,value):
        pending=package/(name+'.pending')
        pending.write_text(json.dumps(value,indent=2),encoding='utf-8');pending.replace(package/name)
    save('quest-training.json',training)
    receipt=dict(version=1,source=plan,native_scene=scene,links=links,runtime_verified=False,
        asset=stem+'_entry_scene',
        entities={e.get('EntityGuid'):graph_digest(e) for e in mission if e.get('EntityGuid') in guids},
        nodes={n.get('Name'):graph_digest(n) for n in nodes if n.get('Name','').startswith(stem+'_entry')})
    save(RECORD,receipt)
    validate(package)
    return {p:digest(package/p) for p in (travel,level,'quest-training.json',RECORD)},dict(receipt,changed=True)
