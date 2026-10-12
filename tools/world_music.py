"""Build a world-scoped KCD1 adaptive score using native KCD2 area inputs.

Read recordings and authored score from the user's installations. Never check
generated soundtrack files into source control. Preserve native scene bodies,
gate their eligibility in the imported world, and namespace every legacy state.
"""
import hashlib
from pathlib import Path
import re
import xml.etree.ElementTree as ET
import zipfile

from audio_mapping import sqcb_index
from campaign_entity_links import guid_value
from campaign_trigger_areas import TriggerArea, read_areas, write_areas
from upgrade_map import read, xml
from world_environment import inventory

SCRIPT = 'Music/kcd/main_layer.widsh'
VAR = re.compile(r'%([@#&]?)([A-Za-z_][\w.]*)')


def namespace(text):
    return VAR.sub(lambda m: '%' + m[1] + 'gm_' + m[2], text)


def scene_blocks(text):
    matches = list(re.finditer(r'^SCENE ([^\n]+)\n', text, re.M))
    if not matches: raise ValueError('No music scenes')
    return text[:matches[0].start()], [(m[1].strip(), text[m.start():matches[i+1].start()
        if i+1 < len(matches) else len(text)]) for i,m in enumerate(matches)]


def gate(body, condition):
    # Only the first E is scene eligibility. Later E lines select patterns.
    result, count = re.subn(r'^E (\[[^\n]*\])$', lambda m: 'E ['+m[1]+' '+condition+' &]',
                            body, count=1, flags=re.M)
    if count != 1: raise ValueError('Scene has no eligibility expression')
    # Scene continuation is independent from selection in SQC. Gate it too or
    # a looping track can survive a world switch despite no longer selectable.
    result, continuation = re.subn(r'^e (\[[^\n]*\])$',
        lambda m:'e ['+m[1]+' '+condition+' &]',result,count=1,flags=re.M)
    if not continuation:
        result=re.sub(r'^(E [^\n]+)$',lambda m:m[0]+'\ne '+condition,result,count=1,flags=re.M)
    return result


def binding_key(variable, value):
    return 'gm_' + variable.lower() + '_' + ('positive' if value == '++' else value.lower())


def source_bindings(source):
    triggers = {}
    with zipfile.ZipFile(Path(source)/'Data/GameData.pak') as z:
        for n in z.namelist():
            if not n.startswith('Libs/GameAudio/') or not n.endswith('.xml'): continue
            for t in ET.fromstring(read(z,n)).iter('ATLTrigger'):
                values = [v.get('fmod_name').split(':',1) for v in t.findall('SqcVariable')
                          if ':' in v.get('fmod_name','')]
                if values: triggers[t.get('atl_name').lower()] = values
    with zipfile.ZipFile(Path(source)/'Data/Tables.pak') as z:
        locations = {r.get('location_id'):r.get('location_name')
                     for r in ET.fromstring(read(z,'Libs/Tables/rpg/location.xml')).iter('row')}
    return triggers, locations


def world_polygon(entity):
    from region_travel import rotate
    shape = entity.find('Area')
    if shape is None: raise ValueError('Missing area: '+entity.get('Name',''))
    origin = tuple(map(float,entity.get('Pos').split(',')))
    scale = tuple(map(float,entity.get('Scale','1,1,1').split(',')))
    rotation = tuple(map(float,entity.get('Rotate','1,0,0,0').split(',')))
    points = []
    for p in shape.findall('Points/Point'):
        local = tuple(a*b for a,b in zip(map(float,p.get('Pos').split(',')),scale))
        points.append(tuple(a+b for a,b in zip(origin,rotate(rotation,local))))
    return float(shape.get('Height'))*scale[2], tuple(points)


def area_resources(files, source, guid):
    mission = ET.fromstring(files['objects_mission0.xml'])
    if any(e.get('Name','').startswith('gm_music_') for e in mission.iter('Entity')):
        raise ValueError('Music areas already installed; use the pre-music baseline')
    areas = read_areas(files['triggerareas.fubar'])
    by_guid = {a.guid:a for a in areas['areas']}
    triggers, locations = source_bindings(source)
    records, bindings = [], {}
    next_id = max(int(e.get('EntityId','0')) for e in mission.iter('Entity'))+1

    def add(identity, points, height, values, evidence):
        nonlocal next_id
        if next_id == 0x7777: next_id += 1
        if next_id > 65533: raise ValueError('Entity ID capacity exceeded')
        g = guid('music/'+identity); number = guid_value(g)
        if number in by_guid: raise ValueError('Music area GUID collision')
        keys=[]
        for variable,value in values:
            key=binding_key(variable,value);bindings[key]=(variable,value);keys.append(key)
        entity=ET.SubElement(mission,'Entity',Name='gm_music_'+identity,
            EntityClass='TriggerArea',EntityId=str(next_id),EntityGuid=g,
            Pos=','.join(str(v) for v in points[0]))
        ET.SubElement(entity,'Properties',Label=';'.join('music_'+k for k in keys),bSaved_by_game='0')
        next_id += 1
        area=TriggerArea(number,height,points);areas['areas'].append(area);by_guid[number]=area
        records.append(dict(name=identity,guid=g,bindings=keys,**evidence))

    add('world',((-100,-100,-1000),(4196,-100,-1000),(4196,4196,-1000),(-100,4196,-1000)),
        3000,[('world','on')],dict(source='imported 4096m world extent'))
    matched_locations=set()
    for entity in list(mission.iter('Entity')):
        props=entity.find('Properties')
        if props is None: continue
        location=props.get('guidLocationId')
        name=locations.get(location,'')
        values=triggers.get('entered_'+name.lower())
        if not values: continue
        area=by_guid.get(guid_value(entity.get('EntityGuid')))
        if area is None: raise ValueError('Registered music location lacks trigger polygon: '+name)
        add(entity.get('EntityGuid'),area.points,area.height,values,
            dict(source_location=name,source_location_id=location,source_entity=entity.get('Name')))
        matched_locations.add(name.lower())

    # Authored audio-area boundaries also drive river/cave/stealth music in KCD1.
    entities, active=inventory(source)
    for key in sorted(active):
        area=entities[key]
        if area.find('Area/Points') is None: continue
        values=[];refs=[]
        for ref in area.findall('Area/Entities/Entity'):
            linked=entities.get(ref.get('Id'))
            if linked is None or ref.get('Id') not in active: continue
            props=linked.find('Properties')
            if props is None or props.get('bEnabled','1') != '1': continue
            control=props.get('audioTriggerPlayTrigger','').lower()
            for value in triggers.get(control,[]):
                if value[0] in {'river','cave','landscape','stealth_quest_driven','quiet_countryside',
                                'tragic_music','location_highlight','quiet_monks'}:
                    if value not in values: values.append(value)
                    refs.append(control)
        if values:
            height,points=world_polygon(area)
            add('audio_'+key,points,height,values,dict(source_entity=area.get('Name'),source_controls=refs))
    missing=[name for name in locations.values() if 'entered_'+name.lower() in triggers
             and name.lower() not in matched_locations]
    return {'objects_mission0.xml':xml(mission),
            'triggerareas.fubar':write_areas(areas['areas'],areas['export_version'])}, bindings, dict(
        areas=records,unregistered_source_music_locations=missing,
        retired_location_trigger_names=[n for n in sorted(triggers) if n.startswith('entered_location_')
            and n.removeprefix('entered_') not in {v.lower() for v in locations.values()}])


def music_tables(target, bindings):
    files={}; roots={}
    with zipfile.ZipFile(Path(target)/'Data/Tables.pak') as z:
        for name in ('music_address_keyword','music_world_state_toggle','music_matrix'):
            path='Libs/Tables/music/'+name+'.xml'
            roots[name]=ET.fromstring(read(z,path))
    cells=next(r for r in roots['music_matrix'][0] if r.get('Address')=='*').find('Cells')
    atl=ET.Element('ATLConfig',atl_name='gluemapper_music');rtpcs=ET.SubElement(atl,'AudioRTPCs')
    used_ids=set()
    with zipfile.ZipFile(Path(target)/'Data/IPL_GameData.pak') as z:
        for n in z.namelist():
            if n.startswith('Libs/GameAudio/') and n.endswith('.xml'):
                used_ids.update(int(e.get('fmod_id')) for e in ET.fromstring(read(z,n)).iter() if e.get('fmod_id','').isdigit())
    next_id=max(used_ids)+1
    for key in sorted(bindings):
        toggle=key.upper()
        ET.SubElement(roots['music_address_keyword'][0],'AddressKeyword',Name=key,Weight='1',Toggle=toggle)
        ET.SubElement(roots['music_world_state_toggle'][0],'WorldStateToggle',Name=toggle,Overriding='false',Priority='999')
        ET.SubElement(cells,'MusicMatrixCell',WorldStateToggle=toggle,Playlist='#'+key,Status='Added')
        rtpc=ET.SubElement(rtpcs,'ATLRtpc',atl_name='sqc_ptag_'+key)
        ET.SubElement(rtpc,'SqcCtrl',fmod_id=str(next_id),fmod_name='#'+key);next_id+=1
    for name,root in roots.items(): files['Libs/Tables/music/'+name+'.xml']=xml(root)
    files['Libs/GameAudio/gluemapper_music.xml']=xml(atl)
    return files


def bridge(bindings):
    lines=['MACRO GM_INPUTS','\t[%@gm_active %#gm_world_on !]',
        '\tIF [%#menu %#menu_title ||]', '\t\t[%@gm_active #0 !]', '\tEND',
        '\t[%gm_menu $off !]','\t[%gm_location $off !]','\t[%gm_location_highlight $off !]',
        '\t[%gm_daytime %time_of_day !]','\t[%gm_player_health %player_health !]']
    for variable in ('river','cave','landscape','quiet_monks','quiet_countryside','tragic_music','stealth_quest_driven'):
        lines.append('\t[%gm_'+variable+' #0 !]')
    # Non-overriding address toggles survive weather/combat priority changes.
    for key,(variable,value) in sorted(bindings.items()):
        if variable=='world':continue
        literal='#1' if value=='++' else '$'+value
        lines.extend(['\tIF [%#'+key+']','\t\t[%gm_'+variable+' '+literal+' !]','\tEND'])
    for variable,condition in {
        'dialog':'[%#dialog]', 'silence':'[%#silence %#silence_asap %#silence_lazy ||]',
        'skiptime':'[%#skiptime]', 'combat':'[%@play_skirmish_armed %@play_skirmish_friendly ||]',
        'battle':'[%@play_battle_1 %@play_battle_2 %@play_battle_3 ||]',
        'chase':'[%#crime_high]', 'duel':'[%#skirmish_honor]',
    }.items():
        lines.extend(['\t[%gm_'+variable+' $off !]','\tIF '+condition,
                      '\t\t[%gm_'+variable+' $on !]','\tEND'])
    lines.extend(['\t[%gm_rain_intensity #0 !]','\tIF [%#rain %#storm ||]',
                  '\t\t[%gm_rain_intensity #1 !]','\tEND',
                  '\t[%gm_combat_armed $armed !]','\tIF [%skirmish_armed #0 =]',
                  '\t\t[%gm_combat_armed $unarmed !]','\tEND',
                  '\t[%gm_combat_level $even !]',
                  '\t[%gm_combat_phase $warmup !]',
                  '\tIF [%skirmish_phase #1 =]', '\t\t[%gm_combat_phase $texture !]', '\tEND',
                  '\tIF [%skirmish_phase #9 >=]', '\t\t[%gm_combat_phase $abandoned !]', '\tEND',
                  '\tIF [%skirmish_phase #10 =]', '\t\t[%gm_combat_phase $victory !]', '\tEND',
                  '\tIF [%skirmish_phase #12 >=]', '\t\t[%gm_combat_phase $loss !]', '\tEND',
                  '\t[%gm_battle_phase $texture_1 !]',
                  '\tIF [%@play_battle_2]', '\t\t[%gm_battle_phase $texture_2 !]', '\tEND',
                  '\t[%gm_risk $off !]', '\tIF [%#crime_low]', '\t\t[%gm_risk $fine !]', '\tEND',
                  '\tIF [%#trespass_low %#trespass_high ||]', '\t\t[%gm_stealth_quest_driven #1 !]', '\tEND',
                  '\t[%gm_minigame $off !]', '\tIF [%#dice]',
                  '\t\t[%gm_minigame $dice !]', '\t\tIF [%@gm_was_dice _]',
                  '\t\t\t[%gm_dice_phase $intro !] [%gm_dice_end $off !] [%gm_dice_player $player !]',
                  '\t\tEND', '\tELSE', '\t\tIF [%@gm_was_dice]',
                  '\t\t\t[%gm_dice_end $end !]', '\t\tEND', '\tEND',
                  '\t[%@gm_was_dice %#dice !]',
                  '\tIF [%@dice_side $player $opponent IN]', '\t\t[%gm_dice_player %@dice_side !]', '\tEND',
                  '\tIF [%@dice_phase %@gm_last_dice_phase ~]',
                  '\t\tIF [%@dice_phase $success $bust IN]', '\t\t\t[%gm_dice_phase %@dice_phase !]', '\t\tEND', '\tEND',
                  '\t[%@gm_last_dice_phase %@dice_phase !]',
                  '\tIF [%@dice_end %@gm_last_dice_end ~]',
                  '\t\tIF [%@dice_end $win $loss $end IN]', '\t\t\t[%gm_dice_end %@dice_end !]', '\t\tEND', '\tEND',
                  '\t[%@gm_last_dice_end %@dice_end !]',
                  'END'])
    return '\n'.join(lines)+'\n\n'


def score_resources(source,target,bindings):
    with zipfile.ZipFile(Path(target)/'Data/Music.pak') as z:
        native=read(z,SCRIPT).decode('utf-8-sig').replace('\r','')
    with zipfile.ZipFile(Path(source)/'Data/Music.pak') as z:
        old=read(z,SCRIPT).decode('utf-8-sig').replace('\r','')
        header,scenes=scene_blocks(old);native_header,native_scenes=scene_blocks(native)
        if not old.startswith('SQC MUSIC ENGINE WIDSH FILE VERSION 1.18') or not native.startswith('SQC MUSIC ENGINE WIDSH FILE VERSION 1.22'):
            raise ValueError('Unreviewed adaptive score version')
        setup=header.split('SETUP\n',1)[1].split('\nEND',1)[0]
        update=header.split('UPDATE\n',1)[1].rsplit('\nEND',1)[0]
        native_header=native_header.replace('SETUP\n','SETUP\n'+namespace(setup)+'\n',1)
        native_header=re.sub(r'^UPDATE\n',lambda _: bridge(bindings)+'MACRO GM_LEGACY_UPDATE\n'+namespace(update)+'\nEND\n\nUPDATE\n',native_header,count=1,flags=re.M)
        native_header=native_header.rstrip()
        if not native_header.endswith('END'):raise ValueError('Missing native update end')
        native_header=native_header[:-3]+'\t[?GM_INPUTS]\n\t[?GM_LEGACY_UPDATE]\nEND\n\n'
        result=[native_header]
        for name,body in native_scenes:
            # These engine service scenes contain silence/cinematic transitions.
            if name not in {'SYSTEM/AAA','SYSTEM/CIN'} and not name.startswith('SYSTEM/ZZZ'):
                body=gate(body,'[%@gm_active _]')
            result.append(body)
        files={};reports=[];missing=[]
        available={n.lower():n for n in z.namelist()}
        for name,body in scenes:
            if name.startswith('GUI/') or name in {'SYSTEM/AAA','SYSTEM/CIN'}: continue
            path='Music/kcd/'+name+'.sqcb'
            actual=available.get(path.lower())
            if actual is None:missing.append(name);continue
            data=read(z,actual);members=sqcb_index(data)
            dest='Music/kcd/GM_KCD1/'+name+'.sqcb';files[dest]=data
            converted=namespace(body).replace('SCENE '+name,'SCENE GM_KCD1/'+name,1)
            for macro in re.findall(r'^MACRO (\w+)',old,re.M):
                converted=converted.replace('MACRO '+macro+'\n','MACRO GM_KCD1_'+macro+'\n')
                converted=re.sub(r'\?'+re.escape(macro)+r'\b','?GM_KCD1_'+macro,converted)
            converted=re.sub(r'^N (.+)$',r'N GM_KCD1_\1',converted,flags=re.M)
            result.append(gate(converted,'[%@gm_active]'))
            reports.append(dict(scene=name,path=dest,sha256=hashlib.sha256(data).hexdigest(),segments=len(members)))
        files[SCRIPT]=''.join(result).encode('utf8')
    if missing: raise ValueError('Missing original scene audio: '+', '.join(missing))
    return files,dict(recordings=reports,missing_scene_containers=missing,
                     source_score_sha256=hashlib.sha256(old.encode()).hexdigest(),
                     native_score_sha256=hashlib.sha256(native.encode()).hexdigest(),
                     native_scenes=len(native_scenes),imported_scenes=len(reports))


def resources(files,source,target,guid):
    level,bindings,report=area_resources(files,source,guid)
    score,score_report=score_resources(source,target,bindings)
    score.update(music_tables(target,bindings))
    report.update(score_report,bindings=bindings,runtime_verified=False,
        limitations=['Initial world only; quest-driven KCD1 campaign music events are not converted.',
                    'Combat phase and dice outcome fidelity require gameplay validation.'])
    return level,score,report
