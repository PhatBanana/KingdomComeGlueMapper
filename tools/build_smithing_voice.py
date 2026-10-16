"""Register native smithing monologues in the standalone KCD1 project."""
import argparse
import json
import posixpath
from pathlib import Path
import xml.etree.ElementTree as ET
import zipfile
from build_horse_trader_test import digest, rewrite
from upgrade_map import read, xml

HOST='Quests/GlueTravel/GlueTravel_kcd1.xml'
NATIVE='Quests/Final/Barbora/open_world/minihry/kovareni.xml'
PREFIX='Quests/GlueTravel/smithing_voice/'


def wrapper(name, child, file):
    root=ET.Element('Database',Name='brambora')
    host=ET.SubElement(ET.SubElement(root,'Skald'),'Gameplay',Name=name,VoiceNamespace='true')
    ET.SubElement(ET.SubElement(host,'Definitions'),'Definition',File=file)
    ET.SubElement(ET.SubElement(host,'Nodes'),child,Name=child)
    return xml(root)


def patch(payload,scripts,recording_names):
    root=ET.fromstring(payload);host=root.find('Skald/Project')
    if any(e.get('Name')=='open_world' for e in host.find('Nodes')):
        raise ValueError('Existing open_world registration requires review')
    ET.SubElement(host.find('Definitions'),'Definition',File='smithing_voice/open_world.xml')
    ET.SubElement(host.find('Nodes'),'open_world',Name='open_world')
    resources={HOST:xml(root),PREFIX+'open_world.xml':wrapper('open_world','minihry','minihry.xml'),
               PREFIX+'minihry.xml':wrapper('minihry','kovareni','kovareni.xml'),
               PREFIX+'kovareni.xml':read(scripts,NATIVE)}
    controller=ET.fromstring(resources[PREFIX+'kovareni.xml'])
    checked=[];roles=set()
    for definition in controller.findall('.//Definition'):
        relative=definition.get('File')
        path=posixpath.join(posixpath.dirname(NATIVE),relative)
        blob=read(scripts,path);dialog=ET.fromstring(blob)
        for response in dialog.iter('Response'):
            roles.add(response.get('Role'))
            text=response.find('Text')
            if text is None:continue
            audio='dialog/open_world/minihry/tmck_'+text.get('StringName')+'.ogg'
            if audio not in recording_names:raise ValueError('Missing native recording '+audio)
            checked.append(audio)
        # Preserve native lines, decisions, aliases and tutorial suppression.
        resources[PREFIX+relative]=blob
    if len(roles)!=9 or len(controller.findall('.//Definition'))!=9:
        raise ValueError('Expected nine native smithing warning/progress roles')
    return resources,dict(roles=sorted(roles),recordings_checked=sorted(set(checked)),
                          voice_namespace='open_world/minihry',runtime_verified=False)


def build(game,mod,output,base=None):
    if output.exists():raise FileExistsError(output)
    relative='Data/gluemappertravel.pak';source=(base or mod)/relative
    names=set()
    for pak in (game/'Localization').glob('*.pak'):
        if 'english' in pak.name.lower():
            with zipfile.ZipFile(pak) as z:names.update(z.namelist())
    with zipfile.ZipFile(source) as archive,zipfile.ZipFile(game/'Data/Scripts.pak') as scripts:
        resources,report=patch(read(archive,HOST),scripts,names)
    dest=output/'package'/relative;rewrite(source,dest,resources)
    with zipfile.ZipFile(source) as a,zipfile.ZipFile(dest) as b:
        assert {i.filename:(i.CRC,i.file_size) for i in a.infolist() if i.filename not in resources}=={i.filename:(i.CRC,i.file_size) for i in b.infolist() if i.filename not in resources}
        assert all(read(b,n)==v for n,v in resources.items())
    report.update(baseline={relative:digest(mod/relative)},source_sha256=digest(source),
                  packages={relative:digest(dest)},installed=False)
    (output/'report.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(dict(roles=len(report['roles']),recordings=len(report['recordings_checked']),installed=False)))


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for key in ('game','mod','output'):p.add_argument('--'+key,type=Path,required=True)
    p.add_argument('--base',type=Path)
    build(**vars(p.parse_args()))
