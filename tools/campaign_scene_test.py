"""Stage a source dialogue scene against an installed development world.

Explicit test builder: source-linked placements and choices, native lifecycle,
merged world/resources/localization. Never installs implicitly. Missing gesture
clips require --allow-missing-gestures and remain in the receipt.
"""
import argparse
import copy
import json
from pathlib import Path
import xml.etree.ElementTree as ET
import zipfile

from upgrade_map import read, xml
from campaign_quest_graph import emit_project
from campaign_quest_text import load as load_quest_text, localization_table
from campaign_quest_scope import bind_level
from campaign_dialogue_runtime import attach_dialogue
from campaign_scene import attach_scene, stat_effects, bind_stat_effects, bind_scene_cameras, bind_scene_positions
from character_person import resolve_person, register_person, actor_resources
from character_person_world import register_person_world
from campaign_package import campaign_spawn_objects
from dialogue_dubbing import bind_soul_voice, dubbing_index, DEPOT
from build_english_audio_test import merge_audio_strings
from build_horse_trader_test import rewrite, digest


def source_scene_positions(source, level, quest, alias):
    with zipfile.ZipFile(source / 'Data/Levels' / level / 'level.pak') as archive:
        entities = list(ET.fromstring(read(archive, 'objects_mission0.xml')).iter('Entity'))
        for n in archive.namelist():
            if n.lower().startswith('layers/') and n.lower().endswith('.xml'):
                entities.extend(ET.fromstring(read(archive, n)).iter('Entity'))
    controller = [e for e in entities if e.get('Name') == quest]
    # Mission and source layer can expose the same controller.
    controllers = {ET.tostring(e) for e in controller}
    if len(controllers) != 1: raise ValueError('Ambiguous source quest controller')
    result = {}
    import re
    for link in controller[0].findall('EntityLinks/Link'):
        m = re.fullmatch(r"CutsceneSpot\[npc\('([^']+)'\),alias\('([^']+)'\)(?:,idle\(true\))?\]", link.get('Name', ''))
        if m and m[2] == alias:
            found = {ET.tostring(e): e for e in entities if e.get('EntityId') == link.get('TargetId')}
            if len(found) != 1: raise ValueError('Ambiguous source scene spot')
            result[m[1]] = dict(next(iter(found.values())).attrib)
    if not result: raise ValueError('No source cutscene spots')
    return result


def map_gestures(blob, source, target, genders, allow_missing=False):
    databases = {}
    for gender in set(genders.values()):
        old = 'kcd_male_database.adb' if gender == 'male' else 'wh_female_database.adb'
        with zipfile.ZipFile(source / 'Data/Animations-part1.pak') as z:
            original = ET.fromstring(read(z, 'Animations/Mannequin/ADB/' + old))
        with zipfile.ZipFile(target / 'Data/Animations.pak') as z:
            native = ET.fromstring(read(z, 'Animations/Mannequin/ADB/' + gender + '_adlg.adb'))
        databases[gender] = original, native
    root, report = ET.fromstring(blob), []
    for parent in root.iter('Commands'):
        for command in list(parent):
            if command.tag != 'AnimationCommand': continue
            original, native = databases[genders[command.get('Role')]]
            fragment = original.find('./FragmentList/' + command.get('FragmentId'))
            choices = [f for f in fragment if not f.get('Tags')] if fragment is not None else []
            variant = int(command.get('Variant')) - 1
            if variant < 0 or variant >= len(choices): raise ValueError('Missing source gesture variant')
            authored = choices[variant]
            signature = [dict(a.attrib) for a in authored.iter('Animation')]
            matches = []
            for group in native.find('FragmentList'):
                untagged = [f for f in group if not f.get('Tags')]
                for index, f in enumerate(untagged):
                    if [dict(a.attrib) for a in f.iter('Animation')] == signature:
                        matches.append((group.tag, index + 1, f))
            exact = [m for m in matches if [dict(b.attrib) for b in m[2].iter('Blend')] ==
                     [dict(b.attrib) for b in authored.iter('Blend')]]
            if exact: matches = exact
            record = dict(source=dict(command.attrib), clips=signature)
            if len(matches) != 1:
                if not allow_missing: raise ValueError('Unresolved original gesture: ' + str(record))
                record['status'] = 'pending_missing_or_ambiguous'; parent.remove(command)
            else:
                group, index, selected = matches[0]
                command.set('FragmentId', group); command.set('Variant', str(index)); command.set('Guid', selected.get('GUID'))
                record.update(status='matched_native_clip', target=dict(command.attrib))
            report.append(record)
    return xml(root), report


def build(a):
    if a.output.exists(): raise FileExistsError('Choose a fresh output directory')
    from campaign_start_policy import validate_native
    with zipfile.ZipFile(a.target/'Data/IPL_GameData.pak') as archive:
        validate_native(read(archive, 'Libs/concept/definitions.xml'))
    model = json.loads((a.dialogue / 'dialogue-ir.json').read_text())
    quest_model = json.loads(a.quest_model.read_text())
    conversion = json.loads((a.dialogue / 'conversion.json').read_text())
    binding = json.loads((a.runtime / 'runtime-binding.json').read_text())
    character = json.loads((a.appearance / 'appearance-result.json').read_text())
    person = resolve_person(a.source, a.person, a.source_level)
    spots = source_scene_positions(a.source, a.source_level, quest_model['quest'], a.scene_alias)
    if a.actor_alias not in spots or 'player' not in spots: raise ValueError('Missing source participant position')
    project_name = 'gm_imported_scene'
    quest_text, quest_text_report = load_quest_text(a.source, [quest_model], 'English')
    graphs, quest_report = emit_project([quest_model], project_name, localization=quest_text)
    native_dialogue = next((a.runtime / 'Data/Quests').rglob(a.dialogue_name + '.xml'))
    dialog, animation_report = map_gestures(native_dialogue.read_bytes(), a.source, a.target,
                                          {'HENRY': 'male', a.role: character['gender']}, a.allow_missing_gestures)
    dialog_root = ET.fromstring(dialog)
    for selected in dialog_root.findall('.//SelectedSoul'):
        if selected.get('Role') == a.role: selected.set('Soul', person['name'])
    dialog = xml(dialog_root)
    graphs = attach_dialogue(graphs, project_name, dialog, conversion, quest_model['quest'] + '.started')
    effects = stat_effects(a.behavior.read_bytes(), quest_model['tables']['quest_objective']['rows'])
    qpath = project_name + '/' + quest_model['quest'] + '.xml'
    graphs[qpath] = bind_stat_effects(graphs[qpath], effects, a.player_asset)
    travel = a.mod / 'Data/gluemappertravel.pak'
    level = a.mod / 'Data/Levels' / a.level / 'level.pak'
    with zipfile.ZipFile(travel) as z:
        resources = {n: read(z, n) for n in z.namelist() if n.startswith('Libs/')}
        existing_graph = read(z, a.project_path)
    project_root = ET.fromstring(existing_graph)
    ET.SubElement(project_root.find('./Skald/Project/Assets'), 'SoulAsset', Name=a.namespace + '_actor',
                  SharedSoulGuids=person['soul']['soul_id'])
    existing_graph = xml(project_root)
    resources = actor_resources(a.target, person, character, a.namespace, role_name=a.role,
        native_soul_table='Libs/Tables/rpg/soul__ttac.xml', native_soul_name='ttac_procek',
        native_role_name='PREVOZNIK_TROSECKO', resources=resources)
    modid = ET.parse(a.mod / 'mod.manifest').findtext('info/modid')
    resources, voice_receipt = bind_soul_voice(resources, a.target, modid, person['name'],
        binding['roles'][a.role]['voice_technical_name'], a.role, person['instance'].findtext('StaticData/NameStringId'))
    for p in a.appearance.rglob('*'):
        if p.is_file() and p.relative_to(a.appearance).parts[0] in ('objects', 'Libs'):
            resources[p.relative_to(a.appearance).as_posix()] = p.read_bytes()
    completion = [k for k,v in conversion['actions'].items() if v['input'] == a.completion_input]
    if len(completion) != 1: raise ValueError('Expected one completion action')
    resources[a.project_path] = attach_scene(existing_graph, graphs[project_name + '.xml'],
        a.dialogue_name, quest_model['quest'], a.level + '.arrived', completion[0], a.namespace + '_actor')
    for p,b in graphs.items():
        if p != project_name + '.xml': resources[a.project_path.rsplit('/',1)[0] + '/' + p] = b
    with zipfile.ZipFile(level) as z:
        files = {n: read(z,n) for n in ('objects_mission0.xml','whdata_0','tables/ai/scheduler.xml','triggerareas.fubar','waitinglinks.xml')}
    mission, wh = ET.fromstring(files['objects_mission0.xml']), ET.fromstring(files['whdata_0'])
    next_id = max(int(e.get('EntityId','0')) for e in mission)+1
    def add(name, cls, pos, guid, rotation):
        nonlocal next_id
        if any(e.get('Name') == name or e.get('EntityGuid') == guid for e in mission): raise ValueError('Actor already present')
        e=ET.SubElement(mission,'Entity',Name=name,EntityClass=cls,Pos=pos,EntityGuid=guid,EntityId=str(next_id),CastShadowMinSpec='1')
        if rotation:e.set('Rotate',rotation)
        next_id+=1
        return e
    register_person(add, wh, person, spots[a.actor_alias])
    for camera in ET.parse(a.dialogue / 'camera-entities.xml').getroot():
        if any(e.get('Name') == camera.get('Name') for e in mission):raise ValueError('Camera already present')
        camera.set('EntityId',str(next_id));next_id+=1;mission.append(copy.deepcopy(camera))
    player = spots['player']
    files['objects_mission0.xml'] = campaign_spawn_objects(xml(mission),dict(position=player['Pos'],rotation=player['Rotate']))
    files['whdata_0'] = xml(wh)
    files, world_receipt = register_person_world(files,[person],a.source,a.target)
    (resources[a.project_path], files['objects_mission0.xml'], files['waitinglinks.xml'], camera_report) = bind_scene_cameras(
        resources[a.project_path], files['objects_mission0.xml'], files['waitinglinks.xml'], dialog)
    (resources[a.project_path], files['objects_mission0.xml'], files['waitinglinks.xml'], placement_report) = bind_scene_positions(
        resources[a.project_path], files['objects_mission0.xml'], files['waitinglinks.xml'], a.dialogue_name,
        {a.player_asset: spots['player'], a.namespace + '_actor': spots[a.actor_alias]})
    for path,blob in files.items():
        if path.startswith('tables/'):
            resources[f'Mods/{modid}/Data/Levels/{a.level}/{path}']=blob
    package=a.output/'package';package.mkdir(parents=True)
    entry_path = a.project_path.rsplit('/', 1)[0] + '/entry/' + a.level + '.xml'
    with zipfile.ZipFile(travel) as archive:
        entry_blob = resources.get(entry_path, read(archive, entry_path))
    resources[a.project_path], resources[entry_path], scope_report = bind_level(
        resources[a.project_path], entry_blob, graphs[project_name + '/' + quest_model['quest'] + '.xml'],
        quest_model['quest'], a.level)
    rewrite(travel,package/'Data/gluemappertravel.pak',resources)
    rewrite(level,package/'Data/Levels'/a.level/'level.pak',files)
    audio = {p.relative_to(a.runtime/'Localization/English').as_posix():p.read_bytes()
             for p in (a.runtime/'Localization/English').rglob('*.ogg')}
    audio_pak=a.mod/'Localization/English.pak'
    existing = None
    if audio_pak.exists():
        with zipfile.ZipFile(audio_pak) as z:existing=read(z,DEPOT)
    audio[DEPOT],_ = dubbing_index(a.target,audio,existing)
    if audio_pak.exists():
        rewrite(audio_pak,package/'Localization/English.pak',audio)
    else:
        destination = package/'Localization/English.pak'
        destination.parent.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(destination, 'x', zipfile.ZIP_STORED) as z:
            for name, blob in sorted(audio.items()): z.writestr(name, blob)
    locale=a.mod/'Localization/English_xml.pak'
    with zipfile.ZipFile(locale) as z:
        strings={'text_ui_dialog.xml':merge_audio_strings(read(z,'text_ui_dialog.xml'),
            (a.runtime/'Localization/English_xml/text_ui_dialog.xml').read_bytes())}
        strings['text_ui_quest.xml'] = merge_audio_strings(read(z, 'text_ui_quest.xml'),
            localization_table([s for q in quest_report['quests'] for s in q['journal_strings']]))
        with zipfile.ZipFile(a.source/'Localization/English_xml.pak') as original:
            key=person['instance'].findtext('StaticData/NameStringId');t=ET.Element('Table')
            t.append(next(r for r in ET.fromstring(read(original,'text_ui_soul.xml')) if r.findtext('Cell')==key))
            strings['text_ui_soul.xml']=merge_audio_strings(read(z,'text_ui_soul.xml'),xml(t))
        item_strings=a.appearance/'Localization/English/text_ui_items.xml'
        if item_strings.exists():strings['text_ui_items.xml']=merge_audio_strings(read(z,'text_ui_items.xml'),item_strings.read_bytes())
    rewrite(locale,package/'Localization/English_xml.pak',strings)
    receipt=dict(runtime_verified=False,source_alias=model['alias'],placements=spots,actor=voice_receipt,
                 rewards=effects,animations=animation_report,world=world_receipt,cameras=camera_report,
                 scene_placement=placement_report,
                 quest_conversion=quest_report,quest_localization=quest_text_report,quest_scope=scope_report,
                 baseline={str(p.relative_to(a.mod)):digest(p) for p in (travel,level,audio_pak,locale) if p.exists()},
                 pending=['Full original campaign continuation','Original facial tracks','In-game two-round choices and gameplay handoff'])
    (a.output/'scene-test.json').write_text(json.dumps(receipt,indent=2))
    print(json.dumps(dict(package=str(package),rewards=len(effects),gestures=len(animation_report),
                         pending_gestures=sum(r['status']!='matched_native_clip' for r in animation_report))))


def main():
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('source','target','mod','dialogue','runtime','appearance','quest-model','behavior','output'):
        p.add_argument('--'+name,type=Path,required=True)
    for name in ('person','role','namespace','dialogue-name','actor-alias','scene-alias','completion-input'):
        p.add_argument('--'+name,required=True)
    p.add_argument('--source-level',default='rataje');p.add_argument('--level',default='kcd1_travel')
    p.add_argument('--project-path',default='Quests/GlueTravel/GlueTravel_kcd1.xml')
    p.add_argument('--player-asset',default='travel_player')
    p.add_argument('--allow-missing-gestures',action='store_true')
    build(p.parse_args())


if __name__=='__main__':main()
