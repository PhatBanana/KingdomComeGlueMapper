"""Assemble source-selected training with a complete native lesson lifecycle.

Content selections live in setup_gameplay. This stage resolves source actors,
requests, objectives and borrowed equipment; it never supplies a destination,
start-hour, faction change or timeout of its own.
"""
from contextlib import ExitStack
import hashlib
import json
from pathlib import Path
import posixpath
import tempfile
from types import SimpleNamespace
import xml.etree.ElementTree as E
import zipfile

from campaign_quest_graph import xml, edge, constant
from campaign_quest_start_placement import unique
from upgrade_map import read

RECORD='quest-training.json'


def conversations(nodes, graphs, prefix):
    """Resolve dialogue instances by their definitions, never name-prefix alone."""
    definitions={}
    for blob in graphs.values():
        host=E.fromstring(blob).find('Skald/*')
        if host is not None and host.tag in ('Dialog','FaderDialog','ForcedDialog'):
            definitions[host.get('Name')]=host
    result=[n for n in nodes if n.get('Name','').startswith(prefix) and n.tag in definitions]
    if not result:raise ValueError('Missing authorization conversation instance')
    return result


def validate_references(entry, graphs, prefix):
    """Check generated host references against actual custom definitions."""
    hosts={}
    for blob in graphs.values():
        host=E.fromstring(blob).find('Skald/*')
        if host is not None:hosts[host.get('Name')]=host
    nodes={n.get('Name'):n for n in entry.findall('./Skald/Level/Nodes/*')}
    for name,node in nodes.items():
        if not name.startswith(prefix):continue
        for link in node.findall('Edge'):
            ref=link.get('From','');owner,sep,port=ref.partition('.')
            if not sep or owner not in nodes:raise ValueError('Unresolved training graph reference: '+ref)
            origin=nodes[owner];definition=hosts.get(origin.tag)
            if definition is not None:
                outputs={p.get('Name') for p in definition.findall('Ports/Port') if p.get('Direction')=='Out'}
                if definition.tag in ('Dialog','FaderDialog','ForcedDialog'):outputs.update(('BeforePlay','AfterPlay'))
                if port not in outputs:raise ValueError('Missing training source port: '+ref)
            elif port in ('BeforePlay','AfterPlay') and origin.tag != 'CutsceneHandler':
                raise ValueError('Training conversation event refers to a non-dialogue: '+ref)
        definition=hosts.get(node.tag)
        if definition is not None:
            inputs={p.get('Name') for p in definition.findall('Ports/Port') if p.get('Direction')=='In'}
            supplied={e.get('To') for e in node.findall('Edge')}|{e.get('Name') for e in node.findall('Asset')}
            if not supplied<=inputs:raise ValueError('Undeclared training input: '+str(supplied-inputs))


def validate(package):
    from setup_gameplay import ENTRY
    from setup_quest_invitation import graph_digest
    report=json.loads((package/RECORD).read_text(encoding='utf-8'))
    for pak,resources in report['resources'].items():
        with zipfile.ZipFile(package/pak) as z:
            for path,digest in resources.items():
                try: payload=read(z,path)
                except KeyError:
                    # Packaging moves objects/ into bounded asset shards after
                    # this provenance record is written. Verify their bytes
                    # there; never treat a missing gameplay graph as sharded.
                    if pak!='Data/gluemappertravel.pak' or not path.lower().startswith('objects/'): raise
                    matches=[]
                    for shard in sorted((package/'Data').glob('gluemappertravel_assets_*.pak')):
                        with zipfile.ZipFile(shard) as archive:
                            try: matches.append(read(archive,path))
                            except KeyError: pass
                    if len(matches)!=1: raise ValueError('Missing or duplicate training asset: '+path)
                    payload=matches[0]
                if hashlib.sha256(payload).hexdigest()!=digest:
                    raise ValueError('Training resource differs: '+path)
    with zipfile.ZipFile(package/'Data/gluemappertravel.pak') as z:entry=E.fromstring(read(z,ENTRY))
    for name,digest in report['graph_nodes'].items():
        node=unique(entry.findall(".//Nodes/*[@Name='"+name+"']"),'training binding '+name)
        if graph_digest(node)!=digest:raise ValueError('Training binding differs: '+name)
    if 'compiled_route' in report:
        route=report['compiled_route']
        from campaign_entity_links import guid_value
        from campaign_behavior_schedule import validate_compiled
        with zipfile.ZipFile(package/'Data/Levels/kcd1_travel/level.pak') as z:
            mission=E.fromstring(read(z,'objects_mission0.xml'));scheduler=E.fromstring(read(z,'tables/ai/scheduler.xml'))
        validate_compiled(mission,scheduler,[tuple(r) for r in route['links']])
        links=scheduler.findall(".//C_SmartHub[@EntityGuid='"+str(guid_value(route['actor']))+"']/Links/S_ActivityLink")
        matches=[n for n in links if n.get('TargetGuid')==str(guid_value(route['host'])) and
            n.find('Parameters') is not None and n.find('Parameters').get('BehaviorName')=='lesson']
        if len(matches)!=1:raise ValueError('Missing or duplicate compiled training activity')
    return report


def upgrade(package,source,target,*,selection=None):
    from setup_gameplay import TRAINING,ENTRY,PROJECT,LEVEL,quest_model
    from setup_package_upgrade import rewrite
    from setup_campaign import digest
    from setup_quest_invitation import validate as invitation_validate,graph_digest,RECORD as INVITATION
    from campaign_training_handoff import resolve
    from campaign_training_sources import resolve_equipment
    from campaign_training_equipment import lower
    from campaign_training_worker import emit as worker_files,basic_equipment_policy
    from campaign_training_native import assemble,bind_resources
    from campaign_training_schedule import bind as schedule
    from campaign_training_host import bind as host_bind
    from campaign_behavior import BehaviorCompiler,native_catalog
    from campaign_behavior_schedule import connect,validate_compiled
    from campaign_combat_work import validate as validate_ai
    from campaign_sources import RetailSourceReader
    from campaign_dependency_adapters import SourceTables,ItemTextAdapter
    from campaign_dependencies import DependencyImporter
    from campaign_buffs import BuffAdapter,native_contract
    from campaign_entity_links import append_links
    from character_person_world import native_wait_activity
    from container_items import build as import_items
    from build_actor_dialogues_test import build as dialogues
    from build_recipe import apply_overlay
    from dialogue_dubbing import DEPOT
    from dialogue_facials import INDEX
    selection=dict(TRAINING if selection is None else selection)
    if (package/RECORD).exists():
        report=validate(package)
        if report['selection']!=json.loads(json.dumps(selection)):raise ValueError('Training selection changed')
        return {},report
    if source is None or target is None:raise ValueError('Both games are required for training conversion')
    invitation=invitation_validate(package)
    q=selection['quest'];stem='gm_training_'+q;directory='Quests/GlueTravel/'+stem
    travel='Data/gluemappertravel.pak';level='Data/Levels/kcd1_travel/level.pak'
    with tempfile.TemporaryDirectory(prefix='training-',dir=package.parent) as temp,ExitStack() as stack:
        work=Path(temp)
        model=quest_model(source,work/'quest',q)
        original=(work/'quest/behavior.xml').read_bytes()
        plan=resolve(original,selection['arrival'],selection['request'])
        if plan['arrival']!={k:invitation['source'][k] for k in plan['arrival']}:
            raise ValueError('Training arrival differs from converted invitation')
        document='libs/ai/quests/'+q.lower()+'.xml'
        equipment=resolve_equipment(model,document,selection['controller'])
        # Import the actual source loan item and dependencies before compiling
        # equipment. Native item identity alone is not a model registration.
        items=import_items(source,target,package,work/'items',
            [lease['item'] for lease in equipment['equipment']['leases']],
            asset_namespace=stem+'_items',origin='source_training')
        reader=stack.enter_context(RetailSourceReader(source));tables=SourceTables(source,reader)
        importer=DependencyImporter({'buffs':BuffAdapter(tables,native_contract(target),stem),
            'strings':ItemTextAdapter(source,stem,'English')},
            {'items':items['registered_items'],'ai_types':{'player:holsterWeapon':'player:holsterWeapon'}})
        compiler=BehaviorCompiler([model],stem,native_catalog(target),importer=importer)
        roots,variables,equipment_report=lower(compiler,q,document,equipment['prepare']['program']['root'],
            equipment['cleanup']['program']['root'],equipment['variables'],adapt=basic_equipment_policy)
        if selection['domain']!='Basic':raise ValueError('Selected curriculum needs its own equipment policy')
        native=stack.enter_context(zipfile.ZipFile(target/'Data/Scripts.pak'))
        ntables=stack.enter_context(zipfile.ZipFile(target/'Data/Tables.pak'))
        files=worker_files(stem,roots,variables,read(ntables,'Libs/Tables/ai/EventSet.xml'))
        files.update(importer.files)
        files.update({p.relative_to(work/'items/converted').as_posix():p.read_bytes()
                      for p in (work/'items/converted').rglob('*') if p.is_file()})
        validate_ai({k:v for k,v in files.items() if k.startswith('AI/')},target)
        # Import the original follow-up branch, with its original conditions,
        # choices, actions, recordings and participant registration.
        parent=invitation['source']['parent_quest']
        quest_model(source,work/'parent',parent)
        dialogues(SimpleNamespace(source=source,target=target,mod=package,output=work/'speech',
            quest_ir=[work/'quest/quest-ir.json',work/'parent/quest-ir.json'],start_topic=[selection['topic']],
            namespace=stem+'_speech',kind='FaderDialog',container=ENTRY.removeprefix('Quests/'),
            container_name=LEVEL,activation=q+'.started',skill_upgrade=[],participant_asset=[]))
        apply_overlay(package,work/'speech/package',consume=True)
        with zipfile.ZipFile(package/travel) as z:
            graphs={n:read(z,n) for n in z.namelist() if n.startswith('Quests/') and n.endswith('.xml')}
            souls=[r for n in z.namelist() if n.startswith('Libs/Tables/rpg/soul__')
                   for r in E.fromstring(read(z,n)).iter('soul')]
            template_path='Libs/Tables/ai/smartEntity/SmartEntity__'+invitation['stem']+'.xml'
            template=E.fromstring(read(z,template_path))
        project=E.fromstring(graphs[PROJECT]);entry=E.fromstring(graphs[ENTRY]);scope=entry.find('Skald/Level');nodes=scope.find('Nodes')
        from campaign_linked_conditions import expose_state_changes
        source_quest_path='Quests/GlueTravel/gm_imported_scene/'+q+'.xml'
        graphs[source_quest_path]=expose_state_changes(graphs[source_quest_path])
        files[source_quest_path]=graphs[source_quest_path]
        departure=unique(nodes.findall("EnableBehavior[@Name='"+invitation['stem']+"_enable']"),'training departure')
        actor_alias=departure.find("Asset[@Name='NPC']").get('Alias')
        host_alias=departure.find("Asset[@Name='SmartEntity']").get('Alias')
        with zipfile.ZipFile(package/level) as z:
            mission=E.fromstring(read(z,'objects_mission0.xml'));scheduler=E.fromstring(read(z,'tables/ai/scheduler.xml'))
            links=read(z,'waitinglinks.xml')
        actor=unique((n for n in mission if n.get('EntityGuid')==invitation['placement']['actor_guid']),'training actor')
        host=unique((n for n in mission if n.get('Name')==host_alias),'training host')
        soul=unique((r for r in souls if r.get('soul_name')==actor.get('Name')),'registered training soul').get('soul_name')
        # Resolve native helper symbols through their authored library exports.
        symbols={};library=E.fromstring(read(native,selection['settings_library'])).find('Skald/*')
        for d in library.findall('Definitions/Definition'):
            path=posixpath.normpath(posixpath.join(posixpath.dirname(selection['settings_library']),d.get('File')))
            child=E.fromstring(read(native,path)).find('Skald/*')
            symbols[library.get('Name'),child.get('Name')]=path
        lesson_files,additions,lesson_report=assemble(native,selection['native_source'],selection['domain'],stem,
            {selection['native_tutor_role']:soul,selection['native_player_role']:None},
            optional_roles=selection['optional_roles'],effect_roles=selection['effect_roles'],
            settings_source=selection['settings'],settings_symbols=symbols,player_alias=selection['player_alias'])
        # Objectives and state types belong to this actual quest scope, not a
        # disconnected test harness. Its modules inherit the same scope.
        root=E.fromstring(lesson_files[lesson_report['root']]);quest_scope=root.find('Skald/Module');quest_scope.tag='Quest'
        for group in E.fromstring(additions):quest_scope.append(group)
        lesson_files[lesson_report['root']]=xml(root)
        graphs.update({directory+'/'+n:b for n,b in lesson_files.items()})
        E.SubElement(scope.find('Definitions'),'Definition',File='../'+stem+'/'+lesson_report['root'])
        lesson=E.SubElement(nodes,stem,Name=stem)
        E.SubElement(lesson,'Asset',Name='tutor',Alias=actor_alias)
        player=unique(project.findall(".//SoulAsset[@Name='"+selection['player_asset']+"']"),'imported player asset')
        E.SubElement(lesson,'Asset',Name='player',Alias=player.get('Name'))
        worker=E.SubElement(nodes,'EnableBehavior',Name=stem+'_worker',Signature=stem,EventSet=stem+'_events')
        constant(worker,'Behavior','lesson');constant(worker,'ForceKick','true')
        E.SubElement(worker,'Asset',Name='NPC',Alias=actor_alias);E.SubElement(worker,'Asset',Name='SmartEntity',Alias=host_alias)
        # Removing availability releases the authored leaning activity. The
        # equipment worker stays available through its cleanup acknowledgement.
        old_active=unique(departure.findall("Edge[@To='IsActive']"),'departure availability');departure.remove(old_active)
        source_quest=unique(nodes.findall(q),'source lesson quest')
        alive=E.SubElement(nodes,'Watch',Name=stem+'_quest_alive',TypeT='bool')
        edge(alive,q+'.started','WatchedState');constant(alive,'IsActive','true')
        stopped=E.SubElement(nodes,'If',Name=stem+'_quest_stopped')
        edge(stopped,alive.get('Name')+'.OnChanged','Exec');edge(stopped,q+'.started','Condition')
        schedule_report=schedule(nodes,lesson,source_quest,graphs['Quests/GlueTravel/gm_imported_scene/'+q+'.xml'],
            departure,plan['objectives'],[stopped.get('Name')+'.False'],[alive.get('Name')+'.OnChanged'],arrival_completion='source_objective')
        speech=conversations(nodes,graphs,stem+'_speech_')
        host_report=host_bind(nodes,lesson,worker,dialogue_nodes=speech)
        host_report['preparation_requires_scene_release'] = True
        from campaign_training_host import guard_authorization
        guard_authorization(nodes,stem,q,plan['objectives'],speech)
        host_report['authorization_requires_arrival'] = True
        activity,_=native_wait_activity(target);new_links=[]
        connect(mission,new_links,actor,host,'lesson',plan['priority'],plan['speed'],stem,scheduler,activity)
        from campaign_entity_links import guid_value
        for link in scheduler.findall('.//S_ActivityLink'):
            parameters=link.find('Parameters')
            if link.get('TargetGuid')==str(guid_value(host.get('EntityGuid'))) and parameters.get('BehaviorName')=='lesson':
                parameters.set('HaltOnInvalid','true')
        validate_compiled(mission,scheduler,new_links)
        behavior=E.SubElement(unique(template.findall('.//BehaviorTemplates'),'training template'),'SmartBehaviorTemplate',
            Name='lesson',InitialState='Disabled',MaxInstances='1')
        E.SubElement(behavior,'TreeLocation',FileName=stem+'.xml',TreeName='lesson')
        files[template_path]=xml(template)
        graphs[ENTRY]=xml(entry)
        validate_references(entry,graphs,stem)
        audio_paths=sorted((target/'Localization').glob('english-part*.pak'))+[target/'Localization/IPL_english.pak']
        audio_archives=[stack.enter_context(zipfile.ZipFile(p)) for p in audio_paths]
        recordings={};depots=[]
        for z in audio_archives:
            for name in z.namelist():
                if name.endswith('.ogg'):recordings.setdefault(Path(name).stem,[]).append((z,name))
                if name==DEPOT:depots.append(read(z,name))
        dubbing=unique(depots,'native English dubbing index')
        def lookup(stem):
            archive,path=unique(recordings.get(stem,[]),'native training recording '+stem)
            return path,read(archive,path)
        facial_pak='Data/gluemapper_dialogue_facials.pak'
        with zipfile.ZipFile(package/facial_pak) as z:facial_index=read(z,INDEX)
        graphs,media,facials,resource_report=bind_resources(graphs,lesson_report,directory,target,
            read(ntables,'Libs/Tables/skald/voice.xml'),read(ntables,'Libs/Tables/skald/skald_character.xml'),dubbing,lookup,
            existing_facial_index=facial_index)
        speech_paths=[n for n in graphs if '/'+stem+'_speech_' in n]
        if not speech_paths:raise ValueError('Training authorization dialogue was not imported')
        files.update({n:b for n,b in graphs.items() if n.startswith(directory+'/') or n==ENTRY or n in speech_paths})
        level_files={'objects_mission0.xml':xml(mission),'tables/ai/scheduler.xml':xml(scheduler),'waitinglinks.xml':append_links(links,new_links)}
        files['Mods/kingdomcomegluemapper/Data/Levels/kcd1_travel/tables/ai/scheduler.xml']=level_files['tables/ai/scheduler.xml']
        strings={n.removeprefix('localization/English/'):files.pop(n) for n in list(files) if n.startswith('localization/English/')}
        if strings:
            from localization_registry import repair_package
            rewrite(package,'Localization/English_xml.pak',strings)
            repair_package(package)
        rewrite(package,travel,files);rewrite(package,level,level_files)
        rewrite(package,'Localization/English.pak',media);rewrite(package,facial_pak,facials)
        # These two invitation nodes have intentionally changed ownership; all
        # other invitation resources still pass their original digest checks.
        for node in (source_quest,departure):invitation['graph_nodes'][node.get('Name')]=graph_digest(node)
        invitation['resources'][template_path]=hashlib.sha256(files[template_path]).hexdigest()
        invitation['resources'][source_quest_path]=hashlib.sha256(files[source_quest_path]).hexdigest()
        invitation['scope']='Source invitation and departure; native lesson linked by '+RECORD
        (package/INVITATION).write_text(json.dumps(invitation,indent=2),encoding='utf-8')
        resources={travel:{n:hashlib.sha256(b).hexdigest() for n,b in files.items()
            if n!=ENTRY and not n.startswith('Mods/')},'Localization/English.pak':{n:hashlib.sha256(b).hexdigest() for n,b in media.items()},
            facial_pak:{n:hashlib.sha256(b).hexdigest() for n,b in facials.items() if n!=INDEX}}
        graph_nodes={n.get('Name'):graph_digest(n) for n in nodes if n.get('Name','').startswith(stem) or n in (source_quest,departure)}
        names=[n.get('Name') for n in nodes]
        if len(names)!=len(set(names)):raise ValueError('Duplicate training host graph nodes')
        lesson_report.update(ready_for_game_test=True,installed=False,
            remaining=['in-game validation'],host_bindings_resolved=True,resources_bound=True)
        report=dict(selection=selection,source=plan,source_sha256=hashlib.sha256(original).hexdigest(),equipment=equipment_report,
            lesson=lesson_report,host=host_report,schedule=schedule_report,media=resource_report,resources=resources,
            graph_nodes=graph_nodes,runtime_verified=False)
        report['compiled_route']=dict(actor=actor.get('EntityGuid'),host=host.get('EntityGuid'),links=new_links)
        (package/RECORD).write_text(json.dumps(report,indent=2),encoding='utf-8')
        invitation_validate(package)
    return {n:digest(package/n) for n in (travel,level,'Localization/English.pak','Localization/English_xml.pak',facial_pak,INVITATION,RECORD)},validate(package)
