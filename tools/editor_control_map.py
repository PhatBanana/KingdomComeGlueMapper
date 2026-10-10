"""Author a small Sandbox source level using the existing Fritz control assets.

Run after creating fritz_editor_control in Sandbox and closing the editor.
This writes editor layers, never generated scheduler/mission binaries. Export
with the official HLOD -> Editor -export -> RC pipeline afterwards.
"""
import argparse
import copy
import json
from pathlib import Path
import shutil
import uuid
import xml.etree.ElementTree as ET
import zipfile

from upgrade_map import read

LEVEL = 'fritz_editor_control'
NAME = 'gmtest_trosky_ska_fricek'
MOD = 'gluemapper_fritz_trosky_test'


def write(path, root):
    path.parent.mkdir(parents=True, exist_ok=True)
    ET.indent(root)
    path.write_bytes(ET.tostring(root, encoding='utf-8', xml_declaration=True))


def prepare(editor, assets, output):
    level = editor / 'Data/Levels' / LEVEL
    if not (level / 'level.editor_xml').is_file():
        raise ValueError('Create the named level in Sandbox first')
    output.mkdir(parents=True, exist_ok=False)
    shutil.copytree(level, output / 'blank-source')
    native = editor / 'Data/Levels/trosecko/Layers/main'
    layer_id = str(uuid.uuid5(uuid.NAMESPACE_URL, LEVEL + '/main'))
    layer = ET.Element('Layer', GUID=layer_id, Name='Main', HavePhysics='1', IsDefaultColor='1')
    objects = ET.SubElement(layer, 'Objects')

    def pick(file, name, pos=None):
        tree = ET.parse(native / file)
        obj = copy.deepcopy(next(e for e in tree.findall('Objects/Object') if e.get('Name') == name))
        if pos: obj.set('Pos', pos)
        objects.append(obj)
        return obj

    land = pick('_script/generalsmartarea.lyr', 'sa_land', '400,400,-5')
    land.set('Height', '100')
    land.remove(land.find('EntityLinks'))
    land.remove(land.find('Points'))
    pts = ET.SubElement(land, 'Points')
    for p in ('0,0,0', '0,220,0', '220,220,0', '220,0,0'): ET.SubElement(pts, 'Point', Pos=p)
    nav = pick('_script/navigation.lyr', 'NavigationArea', '430,430,-2')
    nav.set('Height', '40')
    nav.remove(nav.find('Points'))
    pts = ET.SubElement(nav, 'Points')
    for p in ('0,0,0', '0,160,0', '160,160,0', '160,0,0'): ET.SubElement(pts, 'Point', Pos=p)
    ET.SubElement(objects,'Object',EntityClass='NavigationSeedPoint',Type='NavigationSeedPoint',
        Id=str(uuid.uuid5(uuid.NAMESPACE_URL,LEVEL+'/navseed')),Name='ControlNavigationSeed',Pos='512,512,32.1')
    for name in ('playerProxy', 'so_player_scheduler', 'playerHorseDefaultSmartObject', 'PlayerLinkRerouter'):
        pick('_script/player.lyr', name, '500,500,1')
    for name in ('so_crime_mrkev', 'so_crime_animal_interrupt', 'CrimeDebugger1'):
        pick('_script/crime.lyr', name, '420,420,1')
    # Keep only connections whose source-authored targets exist in this test.
    ids = {o.get('Id') for o in objects}
    removed = []
    for obj in objects:
        links = obj.find('EntityLinks')
        if links is not None:
            for link in list(links):
                if link.get('TargetId') not in ids:
                    removed.append(dict(source=obj.get('Name'), **link.attrib))
                    links.remove(link)
    links = ET.SubElement(land, 'EntityLinks')
    for label, name in [('mrkev','so_crime_mrkev'), ('redkev','so_crime_animal_interrupt'), ('playerLinkRerouter','PlayerLinkRerouter')]:
        obj = next(o for o in objects if o.get('Name') == name)
        ET.SubElement(links,'Link',Name=label,TargetId=obj.get('Id'))
    report = json.loads((assets / 'test-build.json').read_text())
    soulid = report['actor']['soul_id']
    actor = pick('tpod_podseminsko/banditCamp_for_4/_script/npc.lyr', 'tpod_bandit_3', '512,518,32.05')
    actor.set('Name', NAME); actor.set('Id', soulid)
    actor.remove(actor.find('EntityLinks'))
    anchorid = str(uuid.uuid5(uuid.NAMESPACE_URL, LEVEL + '/idle'))
    anchor = ET.SubElement(objects,'Object',EntityClass='TagPoint',Id=anchorid,Name='FritzIdle',Pos='512,518,32.05',Type='TagPoint')
    ET.SubElement(ET.SubElement(anchor,'EntityLinks'),'Link',Name='^delegate',TargetId=land.get('Id'))
    ET.SubElement(ET.SubElement(actor,'EntityLinks'),'Link',Name='_,schedulerWait',TargetId=anchorid)
    home=ET.SubElement(objects,'Object',EntityClass='SchedulerHub',Type='Entity',
        Id=str(uuid.uuid5(uuid.NAMESPACE_URL,LEVEL+'/home')),Name='FritzHome',Pos='512,518,32.05')
    ET.SubElement(ET.SubElement(home,'EntityLinks'),'Link',Name='home_area',TargetId=land.get('Id'))
    ET.SubElement(actor.find('EntityLinks'),'Link',Name='home',TargetId=home.get('Id'))
    hub=ET.SubElement(objects,'Object',EntityClass='TagPoint',Type='TagPoint',
        Id='c93887ca-90e2-4c4a-8fa2-73ed5b724d46',Name='hangoverSpotsHub',Pos='512,510,32.05')
    ET.SubElement(land.find('EntityLinks'),'Link',Name='hangoverSpotsHub',TargetId=hub.get('Id'))
    souls = ET.SubElement(ET.SubElement(ET.SubElement(layer,'WHData0',version='1'),'SoulList'),'Souls')
    soul = ET.SubElement(souls,'Soul',version='8')
    for key,val in dict(SharedSoulGuid=soulid,Guid=soulid,EntityGuid=soulid[:18],Name=NAME).items(): ET.SubElement(soul,key).text=val
    ET.SubElement(objects,'Object',Id=str(uuid.uuid5(uuid.NAMESPACE_URL,LEVEL+'/jug')),
        Name='ControlJug',Type='Brush',Prefab='Objects/manmade/task_specific_props/household/cooking_eating/jugs/jug_d.cgf',Pos='512,516,32')
    probe=pick('../main.lyr','global_probe_trosecko','512,512,35')
    probe.set('Name','ControlEnvironmentProbe')
    write(level/'Layers/main.lyr',layer)
    profile=ET.Element('LayerProfile',HasNavigation='1')
    ET.SubElement(profile,'ParentProfiles')
    ET.SubElement(ET.SubElement(profile,'ObjectLayers'),'ObjectLayer',GUID=layer_id,DebugPath='Main',Exported='1')
    write(level/'layerexportprofiles/game.xml',profile)
    root=ET.parse(level/'level.editor_xml').getroot()
    root.find('View').attrib.update(ViewerPos='512,511,33.7',ViewerAngles='0,0,0')
    root.find('Missions/Mission/ObjectLayers').set('DefaultStreamingProfile','game')
    # The editor default player remains: no existing retail save is altered.
    write(level/'level.editor_xml',root)
    with zipfile.ZipFile(editor/'Data/Levels/trosecko/level.pak') as z:
        (level/'Tables/WeatherProfiles.xml').write_bytes(read(z,'tables/weatherprofiles.xml'))
    package=editor/'Mods'/MOD
    if package.exists(): raise FileExistsError(package)
    package.mkdir(parents=True)
    shutil.copy2(assets/MOD/'mod.manifest',package/'mod.manifest')
    (package/'Data').mkdir()
    shutil.copy2(assets/MOD/'Data'/f'{MOD}.pak',package/'Data'/f'{MOD}.pak')
    shutil.copytree(assets/MOD/'Localization',package/'Localization')
    order=editor/'Mods/mod_order.txt'
    if order.exists(): shutil.copy2(order,output/'previous-mod-order.txt')
    order.write_text(MOD+'\n')
    (output/'source-report.json').write_text(json.dumps(dict(level=str(level),actor=NAME,
        objects=[o.attrib for o in objects],omitted_external_links=removed,
        runtime_verified=False,exported=False),indent=2))
    print(level)


if __name__ == '__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for key in ('editor','assets','output'): p.add_argument('--'+key,type=Path,required=True)
    a=p.parse_args();prepare(a.editor,a.assets,a.output)
