"""Build the independent fishing mod entirely from the user's local KCD2 files."""
from pathlib import Path
import json
import sys
import xml.etree.ElementTree as ET
import zipfile

from build_fishing import (ADB, FRAGMENTS, CONTROLLER, ROD, TEXT, CAST_RELEASE,
                           CAST_HOLD, CAST_START, animation_resources, item_and_stock, water_lua)
from fishing_meshes import resources as meshes, rod_resources
from setup_campaign import digest, game_version
from upgrade_map import read, xml

MOD_ID='kcd2fishing'
RECEIPT='fishing-install.json'


def asset_root():
    return Path(sys._MEIPASS) if getattr(sys,'frozen',False) else Path(__file__).resolve().parents[1]


def build(game, output, map_package=None, progress=lambda *a:None, cancelled=lambda:False):
    game,output=Path(game),Path(output)
    if output.exists(): raise ValueError('Fishing output already exists')
    root=asset_root();scripts=root/'tools'
    item,unused=item_and_stock(b'<database><ItemClasses version="2"/></database>',
        b'<database><InventoryPresets><InventoryPreset Name="gm_debug_forest_supplies"/><InventoryPreset Name="gm_rattay_smithing_supplies"/></InventoryPresets></database>')
    assets={'Libs/Tables/item/item__kcd2fishing.xml':item,
            'Libs/UI/Textures/Icons/Items/gm_fishing_rod_icon.dds':(root/'assets/fishing/gm_fishing_rod_icon.dds').read_bytes()}
    progress('Prepare fishing assets',0,4,'Animation and rod')
    with zipfile.ZipFile(game/'Data/Animations.pak') as z:
        assets.update(animation_resources(read(z,ADB),read(z,FRAGMENTS),read(z,CONTROLLER)))
    with zipfile.ZipFile(game/'Data/IPL_Objects-part5.pak') as z: assets.update(meshes(z))
    with zipfile.ZipFile(game/'Data/IPL_Objects-part3.pak') as z: assets.update(rod_resources(z))
    with zipfile.ZipFile(game/'Data/Tables.pak') as z:
        name='Libs/Tables/item/InventoryPreset__shops.xml'
        shops=ET.fromstring(read(z,name))
        merchant=shops.find("InventoryPresets/InventoryPreset[@Name='inventory_shop_commonMerchant']")
        if merchant is None: raise ValueError('Native general merchant stock was not found')
        ET.SubElement(merchant,'PresetItem',Name='gm_fishing_rod',Amount='2',Health='1',Quality='1')
        assets[name]=xml(shops)
    waters={}
    levels={name:game/f'Data/Levels/{name}/terrain.pak' for name in ('trosecko','kutnohorsko')}
    candidate=Path(map_package) if map_package else game/'Mods/kingdomcomegluemapper'
    for name in ('kcd1_rataje','kcd1_travel'):
        p=candidate/f'Data/Levels/{name}/terrain.pak'
        if p.exists(): levels[name]=p
    for i,(name,path) in enumerate(levels.items()):
        if cancelled(): raise InterruptedError('Fishing build cancelled')
        progress('Read region water',i,len(levels),name)
        with zipfile.ZipFile(path) as z: water,count=water_lua(read(z,'terrain/terrain.dat'))
        assets[f'Scripts/GMFishing/water_{name}.lua']=water;waters[name]=count
    names=','.join("['"+n+"']=true" for n in waters)
    assets['Scripts/GMFishing/water.lua']=("""
GMFishingWaters={}
local regions={%s}
local current=nil
function GMFishingSelectWater()
    local name=string.lower(tostring(System.GetCVar('sv_map') or '')):gsub('\\\\','/')
    name=name:gsub('/+$',''):match('([^/]+)$') or name
    if name~=current then
        current=name;GMFishingWaters={}
        if regions[name] then Script.ReloadScript('Scripts/GMFishing/water_'..name..'.lua') end
    end
end
"""%names).encode()
    for source,target in [('fishing_game.lua','rules'),('fishing_visuals.lua','visuals'),('fishing_interaction.lua','interaction')]:
        assets[f'Scripts/GMFishing/{target}.lua']=(scripts/source).read_bytes()
    runtime=(scripts/'fishing_runtime.lua').read_text().replace('__ROD_GUID__',ROD).replace('__CAST_RELEASE__',str(CAST_RELEASE)).replace('__CAST_HOLD__',str(CAST_HOLD-CAST_START))
    runtime=runtime.replace("        and System.GetEntityByName('gm_rattay_smithing_supplies')\n",'')
    runtime=runtime.replace('function F:bank()','function F:bank()\n    GMFishingSelectWater()')
    assets['Scripts/GMFishing/runtime.lua']=runtime.encode()
    # Use the native mod bootstrap rather than replacing player.lua, so map and
    # fishing can load together. Hook save initialization once the class exists.
    assets['Scripts/Mods/kcd2fishing.lua']=b'''
Script.ReloadScript('Scripts/GMFishing/runtime.lua')
local function attach()
    if not Player or not player then Script.SetTimer(500,attach);return end
    local init,load=Player.OnInit,Player.OnLoadAI
    function Player:OnInit(...)
        if init then init(self,...) end
        GMFishing:init()
    end
    function Player:OnLoadAI(...)
        if load then load(self,...) end
        GMFishing:init()
    end
    GMFishing:init()
end
Script.SetTimer(500,attach)
'''
    from build_fishing import ripple_library
    assets['Libs/Particles/gm_fishing.xml']=ripple_library()
    output.mkdir(parents=True)
    (output/'Data').mkdir();(output/'Localization').mkdir()
    def pak(path,contents):
        with zipfile.ZipFile(path,'w',zipfile.ZIP_DEFLATED) as z:
            for name,data in sorted(contents.items()):z.writestr(name,data)
    pak(output/'Data/kcd2fishing.pak',assets)
    table=ET.Element('Table')
    for key,value in TEXT.items():
        if key=='need_rod':value='Buy a fishing rod from a general merchant first.'
        row=ET.SubElement(table,'Row')
        for text in ('gm_fishing_'+key,value,value):ET.SubElement(row,'Cell').text=text
    from region_travel_dialogue import merge_localization
    language=candidate/'Localization/English_xml.pak'
    if not language.is_file():language=game/'Localization/English_xml.pak'
    with zipfile.ZipFile(language) as z:
        strings=merge_localization(read(z,'text_ui_items.xml'),xml(table))
    pak(output/'Localization/English_xml.pak',{'text_ui_items.xml':strings})
    manifest=ET.Element('kcd_mod');info=ET.SubElement(manifest,'info')
    for name,value in [('name','KCD2 Fishing'),('modid',MOD_ID),('description','Fishing with native casting and contextual controls. Rods stocked by general merchants.'),('version','0.3.0'),('author','SamG-Coder')]:
        ET.SubElement(info,name).text=value
    ET.SubElement(ET.SubElement(manifest,'supports'),'version').text=game_version(game)
    (output/'mod.manifest').write_bytes(xml(manifest))
    receipt={'schema':1,'owner':MOD_ID,'version':'0.3.0','water_regions':waters,
             'files':{p.relative_to(output).as_posix():digest(p) for p in output.rglob('*') if p.is_file()}}
    (output/RECEIPT).write_text(json.dumps(receipt,indent=2))
    progress('Fishing package verified',4,4,str(output))
    return output
