"""Bind native encounter modules to authored source-road positions."""
import copy
import collections
import posixpath
from pathlib import Path
import xml.etree.ElementTree as E
import zipfile

from campaign_entity_links import append_links, guid_value
from campaign_trigger_areas import TriggerArea, read_areas, write_areas
from character_work_pool import identity
from gambler_dialogue_registration import semantic_xml
from upgrade_map import read, xml
from world_encounter_graphs import DEST, VARIANTS, module, prepare as graphs_prepare
from world_encounter_sites import hull


def validate_spawn_catalog(graphs, tables):
    """Every selected native NPC and pool must exist in the installed catalog."""
    from character_person import native_xml
    souls = {e.get('soul_name') for n in tables.namelist()
             if n.lower().startswith('libs/tables/rpg/soul') and n.lower().endswith('.xml')
             for e in native_xml(read(tables, n)).iter('soul')}
    pools = {e.get('Name'): e for e in native_xml(read(tables, 'Libs/Tables/rpg/SoulPool.xml')).find('SoulPools')}
    groups = [e for b in graphs.values() for e in E.fromstring(b).iter('NpcGroup')]
    selected = set(); used_pools = set()
    for group in groups:
        if group.get('SoulName'): selected.add(group.get('SoulName'))
        elif group.get('SoulPool'):
            name = group.get('SoulPool'); pool = pools.get(name)
            if pool is None or pool.tag != 'StaticSoulPool': raise ValueError('Unsupported native encounter soul pool: '+name)
            members = {e.get('SoulName') for e in pool.findall('Elements/SoulPoolElement')}
            if not members or None in members: raise ValueError('Invalid native encounter soul pool: '+name)
            selected.update(members); used_pools.add(name)
        else: raise ValueError('Native encounter group has no NPC source')
    if selected-souls: raise ValueError('Missing native encounter souls: '+str(sorted(selected-souls)))
    return dict(souls=sorted(selected), pools=sorted(used_pools))


def native_contract(target, family):
    """Use a shipped compiled proxy; retain native priorities and urgency."""
    with zipfile.ZipFile(Path(target)/'Data/Levels/trosecko/level.pak') as z:
        entities={e.get('EntityId'):e for e in E.fromstring(read(z,'objects_mission0.xml'))}
        rows={r.get('EntityGuid'):r for r in E.fromstring(read(z,'tables/ai/scheduler.xml')).find('Schedulers')}
    aliases=('spawnPoints','behaviors','proxy_wayfarer' if family=='pocestny' else 'proxy_holdUp')
    donors=sorted((e for e in entities.values() if e.get('EntityClass')=='RandomEvent'
        and ('[event/'+family+'/'+family).lower() in e.get('Name','').lower()),key=lambda e:e.get('EntityGuid'))
    for donor in donors:
        bound={l.get('Name'):entities.get(l.get('TargetId')) for l in donor.findall('EntityLinks/Link')}
        if all(bound.get("asset['"+a+"']") is not None for a in aliases):break
    else:raise ValueError('No complete native encounter proxy: '+family)
    chosen={a:bound["asset['"+a+"']"] for a in aliases}
    chosen['event']=donor
    compiled={a:rows.get(str(guid_value(e.get('EntityGuid')))) for a,e in chosen.items()}
    if compiled[aliases[-1]] is None or compiled['behaviors'] is None:raise ValueError('Missing native encounter scheduler')
    with zipfile.ZipFile(Path(target)/'Data/Scripts.pak') as z:
        candidates=[]
        for n in z.namelist():
            if not n.startswith('Quests/Final/Barbora/trosecko/eventPlaces/') or not n.endswith('.xml'):continue
            host=E.fromstring(read(z,n)).find('Skald')[0]
            if host.tag=='RandomEventPlace' and host.find('Nodes/'+family) is not None and host.get('GlobalCooldownType','')!='City':candidates.append(host)
    if not candidates:raise ValueError('Missing native roadside encounter policy')
    # Use the most frequent shipped roadside policy rather than the difficulty
    # of an arbitrary donor placement. Native player-difficulty mixing remains.
    policy={k:collections.Counter(c.get(k) for c in candidates if c.get(k) is not None).most_common(1)[0][0]
            for k in ('Cooldown','Difficulty','DifficultyMixRatio','ViewRadius')}
    return chosen,compiled,policy


def prepare(files, resources, target, sites, project_path, entry_path):
    target=Path(target); resources=dict(resources); files=dict(files)
    with zipfile.ZipFile(target/'Data/Scripts.pak') as z:
        graphs,report=graphs_prepare(z)
        native_project=E.fromstring(read(z,'Quests/Final/Barbora.xml')).find('Skald/Project')
    with zipfile.ZipFile(target/'Data/IPL_GameData.pak') as z:
        from world_gameplay_basis import validate_dependency_scopes
        report['validated_graphs']=validate_dependency_scopes(graphs,DEST,read(z,'Libs/concept/definitions.xml'))
    with zipfile.ZipFile(target/'Data/Tables.pak') as z:
        report['spawn_catalog']=validate_spawn_catalog(graphs,z)
    project=E.fromstring(resources[project_path]);host=project.find('Skald/Project')
    for name in ('player','player_any'):
        old=host.find("Assets/*[@Name='"+name+"']");native=native_project.find("Assets/*[@Name='"+name+"']")
        if old is None:host.find('Assets').append(copy.deepcopy(native))
        elif semantic_xml(old)!=semantic_xml(native):raise ValueError('Incompatible native encounter player asset: '+name)
    used={v for b in graphs.values() for e in E.fromstring(b).iter() for k,v in e.attrib.items() if k in ('Type','TypeT')}
    types=host.find('Types')
    if types is None:types=E.SubElement(host,'Types')
    for t in native_project.findall('Types/Type'):
        if t.get('TypeName') not in used:continue
        old=types.find("Type[@TypeName='"+t.get('TypeName')+"']")
        if old is None:types.append(copy.deepcopy(t))
        elif semantic_xml(old)!=semantic_xml(t):raise ValueError('Incompatible native encounter type')
    # Check inherited aliases across the selected closure, not just file presence.
    def assets(path,inherited):
        m=E.fromstring(graphs[path]).find('Skald')[0];scope=inherited|{a.get('Name') for a in m.findall('Assets/*')}
        missing={a.get('Alias') for a in m.iter('Asset')}-scope
        if missing:raise ValueError('Unbound encounter assets '+path+': '+str(sorted(missing)))
        for d in m.findall('Definitions/*'):assets(posixpath.normpath(posixpath.join(posixpath.dirname(path),d.get('File'))),scope)
    assets(DEST,{a.get('Name') for a in host.findall('Assets/*')})
    for name,path in (('random_events',DEST),('gm_native_encounter_places','Quests/GlueTravel/encounters/places.xml')):
        if host.find("Nodes/*[@Name='"+name+"']") is not None:raise ValueError('Encounter registration already exists without its receipt')
        E.SubElement(host.find('Definitions'),'Definition',File=posixpath.relpath(path,posixpath.dirname(project_path)))
        E.SubElement(host.find('Nodes'),name,Name=name)
    places=module('gm_native_encounter_places');placehost=places.find('Skald')[0]
    mission=E.fromstring(files['objects_mission0.xml']);scheduler=E.fromstring(files['tables/ai/scheduler.xml'])
    areas=read_areas(files['triggerareas.fubar']);waiting=[];created=[];created_rows=[]
    next_id=max(int(e.get('EntityId','0')) for e in mission)+1
    def create(key,cls,pos,prototype=None):
        nonlocal next_id
        e=copy.deepcopy(prototype) if prototype is not None else E.Element('Entity')
        e.attrib={'Name':'gm_encounter_'+key,'EntityId':str(next_id),'EntityGuid':identity('native-encounter/v1/'+key),
                  'EntityClass':cls,'Pos':pos}
        for child in list(e):
            if child.tag!='Properties':e.remove(child)
        if e.find('Properties') is not None:e.find('Properties').set('bSaved_by_game','0')
        next_id+=1;mission.append(e);created.append(e);return e
    def link(a,b,label):
        ls=a.find('EntityLinks')
        if ls is None:ls=E.SubElement(a,'EntityLinks')
        E.SubElement(ls,'Link',Name=label,TargetId=b.get('EntityId'),TargetGuid=b.get('EntityGuid'))
        waiting.append((a.get('EntityGuid'),b.get('EntityGuid'),label))
    owner=next(e for e in mission if e.get('Name')==host.get('Name') and e.get('EntityClass')=='SmartObjectHolder')
    holder=create('places','SmartObjectHolder',owner.get('Pos'))
    link(owner,holder,"module['gm_native_encounter_places']")
    contracts={f:native_contract(target,f) for f in {s['native_family'] for s in sites}}
    placed=[]
    for site in sites:
        family=site['native_family'];native,rows,policy=contracts[family];key=site['guid'].lower();name='road_'+key
        path='Quests/GlueTravel/encounters/sites/'+name+'.xml'
        root=module(name,'RandomEventPlace',**policy);pm=root.find('Skald')[0]
        node=E.SubElement(pm.find('Nodes'),family,Name=family,Namespace='random_events.'+family+'.event_'+family)
        if family=='pocestny':E.SubElement(node,'Constant',Name='city_pocestny',Value='false')
        cache=E.SubElement(E.SubElement(pm,'EventsCache'),'RandomEventCache',Name=family)
        for variant in (VARIANTS[family] if family=='pocestny' else ('attack_on_sight',)):
            attributes={'Name':variant}
            if variant=='lost_meaning_of_life':attributes['HasFastTravel']='false'
            E.SubElement(cache,'RandomEventVariantCache',**attributes)
        graphs[path]=xml(root)
        E.SubElement(placehost.find('Definitions'),'Definition',File='sites/'+name+'.xml')
        instance=E.SubElement(placehost.find('Nodes'),name,Name=name)
        E.SubElement(instance,'Constant',Name='IsEnabled',Value='true')
        anchor=site['spawns'][0].get('Pos');place=create(key+'_place','RandomEventPlace',anchor)
        link(holder,place,"module['"+name+"']")
        event=create(key+'_event','RandomEvent',anchor,native['event'])
        # Native graphs own spawning; never invoke the old numeric event table.
        if event.find('Properties') is not None:
            event.find('Properties').attrib.pop('gpGameProfile',None)
            event.find('Properties').attrib.pop('nRandomEventDBId',None)
        link(place,event,"module['"+family+"']")
        mapped={}
        for alias in ('behaviors','proxy_wayfarer' if family=='pocestny' else 'proxy_holdUp'):
            donor=native[alias];e=create(key+'_'+alias,donor.get('EntityClass'),anchor,donor);mapped[alias]=e
            link(event,e,"asset['"+alias+"']")
        if family=='prepadeniNaCeste':link(mapped['behaviors'],event,'eventEntity')
        for i,p in enumerate(site['spawns']):
            e=create(key+'_spawn_'+str(i),'TagPoint',p.get('Pos'))
            if p.get('Rotate'):e.set('Rotate',p.get('Rotate'))
            link(event,e,"asset['spawnPoints']")
        numbers={str(guid_value(native[a].get('EntityGuid'))):str(guid_value(e.get('EntityGuid'))) for a,e in mapped.items()}
        for alias,e in mapped.items():
            row=copy.deepcopy(rows[alias]);row.set('EntityGuid',str(guid_value(e.get('EntityGuid'))))
            links=row.find('Links')
            if links is not None:
                for l in list(links):
                    if l.get('TargetGuid') not in numbers:links.remove(l);continue
                    if l.get('PositioningDelegate')!='0':raise ValueError('Native encounter uses an external positioning delegate')
                    l.set('TargetGuid',numbers[l.get('TargetGuid')])
            scheduler.find('Schedulers').append(row);created_rows.append(row)
        # Use original approach geometry and authored ground points. A native
        # place encloses its approaches, unlike KCD1's pair of thin triggers.
        points=[p for _,a in site['triggers'] for p in a.points]
        bottom=min(p[2] for p in points);top=max(p[2]+a.height for _,a in site['triggers'] for p in a.points)
        area=create(key+'_trigger','TriggerArea',anchor)
        geometry=TriggerArea(guid_value(area.get('EntityGuid')),top-bottom,tuple((x,y,bottom) for x,y in hull(points)))
        areas['areas'].append(geometry);link(place,area,"asset['RandomEventPlaceTrigger']")
        for i,(t,_) in enumerate(site['triggers']):
            far=create(key+'_approach_'+str(i),'TagPoint',t.get('Pos'))
            if t.get('Rotate'):far.set('Rotate',t.get('Rotate'))
            link(place,far,"asset['PlayerSpawnPoint_Far']")
        # No close landing is guessed onto an NPC spawn. Fast-travel interruption
        # stays disabled until the source provides a distinct authored landing.
        for c in cache:c.set('HasFastTravel','false')
        graphs[path]=xml(root)
        placed.append(dict(name=site['name'],source_guid=site['guid'],profile=site['profile'],family=family,
            place=place.get('EntityGuid'),event=event.get('EntityGuid'),spawn_guids=[p.get('EntityGuid') for p in site['spawns']],
            native_policy=policy,fast_travel=False))
    graphs['Quests/GlueTravel/encounters/places.xml']=xml(places)
    resources.update(graphs);resources[project_path]=xml(project)
    files.update({'objects_mission0.xml':xml(mission),'tables/ai/scheduler.xml':xml(scheduler),
        'waitinglinks.xml':append_links(files['waitinglinks.xml'],waiting),'triggerareas.fubar':write_areas(areas['areas'],areas['export_version'])})
    from character_person_activity import validate_scheduler_targets
    validate_scheduler_targets(scheduler)
    report.update(sites=placed,entities=[e.get('EntityGuid') for e in created],scheduler_rows=[r.get('EntityGuid') for r in created_rows],
        fast_travel='disabled: no validated close player landing in the source event contract',
        activity_adaptation='native idle/dialogue/leave-level; destination-town optional daycycles excluded')
    return files,resources,report
