"""Opt-in developer forest cache overlay; preserve the installed world and tests."""
import argparse
from contextlib import ExitStack
import json
import math
from pathlib import Path
import re
import xml.etree.ElementTree as ET
import zipfile

from build_horse_trader_test import rewrite, digest
from campaign_entity_links import append_links, guid_value
from campaign_trigger_areas import TriggerArea, read_areas, write_areas
from debug_supply_quest import attach
from getting_started_dialogue import attach as attach_introduction
from region_travel import guid
from region_travel_ground import Heightfield
from region_travel_dialogue import merge_localization
from region_travel_tables import managed_patches
from static_assets import asset_pack
from upgrade_map import read, xml
from smithing_supplies import supplies as smithing_items, extend_preset

ITEM_NAMES = ('money', 'huntingSwordBasic', 'GambesonShort02_m01_E1',
              'HoseSeparate01_m01_E', 'Shoes01_m01_D')
PRESET = 'gm_debug_forest_supplies'
MODEL = 'objects/props/wooden_bins/chests/chest_02/chest02.cga'
PREFIX = 'objects/gluemapper/debug_supplies/'
CHEST_XY = (3787., 1817.)
SEARCH_XY = (3780., 1825.)
SEARCH_RADIUS = 35.


def supplies(target):
    found = {}
    with zipfile.ZipFile(target/'Data/Tables.pak') as archive:
        for name in archive.namelist():
            if re.fullmatch(r'Libs/Tables/item/item(?:__[^/]+)?\.xml', name, re.I):
                for row in ET.fromstring(read(archive, name)).findall('ItemClasses/*'):
                    if row.get('Name') in ITEM_NAMES:
                        if row.get('Name') in found: raise ValueError('Duplicate item name')
                        found[row.get('Name')] = dict(row.attrib)
    if set(found) != set(ITEM_NAMES): raise ValueError('Missing native equipment')
    for name, row in found.items():
        if float(row.get('StrReq', 0)) > 4 or float(row.get('AgiReq', 0)) > 6:
            raise ValueError('Starter equipment stat requirements increased: '+name)
    items = [found[name] for name in ITEM_NAMES]
    root = ET.Element('database', name='barbora')
    preset = ET.SubElement(ET.SubElement(root, 'InventoryPresets', version='2'),
                          'InventoryPreset', Name=PRESET, Mode='All', Health='1')
    for row in items:
        # Native money quantities are decigroschen (ten per displayed groschen).
        ET.SubElement(preset, 'PresetItem', Name=row['Name'], ItemClassId=row['Id'],
            Amount='200000' if row['Name']=='money' else '1', Health='1', Quality='1')
    # Keep the original five quest-required item types separate from optional
    # crafting supplies so the getting-started objective does not require them.
    with zipfile.ZipFile(target/'Data/Tables.pak') as archive:
        preset = extend_preset(xml(root), smithing_items(archive))
    return items, preset


def chest_assets(source):
    with ExitStack() as stack:
        index, emitted, material, mesh = asset_pack(stack, source.parent, PREFIX)
        emitted[PREFIX+Path(MODEL).name] = mesh(MODEL)
        for lod in (1, 2):
            name = MODEL[:-4]+f'_lod{lod}.cga'
            if name in index: emitted[PREFIX+Path(name).name] = mesh(name)
        with zipfile.ZipFile(source/'Data/Objects.pak') as archive:
            for name in archive.namelist():
                if name.lower().startswith(MODEL.rsplit('/',1)[0]+'/') and name.lower().endswith(('.anm','.animevents')):
                    emitted[PREFIX+Path(name).name] = read(archive,name)
        return dict(emitted)


def world(files, height):
    mission = ET.fromstring(files['objects_mission0.xml'])
    if any(e.get('Name')=='gm_debug_supply_chest' for e in mission):
        raise ValueError('Debug chest already installed; use recorded baseline')
    next_id = max(int(e.get('EntityId','0')) for e in mission)+1
    def entity(name, cls, pos):
        nonlocal next_id
        e = ET.SubElement(mission,'Entity',Name=name,EntityClass=cls,EntityId=str(next_id),
            EntityGuid=guid(name),Pos=','.join(map(str,pos)),Rotate='1,0,0,0',CastShadowMinSpec='1')
        next_id+=1
        return e
    x,y=CHEST_XY
    z=height(x,y)+.04
    chest=entity('gm_debug_supply_chest','Stash',(x,y,z))
    props=ET.SubElement(chest,'Properties',object_Model=PREFIX+Path(MODEL).name,
        bOwnedByHome='0',fUseAngle='-1',fUseDistance='2.5',sWH_AI_EntityCategory='Chest')
    ET.SubElement(props,'Database',sGeneratedInventory='inventory_empty',sInventoryPreset=PRESET)
    ET.SubElement(props,'Animation',anim_Close='close',anim_Open='open',bOpenOnly='0')
    ET.SubElement(props,'Lock',bLocked='0',bCanLockPick='0')
    ET.SubElement(props,'Physics',bRigidBody='0',bPhysicalize='1')
    ET.SubElement(props,'Script',bLootIsLegal='1')
    cx,cy=SEARCH_XY
    floor=min(height(cx+SEARCH_RADIUS*math.cos(i*math.tau/24),
                     cy+SEARCH_RADIUS*math.sin(i*math.tau/24)) for i in range(24))-5
    area=entity('gm_debug_supply_search','TriggerArea',(cx,cy,floor))
    ET.SubElement(area,'Properties',bSaved_by_game='0')
    polygon=tuple((cx+SEARCH_RADIUS*math.cos(i*math.tau/24),
                   cy+SEARCH_RADIUS*math.sin(i*math.tau/24),floor) for i in range(24))
    shapes=read_areas(files['triggerareas.fubar'])
    shapes['areas'].append(TriggerArea(guid_value(area.get('EntityGuid')),60,polygon))
    holder=next(e for e in mission if e.get('EntityClass')=='LevelHolder')
    # Native Barbora exports a SmartObjectHolder named after the Project and
    # links it to the LevelHolder. Without this root, Skald can execute states
    # but cannot traverse Level asset links (shops, stashes or map markers).
    roots=[e for e in mission if e.get('Name')=='GlueTravel_kcd1']
    if roots:
        project=roots[0]
        if len(roots)!=1 or project.get('EntityClass')!='SmartObjectHolder':
            raise ValueError('Unexpected project holder collision')
    else:
        project=entity('GlueTravel_kcd1','SmartObjectHolder',tuple(map(float,holder.get('Pos').split(','))))
        ET.SubElement(project,'Properties',bSaved_by_game='0')
    project_links=project.find('EntityLinks')
    if project_links is None:project_links=ET.SubElement(project,'EntityLinks')
    ET.SubElement(project_links,'Link',Name='module',TargetId=holder.get('EntityId'),TargetGuid=holder.get('EntityGuid'))
    links=holder.find('EntityLinks')
    if links is None: links=ET.SubElement(holder,'EntityLinks')
    compiled=[(project.get('EntityGuid'),holder.get('EntityGuid'),'module')]
    for e,alias in ((chest,'debug_supply_chest'),(area,'debug_supply_search')):
        label="asset['"+alias+"']"
        ET.SubElement(links,'Link',Name=label,TargetId=e.get('EntityId'),TargetGuid=e.get('EntityGuid'))
        compiled.append((holder.get('EntityGuid'),e.get('EntityGuid'),label))
    files=dict(files)
    files['objects_mission0.xml']=xml(mission)
    files['waitinglinks.xml']=append_links(files['waitinglinks.xml'],compiled)
    files['triggerareas.fubar']=write_areas(shapes['areas'],shapes['export_version'])
    return files,dict(chest_position=(x,y,z),search_center=SEARCH_XY,search_radius=SEARCH_RADIUS)


def build(source,target,mod,output,baseline=None):
    if output.exists():raise FileExistsError('Choose fresh output staging directory')
    output.mkdir(parents=True)
    modid=ET.parse(mod/'mod.manifest').findtext('info/modid')
    base=baseline or mod
    travel=base/'Data/gluemappertravel.pak'
    level=base/'Data/Levels/kcd1_travel/level.pak'
    localization=base/'Localization/English_xml.pak'
    with zipfile.ZipFile(travel) as a:
        resources={n:read(a,n) for n in a.namelist() if n.endswith('.xml') and n.startswith(('Quests/','Libs/Tables/'))}
    with zipfile.ZipFile(level) as a:
        files={n:read(a,n) for n in ('objects_mission0.xml','waitinglinks.xml','triggerareas.fubar')}
    with zipfile.ZipFile(mod/'Data/Levels/kcd1_travel/terrain.pak') as a:
        height=Heightfield(read(a,'terrain/terrain.dat'))
    items,preset=supplies(target)
    resources['Libs/Tables/item/InventoryPreset__debug_supplies.xml']=preset
    files,placement=world(files,height)
    with zipfile.ZipFile(target/'Data/Scripts.pak') as a:
        resources,strings=attach(resources,items,a)
    resources,dialog_strings=attach_introduction(resources)
    resources=managed_patches(resources,modid)
    with zipfile.ZipFile(localization) as a:
        texts={n:read(a,n) for n in a.namelist()}
    texts['text_ui_quest.xml']=merge_localization(texts.get('text_ui_quest.xml',b'<Table/>'),strings)
    texts['text_ui_dialog.xml']=merge_localization(texts['text_ui_dialog.xml'],dialog_strings)
    assets=chest_assets(source)
    package=output/'package'
    rewrite(travel,package/'Data/gluemappertravel.pak',resources)
    rewrite(level,package/'Data/Levels/kcd1_travel/level.pak',files)
    rewrite(localization,package/'Localization/English_xml.pak',texts)
    with zipfile.ZipFile(package/'Data/gluemapper_debug_supplies.pak','x',zipfile.ZIP_STORED,allowZip64=False) as a:
        for n,b in assets.items():a.writestr(n,b)
    for n,b in resources.items():
        if n.startswith('Libs/Tables/'):
            dest=output/'validation'/n;dest.parent.mkdir(parents=True,exist_ok=True);dest.write_bytes(b)
    report=dict(placement=placement,items=items,groschen=20000,source_chest=MODEL,
        equipment='Native KCD2 starter equipment; not converted KCD1 wearable assets',
        runtime_verified=False,baseline_root=str(base),baseline={str(p.relative_to(base)):digest(p) for p in (travel,level,localization)},
        files={str(p.relative_to(package)):digest(p) for p in package.rglob('*') if p.is_file()})
    (output/'report.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    print(json.dumps(placement),flush=True)
    return report


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    for n in ('source','target','mod','output'):parser.add_argument('--'+n,type=Path,required=True)
    parser.add_argument('--baseline',type=Path,help='Previously recorded package before the debug overlay')
    args=parser.parse_args();build(args.source,args.target,args.mod,args.output,args.baseline)
