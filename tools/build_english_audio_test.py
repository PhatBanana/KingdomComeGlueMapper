"""Stage the original voiced horse-shop introduction and a complete audio audit.

Uses the currently installed Python mod as its baseline. No world regeneration,
global voice overrides, copied master banks, or implicit installation.
"""
import argparse
import copy
from collections import Counter
import hashlib
import json
from pathlib import Path
import xml.etree.ElementTree as ET
import zipfile

from audio_mapping import EnglishRecordings, dialogue_catalog, music_catalog
from dialogue_dubbing import DEPOT, bind_soul_voice, dubbing_index
from build_horse_trader_test import digest, rewrite
from getting_started_dialogue import PATH
from horse_trader_dialogue import DIALOG, ROLE
from region_travel_dialogue import merge_localization
from upgrade_map import read, xml

INTRO = ('156455', '156457', '156521')


def merge_audio_strings(native, additions):
    old=ET.fromstring(native)
    incoming=ET.fromstring(additions)
    known={row[0].text:row for row in old.findall('Row') if len(row)}
    for row in list(incoming):
        key=row[0].text
        if key in known:
            if [c.text for c in row]!=[c.text for c in known[key]]:
                raise ValueError('Changed original audio subtitle: '+key)
            incoming.remove(row)
    return merge_localization(native,xml(incoming))


def bind_introduction(blob, catalog):
    root=ET.fromstring(blob)
    host=root.find('Skald/FaderDialog')
    if host is None or host.get('Name') != DIALOG:
        raise ValueError('Expected current horse-sales dialogue')
    sequence=host.find(".//Sequence[@Name='getting_started_intro']")
    if sequence is None or sequence.find('Triggers/Port') is None:
        raise ValueError('Getting started quest introduction missing')
    if sequence.find('Triggers/Port').get('Name') != 'getting_started_talked':
        raise ValueError('Quest completion contract changed')
    mapped={r['sequence_line_id']:r for r in catalog}
    selected=[mapped[n] for n in INTRO]
    if any(r['status'] != 'mapped' for r in selected):
        raise ValueError('Original horse-shop English recordings incomplete')
    host.set('VoiceNamespace','true')
    body=host.find('Dialogue')
    body.attrib.pop('NonSpeakerRoles',None)
    for role,speaker in [('HENRY','Henry'),(ROLE,'Zora')]:
        voice=body.find("SelectedSouls/SelectedSoul[@Role='"+role+"']")
        if voice is None: raise ValueError('Missing dialogue participant: '+role)
        voice.set('Voice',next(r['target_voice'] for r in selected if r['speaker']==speaker))
    elements=sequence.find('Elements')
    elements.clear()
    strings=ET.Element('Table')
    for record in selected:
        response=ET.SubElement(elements,'Response',Role='HENRY' if record['speaker']=='Henry' else ROLE)
        ET.SubElement(response,'Text',StringName=record['string_name'],Text=record['text'])
        row=ET.SubElement(strings,'Row')
        for value in (record['string_name'],record['text'],record['text']):ET.SubElement(row,'Cell').text=value
    choices=host.find(".//Decision[@Name='horses']/Sequences")
    previous=choices.find("Sequence[@Name='original_horse_introduction']")
    if previous is not None:choices.remove(previous)
    repeat=copy.deepcopy(sequence)
    repeat.set('Name','original_horse_introduction')
    repeat.set('EntryCondition',"!Port('getting_started_active')")
    repeat.remove(repeat.find('Triggers'))
    prompt=repeat.find('UiPrompt')
    prompt.set('StringName',selected[0]['string_name'])
    prompt.set('Text',selected[0]['text'])
    choices.insert(1,repeat)
    unvoiced=[t.get('StringName') for t in root.findall('.//Response/Text')
              if t.get('StringName') not in {r['string_name'] for r in selected}]
    return xml(root),xml(strings),selected,unvoiced


def build(source,target,mod,output):
    if output.exists():raise FileExistsError('Choose a fresh staging directory')
    output.mkdir(parents=True)
    travel=mod/'Data/gluemappertravel.pak'
    locale=mod/'Localization/English_xml.pak'
    baseline={str(p.relative_to(mod)):digest(p) for p in (travel,locale)}
    package=output/'package'
    print('Mapping Henry and Zora recordings against native KCD2 voice identities',flush=True)
    with EnglishRecordings(source) as recordings:
        catalog,provenance=dialogue_catalog(source,target,recordings)
        with zipfile.ZipFile(travel) as archive:
            changed,strings,selected,unvoiced=bind_introduction(read(archive,PATH),catalog)
            resources={n:read(archive,n) for n in archive.namelist() if n.startswith('Libs/Tables/') and n.endswith('.xml')}
        modid=ET.parse(mod/'mod.manifest').findtext('info/modid')
        resources,voice_binding=bind_soul_voice(resources,target,modid,'neu_zdena',
            'abigailRice',ROLE,'char_169_uiName')
        resources[PATH]=changed
        media={}
        for row in selected:
            name='dialog/'+DIALOG+'/'+row['wave_file']+'.ogg'
            media[name]=recordings.extract(row['source_path'])
            row['installed_path']=name
            row['sha256']=hashlib.sha256(media[name]).hexdigest()
        rewrite(travel,package/'Data/gluemappertravel.pak',resources)
        with zipfile.ZipFile(locale) as archive:
            texts=merge_audio_strings(read(archive,'text_ui_dialog.xml'),strings)
        rewrite(locale,package/'Localization/English_xml.pak',{'text_ui_dialog.xml':texts})
        voicepak=mod/'Localization/English.pak'
        existing_index=None
        if voicepak.exists():
            with zipfile.ZipFile(voicepak) as archive:
                if DEPOT in archive.namelist():existing_index=read(archive,DEPOT)
        index,index_report=dubbing_index(target,media,existing_index)
        media[DEPOT]=index
        for name,blob in resources.items():
            if name.startswith('Libs/Tables/'):
                path=output/'validation'/name
                path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(blob)
        (output/'validation/dubbing.xml').write_bytes(index)
        if voicepak.exists():
            baseline['Localization/English.pak']=digest(voicepak)
            rewrite(voicepak,package/'Localization/English.pak',media)
        else:
            with zipfile.ZipFile(package/'Localization/English.pak','x',zipfile.ZIP_STORED) as archive:
                for n,b in media.items():archive.writestr(n,b)
    print('Validating KCD1 music containers and adaptive scene dependencies',flush=True)
    music=music_catalog(source,target)
    (output/'dialogue-map.json').write_text(json.dumps(catalog,indent=2),encoding='utf-8')
    (output/'music-map.json').write_text(json.dumps(music,indent=2),encoding='utf-8')
    report=dict(schema=1,baseline_root=str(mod),baseline=baseline,provenance=provenance,
        dialogue_counts=dict(Counter(r['status'] for r in catalog)),
        voiced_introduction=selected,unvoiced_custom_lines=unvoiced,
        runtime_voice_binding=voice_binding,dubbing_index=index_report,
        music_tracks=len(music['tracks']),music_state_conversion_pending=True,
        runtime_verified=False,
        files={str(p.relative_to(package)):digest(p) for p in package.rglob('*.pak')})
    (output/'report.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    return report


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ('source','target','mod','output'):parser.add_argument('--'+name,type=Path,required=True)
    args=parser.parse_args()
    report=build(**vars(args))
    print(json.dumps({k:report[k] for k in ('dialogue_counts','music_tracks','runtime_verified')},indent=2))
