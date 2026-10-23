"""Upgrade native market workers with source actor-bound advertising speech."""
import hashlib,json,copy
from pathlib import Path
import xml.etree.ElementTree as E
import zipfile
from upgrade_map import read
from campaign_quest_graph import xml

RECORD='work-speech.json'

def upgrade(package,source,target):
 from campaign_dependency_adapters import SourceTables
 from campaign_sources import RetailSourceReader
 from campaign_dialogue import load_many
 from campaign_work_metaroles import resolve,register,partition,dispatch_proof,select_recordings,stage_dialogue,adapt_hearing,bind_entry_speaker
 from campaign_market_speech import clone_market
 from character_market_jobs import contract
 from campaign_dialogue_runtime import voice_namespace
 from dialogue_dubbing import DEPOT,dubbing_index,bind_soul_voice
 from build_actor_dialogues_test import actor_ui_name
 from build_english_audio_test import merge_audio_strings
 from setup_package_upgrade import rewrite
 from setup_campaign import digest
 from setup_gameplay import ENTRY
 package=Path(package); travel='Data/gluemappertravel.pak'; level='Data/Levels/kcd1_travel/level.pak'
 if (package/RECORD).exists():
  report=json.loads((package/RECORD).read_text())
  for pak,entries in report['resources'].items():
   with zipfile.ZipFile(package/pak) as z:
    for name,sha in entries.items():
     if hashlib.sha256(read(z,name)).hexdigest()!=sha:raise ValueError('Changed work speech resource: '+name)
  validate_owned(package,report)
  return {},report
 if source is None or target is None:raise ValueError('Source games required for work speech upgrade')
 source,target=map(Path,(source,target))
 with zipfile.ZipFile(package/travel) as z:resources={n:read(z,n) for n in z.namelist() if n.startswith(('Libs/','Quests/','AI/'))}
 with zipfile.ZipFile(package/level) as z:
  mission=E.fromstring(read(z,'objects_mission0.xml')); scheduler=E.fromstring(read(z,'tables/ai/scheduler.xml'))
 soul_names={r.get('soul_id'):r.get('soul_name') for n,b in resources.items() if n.startswith('Libs/Tables/rpg/soul__') for r in E.fromstring(b).iter('soul')}
 template=contract(target).get('DatabaseId')
 jobs={s:[e for e in mission if e.get('Name','').startswith('gm_schedule_'+name+'_') and e.find('Properties') is not None and e.find('Properties').get('guidSmartObjectType')==template] for s,name in soul_names.items()}
 soul_names={s:n for s,n in soul_names.items() if jobs[s]}
 from campaign_entity_links import guid_value
 for soul,name in soul_names.items():
  actors=[e for e in mission if e.get('Name')==name]
  if len(actors)!=1:raise ValueError('Missing source market actor')
  hub=scheduler.find(".//C_SmartHub[@EntityGuid='"+str(guid_value(actors[0].get('EntityGuid')))+"']")
  for job in jobs[soul]:
   links=[] if hub is None else hub.findall("Links/S_ActivityLink[@TargetGuid='"+str(guid_value(job.get('EntityGuid')))+"']/Parameters[@BehaviorName='seller_market']")
   if not links:raise ValueError('Market worker lacks actor-owned scheduler link')
 with RetailSourceReader(source) as reader:
  db=SourceTables(source,reader)
  tables={n:db.get(path+'/'+n)['rows'] for path,n in [('rpg','role'),('rpg','metarole'),('rpg','soul2role'),('text','topictorole'),('text','v_branch')]}
  chars=db.get('rpg/v_soul_character_data')['rows']; source_voices=db.get('text/v_voice_abbreviation')['rows']; hearings=db.get('text/dialogue_hearing')['rows']
  source_tree=reader(source,{'tree':('Scripts.pak','Libs/AI/final/sa_shop2.xml')})['tree']['data']
 from campaign_intro_activity import normalized
 tree=normalized(source_tree).find("BehaviorTree[@name='merchant']/Root")
 requests=[n for n in tree.iter('SendMessageToNPC') if n.get('type')=='dialog:monologRequest' and "metarole('MERCHANT_VYVOLAVANI')" in n.get('values','')]
 if len(requests)!=1:raise ValueError('Source merchant call dispatch changed')
 request=dict(requests[0].attrib)
 bindings,branches=resolve(tables,soul_names,['MERCHANT_VYVOLAVANI'])
 models=load_many(source,[(None,b['start_topic']) for b in branches]) if branches else []
 ready,pending=partition({m['start_topic']:m for m in models})
 with zipfile.ZipFile(target/'Data/Tables.pak') as z:
  native_roles=[r.attrib for r in E.fromstring(read(z,'Libs/Tables/rpg/role.xml')).iter('role')]; native_voices=read(z,'Libs/Tables/skald/voice.xml')
 with zipfile.ZipFile(target/'Data/Scripts.pak') as z:
  native=E.fromstring(read(z,'Quests/Final/Barbora/fist_fights_common_module/fandici_barky.xml'))
  hearing=E.fromstring(read(z,'Quests/Final/Barbora/kutnohorsko/brushes_with_death_kutnohorsko/truhlari/chrudos_state/chrudos_uveznen/chrudos_utika.xml'))
 graphs={n.removeprefix('Quests/'):b for n,b in resources.items() if n.startswith('Quests/')}
 scope=voice_namespace(graphs,ENTRY.removeprefix('Quests/')); entry=E.fromstring(resources[ENTRY]); host=entry.find('Skald/Level')
 if host.find("Nodes/State[@Name='entry_ready'][@TypeT='bool']/Constant[@Name='DefaultValue'][@Value='true']") is None:raise ValueError('Missing level availability state')
 recordings={}; emitted=[]; actor_reports=[]; strings=E.Element('Table'); changed={}
 for soul,roles in bindings.items():
  owned={r['role_id'] for r in roles}
  selected=[m for m in ready.values() if {p['role_id'] for p in m['participants'] if p['topic_id']==m['start_topic']}<=owned]
  if not selected:continue
  namespace='gm_work_'+soul.replace('-',''); bnd={soul:roles}
  resources,mapping,metas=register(resources,bnd,soul_names,native_roles,namespace)
  clone,worker=clone_market(target,metas['MERCHANT_VYVOLAVANI'],namespace);resources.update(clone)
  for job in jobs[soul]:job.find('Properties').set('guidSmartObjectType',worker['template'])
  for original in selected:
   model=select_recordings(original,soul,chars,tables['soul2role'])
   proof=dispatch_proof(model,bnd,'MERCHANT_VYVOLAVANI',request,native)
   name=namespace+'_'+model['start_topic']
   resources,blob,audio,report=stage_dialogue(model,proof,source,native_voices,source_voices,resources,mapping,name,parent_namespace=scope)
   blob,hearing_report=adapt_hearing(blob,model,hearings,hearing)
   blob=bind_entry_speaker(blob,native)
   commands=[c for t in model['topics'].values() for seq in t['sequences'] for line in seq['lines'] for c in line['commands']]
   if any(c['dialogue_command_type'] not in ('3','8') for c in commands):raise ValueError('Unsupported work presentation command')
   if report['conversion'].get('conditions') or report['conversion'].get('actions') or report['conversion'].get('action_programs'):raise ValueError('Work speech requires additional source gameplay bindings')
   path='Quests/GlueTravel/entry/'+namespace+'/'+name+'.xml';resources[path]=blob
   E.SubElement(host.find('Definitions'),'Definition',File=namespace+'/'+name+'.xml')
   instance=E.SubElement(host.find('Nodes'),name,Name=name)
   E.SubElement(instance,'Edge',From='entry_ready.State',To=report['conversion']['active_port'])
   recordings.update(audio)
   for key,value in model['strings'].items():
    row=E.SubElement(strings,'Row')
    for text in (key,value,value):E.SubElement(row,'Cell').text=text
   report.update(name=name,definition=path,active_port=report['conversion']['active_port'],requests_enabled=True,pending=[],hearing=hearing_report,presentation_adaptation='Native market activity keeps pose; source ADLG gestures omitted',worker=worker)
   emitted.append(report)
   voice=next(iter(report['binding']['roles'].values()))
   soulrows=[r for n,b in resources.items() if n.startswith('Libs/Tables/rpg/soul__') for r in E.fromstring(b).iter('soul') if r.get('soul_id')==soul]
   character=soulrows[0].get('skald_character_name')
   current=[r for n,b in resources.items() if n.startswith('Libs/Tables/skald/skald_character__') for r in E.fromstring(b).iter('skald_character') if r.get('skald_character_name')==character]
   master=current[0].get('master_role_name') if current else next(iter(mapping.values()))
   resources,voice_receipt=bind_soul_voice(resources,target,'kingdomcomegluemapper',soul_names[soul],voice['voice_technical_name'],master,actor_ui_name(resources,soul_names[soul]))
   actor_reports.append(dict(soul=soul,worker=worker,voice=voice_receipt,jobs=[j.get('Name') for j in jobs[soul]]))
 resources[ENTRY]=xml(entry)
 if not emitted:return {},dict(status='no_supported_source_workers',pending=pending,runtime_verified=False)
 with zipfile.ZipFile(package/'Localization/English.pak') as z:depot=read(z,DEPOT)
 depot,dubbing=dubbing_index(target,recordings,depot);recordings[DEPOT]=depot
 with zipfile.ZipFile(package/'Localization/English_xml.pak') as z:localized=merge_audio_strings(read(z,'text_ui_dialog.xml'),xml(strings))
 from dialogue_facials import FacialImporter,INDEX
 facial_pak='Data/gluemapper_dialogue_facials.pak'
 with zipfile.ZipFile(package/facial_pak) as z:facial_index=read(z,INDEX)
 facial=FacialImporter(source,target,facial_index)
 try:
  supported={n:b for n,b in recordings.items() if n!=DEPOT and len(facial.source_headers.get(Path(n).stem.lower(),[]))==1}
  missing_facials=[n for n in recordings if n!=DEPOT and not facial.source_headers.get(Path(n).stem.lower())]
  if len(supported)+len(missing_facials)!=len(recordings)-1:raise ValueError('Ambiguous source work lip-sync')
  facial.add(supported);facials=facial.resources()
 finally:facial.close()
 with zipfile.ZipFile(package/travel) as z:changes={n:b for n,b in resources.items() if n not in z.namelist() or read(z,n)!=b}
 outputs={travel:changes,level:{'objects_mission0.xml':xml(mission)},'Localization/English.pak':recordings,'Localization/English_xml.pak':{'text_ui_dialog.xml':localized},facial_pak:facials}
 owned={p:{n:hashlib.sha256(b).hexdigest() for n,b in files.items() if ('gm_work_' in n or (p=='Localization/English.pak' and n!=DEPOT))} for p,files in outputs.items()}
 report=dict(version=1,conversations=emitted,actors=actor_reports,pending=pending,runtime_verified=False,
  missing_source_lipsync=missing_facials,resources={p:entries for p,entries in owned.items() if entries})
 for pak,files in outputs.items():rewrite(package,pak,files)
 tmp=package/(RECORD+'.pending');tmp.write_text(json.dumps(report,indent=2),encoding='utf-8');tmp.replace(package/RECORD)
 return {p:digest(package/p) for p in (*outputs,RECORD)},report



def validate_owned(package,report):
 """Check only this upgrade's definitions, dispatch bindings and worker fields."""
 from setup_gameplay import ENTRY
 from campaign_entity_links import guid_value
 with zipfile.ZipFile(Path(package)/'Data/gluemappertravel.pak') as z:
  entry=E.fromstring(read(z,ENTRY)).find('Skald/Level')
  storm=E.fromstring(read(z,'Libs/Storm/storm.xml'))
  for conversation in report['conversations']:
   name=conversation['name'];path=conversation['definition']
   relative=path.removeprefix('Quests/GlueTravel/entry/')
   if len(entry.findall("Definitions/Definition[@File='"+relative+"']"))!=1:raise ValueError('Missing work dialogue definition')
   nodes=entry.findall('Nodes/'+name+"[@Name='"+name+"']")
   if len(nodes)!=1 or nodes[0].find("Edge[@From='entry_ready.State'][@To='"+conversation['active_port']+"']") is None:raise ValueError('Missing work dialogue activation')
  for actor in report['actors']:
   namespace='gm_work_'+actor['soul'].replace('-','')
   if storm.find("tasks/task[@name='roles']/source[@path='roles/"+namespace+".xml']") is None:raise ValueError('Missing work role registration')
 with zipfile.ZipFile(Path(package)/'Data/Levels/kcd1_travel/level.pak') as z:
  mission=E.fromstring(read(z,'objects_mission0.xml'));scheduler=E.fromstring(read(z,'tables/ai/scheduler.xml'))
  for actor in report['actors']:
   for name in actor['jobs']:
    matches=[e for e in mission if e.get('Name')==name]
    if len(matches)!=1 or matches[0].find('Properties').get('guidSmartObjectType')!=actor['worker']['template']:raise ValueError('Changed work speech seller binding')
    links=scheduler.findall(".//S_ActivityLink[@TargetGuid='"+str(guid_value(matches[0].get('EntityGuid')))+"']/Parameters[@BehaviorName='seller_market']")
    if not links:raise ValueError('Missing work speech scheduler dispatch')
