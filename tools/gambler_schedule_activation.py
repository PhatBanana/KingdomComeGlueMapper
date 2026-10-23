"""Gate source dice choices before native resource acquisition."""
import copy
from pathlib import Path
import xml.etree.ElementTree as E
import zipfile
from campaign_entity_links import append_links
from character_city_benches import signature
from character_person import unique
from upgrade_map import read, xml


def prepare(package,target,files,reports,definitions):
    from setup_gameplay import PROJECT, ENTRY
    definitions=dict(definitions)
    with zipfile.ZipFile(Path(package)/'Data/gluemappertravel.pak') as z:
        project=E.fromstring(definitions.get(PROJECT) or read(z,PROJECT))
        entry=E.fromstring(definitions.get(ENTRY) or read(z,ENTRY))
    p=project.find('Skald/Project');level=entry.find('Skald/Level')
    mission=E.fromstring(files['objects_mission0.xml'])
    host=unique((e for e in mission if e.get('Name')==p.get('Name')),'dice activation project')
    with zipfile.ZipFile(Path(target)/'Data/Scripts.pak') as z:
        money=read(z,'Quests/Final/Barbora/utils/money/hasmoney.xml')
        convert=read(z,'Quests/Final/Barbora/utils/money/converttogroshen.xml')
        donor=E.fromstring(read(z,'Quests/Final/Barbora/trosecko/vezniNaTroskach/hibernable/trosky_pred_bouri/straze_na_hrade/baba.xml'))
    compare=E.fromstring(money).find(".//Function[@MethodName='Control::Compare']")
    if compare is None or compare.find("Constant[@Name='Op']").get('Value')!='GreaterEquals':
        raise ValueError('Native money eligibility changed')
    activation=unique((n for n in donor.iter('SchedulerLinkActivation') if n.find("Constant[@Name='LinkTag']") is not None
                       and n.find("Constant[@Name='LinkTag']").get('Value')=='sleepAtBaba'),'native scheduler activation')
    if activation.find('Edge').get('To')!='IsActive':raise ValueError('Native scheduler activation input changed')
    wrapper=E.Element('Database',Name='barbora');module=E.SubElement(E.SubElement(wrapper,'Skald'),'Module',Name='gmDiceFunds')
    ports=E.SubElement(module,'Ports')
    E.SubElement(ports,'Port',Name='actor',Direction='In',Type='wh::rpgmodule::I_Soul*')
    E.SubElement(ports,'ConstantPort',Name='minimum',Direction='In',Type='float',Value='0')
    E.SubElement(ports,'ConstantPort',Name='tag',Direction='In',Type='string',Value='')
    deps=E.SubElement(module,'Definitions')
    for name in ('hasmoney','converttogroshen'):E.SubElement(deps,'Definition',File=name+'.xml')
    nodes=E.SubElement(module,'Nodes')
    properties=E.SubElement(nodes,'ObjectProperties',Name='actorProperties',DeclaringType='wh::rpgmodule::I_Soul')
    E.SubElement(properties,'Edge',From='actor',To='I_Soul')
    check=E.SubElement(nodes,'hasmoney',Name='eligible',Namespace='')
    E.SubElement(check,'Edge',From='actorProperties.Inventory',To='inventory');E.SubElement(check,'Edge',From='minimum',To='amount')
    activation=copy.deepcopy(activation);activation.attrib={'Name':'activate'}
    for child in list(activation):activation.remove(child)
    E.SubElement(activation,'Edge',From='tag',To='LinkTag');E.SubElement(activation,'Edge',From='eligible.hasmoney',To='IsActive')
    nodes.append(activation)
    path=ENTRY.rsplit('/',1)[0]+'/dice_work/gmDiceFunds.xml'
    definitions.update({path:xml(wrapper),path.rsplit('/',1)[0]+'/hasmoney.xml':money,
                        path.rsplit('/',1)[0]+'/converttogroshen.xml':convert})
    from world_gameplay_basis import validate_dependency_scopes
    with zipfile.ZipFile(Path(target)/'Data/IPL_GameData.pak') as z:
        validate_dependency_scopes(definitions,path,read(z,'Libs/concept/definitions.xml'))
    deps=level.find('Definitions')
    if deps is None:deps=E.SubElement(level,'Definitions')
    dependency=E.Element('Definition',File='dice_work/gmDiceFunds.xml')
    if not any(n.get('File')==dependency.get('File') for n in deps):deps.append(dependency)
    additions=[]
    for report in reports:
        name='gm_dice_actor_'+report['actor_guid'].replace('-','').lower()
        actor=unique((e for e in mission if e.get('EntityGuid')==report['actor_guid']),'source gambler')
        assets=p.find('Assets')
        found=assets.find("*[@Name='"+name+"']")
        if found is None:E.SubElement(assets,'SoulAsset',Name=name)
        elif found.tag!='SoulAsset':raise ValueError('Dice actor asset collision')
        links=host.find('EntityLinks')
        if links is None:links=E.SubElement(host,'EntityLinks')
        label="asset['"+name+"']"
        link=E.Element('Link',Name=label,TargetId=actor.get('EntityId'),TargetGuid=actor.get('EntityGuid'))
        existing=[n for n in links if n.get('Name')==label]
        if existing and (len(existing)!=1 or signature(existing[0])!=signature(link)):raise ValueError('Dice actor binding collision')
        if not existing:links.append(link)
        additions.append((host.get('EntityGuid'),actor.get('EntityGuid'),label))
        node=E.Element('gmDiceFunds',Name=name+'_funds',Namespace='')
        E.SubElement(node,'Asset',Name='actor',Alias=name)
        E.SubElement(node,'Constant',Name='minimum',Value=str(report['policy']['minimum_groschen']))
        E.SubElement(node,'Constant',Name='tag',Value=report['funded_tag'])
        current=level.find("Nodes/*[@Name='"+node.get('Name')+"']")
        if current is not None and signature(current)!=signature(node):raise ValueError('Dice funds activation collision')
        if current is None:level.find('Nodes').append(node)
    definitions.update({PROJECT:xml(project),ENTRY:xml(entry)})
    return dict(files,**{'objects_mission0.xml':xml(mission),'waitinglinks.xml':append_links(files['waitinglinks.xml'],additions)}),definitions
