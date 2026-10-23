"""Fresh/resumed package upgrade for native walking/riding road encounters."""
import hashlib
import json
from pathlib import Path
import re
import xml.etree.ElementTree as E
import zipfile

from campaign_entity_links import guid_value
from campaign_trigger_areas import read_areas
from upgrade_map import read, xml

VERSION=1
RECORD='world-encounters.json'
TRAVEL='Data/gluemappertravel.pak'


def digest(data):return hashlib.sha256(data).hexdigest()


def owned_state(files, entity_guids, row_guids):
    """Independent edits elsewhere in the world must not invalidate this stage."""
    entities=set(entity_guids);rows=set(row_guids)
    mission=E.fromstring(files['objects_mission0.xml'])
    selected=[e for e in mission if e.get('EntityGuid') in entities]
    if {e.get('EntityGuid') for e in selected}!=entities or len(selected)!=len(entities):raise ValueError('Missing/duplicate encounter entity')
    all_ids={e.get('EntityId'):e.get('EntityGuid') for e in mission}
    for e in selected:
        for l in e.findall('EntityLinks/Link'):
            if all_ids.get(l.get('TargetId'))!=l.get('TargetGuid'):raise ValueError('Dangling encounter entity link')
    scheduler=E.fromstring(files['tables/ai/scheduler.xml'])
    owned_rows=[r for r in scheduler.find('Schedulers') if r.get('EntityGuid') in rows]
    if len(owned_rows)!=len(rows) or {r.get('EntityGuid') for r in owned_rows}!=rows:raise ValueError('Missing/duplicate encounter scheduler owner')
    numbers={str(guid_value(g)) for g in entities}
    for r in owned_rows:
        for l in r.findall('Links/S_ActivityLink'):
            if l.get('TargetGuid') not in numbers:raise ValueError('Encounter scheduler points outside its portable resources')
    waiting=E.fromstring(files['waitinglinks.xml'])
    links=[e for e in waiting.iter('WaitingLink') if e.get('SourceId') in entities or e.get('TargetId') in entities]
    shapes=read_areas(files['triggerareas.fubar'])['areas']
    def canonical(e):
        from gambler_dialogue_registration import semantic_xml
        return repr(semantic_xml(e)).encode()
    return dict(entities={e.get('EntityGuid'):digest(canonical(e)) for e in selected},
        schedulers={r.get('EntityGuid'):digest(canonical(r)) for r in owned_rows},
        links=digest(b''.join(sorted(canonical(l) for l in links))),
        areas=digest(repr(sorted((a.guid,a.height,a.points) for a in shapes if str(a.guid) in numbers)).encode()))


def validate(package,report):
    package=Path(package)
    if report.get('version')!=VERSION:raise ValueError('Unsupported encounter upgrade receipt')
    level=report['level_pak']
    with zipfile.ZipFile(package/level) as z:
        files={n:read(z,n) for n in ('objects_mission0.xml','tables/ai/scheduler.xml','waitinglinks.xml','triggerareas.fubar')}
    if owned_state(files,report['entities'],report['scheduler_rows'])!=report['owned_state']:raise ValueError('Changed owned native encounter world data')
    with zipfile.ZipFile(package/TRAVEL) as z:
        for path,sha in report['resources'].items():
            if digest(read(z,path))!=sha:raise ValueError('Changed native encounter module: '+path)
        from setup_gameplay import PROJECT
        host=E.fromstring(read(z,PROJECT)).find('Skald/Project')
        for name,path in [('random_events','encounters/random_events.xml'),('gm_native_encounter_places','encounters/places.xml')]:
            if len(host.findall("Nodes/"+name+"[@Name='"+name+"']"))!=1 or len(host.findall("Definitions/Definition[@File='"+path+"']"))!=1:raise ValueError('Missing native encounter registration')
        mounted='Mods/'+report['mod_id']+'/'+level.removesuffix('/level.pak')+'/tables/ai/scheduler.xml'
        if read(z,mounted)!=files['tables/ai/scheduler.xml']:raise ValueError('Stale mounted encounter scheduler')
    return report


def upgrade(package,source,target):
    from setup_campaign import RECEIPT,digest as file_digest
    from setup_gameplay import PROJECT,ENTRY
    from setup_package_upgrade import rewrite
    from campaign_sources import RetailSourceReader
    from world_encounter_sites import discover
    from world_encounter_registration import prepare
    package=Path(package)
    if (package/RECORD).exists():
        report=json.loads((package/RECORD).read_text(encoding='utf-8'))
        return {},validate(package,report)
    if source is None or target is None:raise ValueError('Both source games are required for native world encounters')
    source,target=map(Path,(source,target));receipt=json.loads((package/RECEIPT).read_text(encoding='utf-8'))
    source_level=receipt['campaign_level'].removeprefix('kcd1_');level=receipt['travel_bridge']['destination']
    if not all(re.fullmatch('[A-Za-z0-9_]+',s) for s in (source_level,level)):raise ValueError('Invalid encounter level identity')
    with RetailSourceReader(source) as reader:
        data=reader(source,{n:('Tables.pak','Libs/Tables/'+n+'.xml') for n in ('random_event','random_event_option_set')})
    tables={n:[r.attrib for r in E.fromstring(v['data']).iter('row')] for n,v in data.items()}
    with zipfile.ZipFile(source/'Data/Levels'/source_level/'level.pak') as z:sites,deferred=discover(z,tables)
    lp='Data/Levels/'+level+'/level.pak'
    with zipfile.ZipFile(package/lp) as z:files={n:read(z,n) for n in ('objects_mission0.xml','waitinglinks.xml','tables/ai/scheduler.xml','triggerareas.fubar')}
    with zipfile.ZipFile(package/TRAVEL) as z:resources={PROJECT:read(z,PROJECT)}
    updated,definitions,report=prepare(files,resources,target,sites,PROJECT,ENTRY)
    mod_id=E.parse(package/'mod.manifest').findtext('info/modid')
    if not mod_id:raise ValueError('Missing encounter mount identity')
    definitions['Mods/'+mod_id+'/Data/Levels/'+level+'/tables/ai/scheduler.xml']=updated['tables/ai/scheduler.xml']
    report.update(version=VERSION,status='native_road_encounters',level_pak=lp,mod_id=mod_id,source_level=source_level,
        deferred=deferred,owned_state=owned_state(updated,report['entities'],report['scheduler_rows']),
        resources={n:digest(b) for n,b in definitions.items() if n.startswith('Quests/GlueTravel/encounters/')})
    rewrite(package,lp,updated);rewrite(package,TRAVEL,definitions)
    validate(package,report)
    pending=package/(RECORD+'.pending');pending.write_text(json.dumps(report,indent=2),encoding='utf-8');pending.replace(package/RECORD)
    return {p:file_digest(package/p) for p in (lp,TRAVEL,RECORD)},report
