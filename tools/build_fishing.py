"""Stage a held fishing rod, shoreline minigame and native Henry animations."""
import argparse
import copy
import json
import math
from pathlib import Path
import struct
import uuid
import xml.etree.ElementTree as ET
import zipfile

from build_horse_trader_test import digest, rewrite
from compiled_terrain import parse
from region_travel_dialogue import merge_localization
from upgrade_map import read, xml
from water_volumes import read_water

ROD=str(uuid.uuid5(uuid.NAMESPACE_URL,'KingdomComeGlueMapper/fishing/rod'))
ITEMS='Libs/Tables/item/item__kingdomcomegluemapper.xml'
PRESETS='Libs/Tables/item/InventoryPreset__kingdomcomegluemapper.xml'
PLAYER='Scripts/Entities/actor/player.lua'
ADB='Animations/Mannequin/ADB/kcd_male_database.adb'
FRAGMENTS='Animations/Mannequin/ADB/kcd_male_fragmentids.xml'
CONTROLLER='Animations/Mannequin/ADB/kcd_male_controllerdefs.xml'
CAST_CLIP='fisherman_cast_sitdown_01'
CAST_DURATION=14.133334159851074
# Native male.animevents: c_w_halberd_flick at normalized 0.3367099.
CAST_START=3.9
CAST_RELEASE=CAST_DURATION*.3367099-CAST_START
# Candidate standing follow-through, after the flick and before the 0.4991
# movement event, 0.6393 placement/detach and 0.8124 sitting event. Visual QA
# must confirm this exact frame; do not describe the pose as verified yet.
CAST_HOLD=6.0
TEXT={
    'name':'Fishing rod',
    'description':'Carry the rod in your inventory, look at water and choose Fish. The rod is drawn automatically. Watch the pale quill for a dip, then choose Catch fish or left click. Pull in, right click or walking cancels immediately and puts the rod away.',
    'need_rod':'Take the fishing rod from the test chest first.',
    'need_hold':'Carry a fishing rod and choose Fish while looking at water.',
    'empty_hand':'Put away your weapon or other held item before taking out the fishing rod.',
    'holding':'Look at water and choose Fish.',
    'put_away':'Fishing rod put away.',
    'need_bank':'Stand on a low, level, dry bank and face nearby water.',
    'casting':'Casting...',
    'wait':'Watch the float.',
    'bite':'A bite!',
    'hooked':'Fish hooked! Wait for it to tire before pulling.',
    'pull':'Pull now!',
    'slack':'Let the fish run. Wait for the next pull prompt.',
    'tension':'Too much tension! Stop pulling and wait.',
    'early':'Too early. You pulled the bait out before a bite.',
    'escaped':'The fish escaped.',
    'landing':'Landing your catch...',
    'caught':'Caught a trout! It has been added to your inventory.',
    'cancelled':'Fishing cancelled.',
    'reward_failed':'The catch could not be added to your inventory.',
}
TEXT.update({
    'action_fish':'Fish',
    'action_catch':'Catch fish',
    'action_retrieve':'Pull in',
    'aim_ready':'Release to cast.',
    'retrieving':'Reeling the line back in...',
    'need_hold':'Carry a fishing rod and choose Fish while looking at water.',
    'holding':'Aim at water, hold left click, then release to cast.',
    'charging':'Release left click to cast. Right click cancels.',
    'aim_short':'Hold left click briefly, then release to cast.',
    'need_bank':'Aim at nearby water, then cast.',
    'bank_land':'Aim at water.',
    'bank_aim':'Aim at water.',
    'bank_invalid':'The fishing target could not be read. Try aiming again.',
    'casting':'Casting... watch the float. Right click cancels.',
    'wait':'Watch the cork float. Click when it dips. Fishing ends after 60 seconds.',
    'bite':'The float is going under! Left click now!',
    'pull':'Pull now! Left click!',
    'caught':'Caught a fish! It has been added to your inventory.',
    'caught_trout':'Caught a trout! It has been added to your inventory.',
    'caught_perch':'Caught a perch! It has been added to your inventory.',
    'visual_failed':'The fishing float could not be loaded. Cast cancelled.',
    'rod_unavailable':'The rod tip is not ready. Put the rod away and draw it again.',
    'timeout':'No catch this time. Cast again when ready.',
    'missed':'Missed the bite. Right click to pull in or wait for the cast to end.',
})


def item_and_stock(item_blob,preset_blob):
    items=ET.fromstring(item_blob);presets=ET.fromstring(preset_blob)
    if any(e.get('Id')==ROD for e in items.iter()):raise ValueError('Fishing item already installed')
    ET.SubElement(items.find('ItemClasses'),'MeleeWeapon',Id=ROD,Name='gm_fishing_rod',
        Class='-1',Attack='0',AttackModStab='0',AttackModSlash='0',AttackModSmash='0',
        Defense='0',MaxStatus='100',StrReq='0',AgiReq='0',IsBreakable='false',
        Visibility='1',Conspicuousness='1',Charisma='0',SocialClassId='0',WealthLevel='0',MaxQuality='1',
        Model='GMFishing/rod',
        Weight='2',Price='20',FadeCoef='133.333328',VisibilityCoef='1',
        IconId='gm_fishing_rod',UIName='gm_fishing_name',UIInfo='gm_fishing_description')
    for name in ('gm_debug_forest_supplies','gm_rattay_smithing_supplies'):
        row=presets.find("InventoryPresets/InventoryPreset[@Name='"+name+"']")
        if row is None:raise ValueError('Test chest missing: '+name)
        ET.SubElement(row,'PresetItem',Name='gm_fishing_rod',ItemClassId=ROD,Amount='1',Health='1',Quality='1')
    return xml(items),xml(presets)


def animation_resources(adb,definitions,controller):
    database=ET.fromstring(adb);defs=ET.fromstring(definitions)
    control=ET.fromstring(controller)
    fragments=database.find('FragmentList')
    for name,donor in [('GMFishingCast','FishingCast'),('GMFishingIdle','FishingIdle'),('GMFishingLeave','FishingLeave')]:
        if fragments.find(name) is not None:raise ValueError('Fishing animation already registered')
        source=fragments.find(donor)
        if source is None:raise ValueError('Missing native fishing fragment '+donor)
        original=source.find('Fragment')
        fragment=ET.SubElement(ET.SubElement(fragments,name),'Fragment',Tags='',BlendOutDuration='.2',GUID=str(uuid.uuid5(uuid.NAMESPACE_URL,'gm/fishing/'+name)))
        fragment.append(copy.deepcopy(original.find('AnimLayer')))
        layer=fragment.find('AnimLayer')
        layer.clear()
        ET.SubElement(layer,'Blend',ExitTime='0',StartTime=str(CAST_START if name=='GMFishingCast' else CAST_HOLD),Duration='.15')
        if name=='GMFishingCast':
            ET.SubElement(layer,'Animation',name=CAST_CLIP)
            ET.SubElement(layer,'Blend',ExitTime=str(CAST_HOLD-CAST_START),StartTime=str(CAST_HOLD),Duration='0')
        # Hold the same clip at follow-through, never switch to the carry idle.
        ET.SubElement(layer,'Animation',name=CAST_CLIP,flags='Loop',speed='0')
        # Do not inherit NPC SetIdleState, alignment or movement-control layers:
        # the player's normal animation/movement state must remain recoverable.
        ET.SubElement(defs.find('Tags'),'Tag',name=name)
        ET.SubElement(control.find('FragmentDefs'),name,scopes='FullBody+UpperBody' if name=='GMFishingCast' else 'UpperBody')
    return {ADB:xml(database),FRAGMENTS:xml(defs),CONTROLLER:xml(control)}


def water_lua(blob):
    terrain=parse(blob);records,_=read_water(terrain);waters=[]
    for record in records:
        count=record['contour'] or record['vertices']
        offset=record['geometry_offset']+(record['vertices']*12 if record['contour'] else 0)
        p=[list(struct.unpack_from('<3f',terrain.data,offset+i*12)) for i in range(count)]
        area=abs(sum(p[i][0]*p[(i+1)%count][1]-p[(i+1)%count][0]*p[i][1] for i in range(count)))/2
        if area<25:continue
        bounds=[min(v[0] for v in p),min(v[1] for v in p),max(v[0] for v in p),max(v[1] for v in p)]
        perimeter=sum(math.hypot(p[i][0]-p[(i+1)%count][0],p[i][1]-p[(i+1)%count][1]) for i in range(count))
        # Converted materials do not encode habitats. Infer elongated channels;
        # this is a gameplay classification, not surveyed ecological metadata.
        kind='river' if perimeter*perimeter/(4*math.pi*area)>5 else 'pond'
        waters.append(dict(bounds=bounds,points=p,kind=kind))
    if not waters:raise ValueError('No water polygons')
    def vector(v):return '{'+','.join(f'{n:.6f}' for n in v)+'}'
    text='GMFishingWaters = {\n'+''.join('{kind="'+w['kind']+'",bounds='+vector(w['bounds'])+',points={'+','.join(vector(p) for p in w['points'])+'}},\n' for w in waters)+'}\n'
    return text.encode(),len(waters)


def build(game,mod,output,baseline=None):
    if output.exists():raise FileExistsError(output)
    source=baseline or mod
    travel='Data/gluemappertravel.pak';localization='Localization/English_xml.pak'
    with zipfile.ZipFile(source/travel) as z:
        item,presets=item_and_stock(read(z,ITEMS),read(z,PRESETS))
        player=read(z,PLAYER).decode('utf-8')
        if 'GMFishing:init()' in player:raise ValueError('Fishing runtime already installed')
    hook='''
-- GMFishing: preserve all existing player wrappers and save-loading behavior.
Script.ReloadScript('Scripts/GMFishing/runtime.lua')
do
    local init,load=Player.OnInit,Player.OnLoadAI
    function Player:OnInit(...)
        if init then init(self,...) end
        GMFishing:init()
    end
    function Player:OnLoadAI(...)
        if load then load(self,...) end
        GMFishing:init()
    end
end
'''
    with zipfile.ZipFile(mod/'Data/Levels/kcd1_travel/terrain.pak') as z:
        water,count=water_lua(read(z,'terrain/terrain.dat'))
    with zipfile.ZipFile(game/'Data/Animations.pak') as z:
        resources=animation_resources(read(z,ADB),read(z,FRAGMENTS),read(z,CONTROLLER))
    here=Path(__file__).parent
    resources.update({ITEMS:item,PRESETS:presets,PLAYER:(player+hook).encode(),
        'Libs/UI/Textures/Icons/Items/gm_fishing_rod_icon.dds':(here.parent/'assets/fishing/gm_fishing_rod_icon.dds').read_bytes(),
        'Scripts/GMFishing/rules.lua':(here/'fishing_game.lua').read_bytes(),
        'Scripts/GMFishing/visuals.lua':(here/'fishing_visuals.lua').read_bytes(),
        'Scripts/GMFishing/interaction.lua':(here/'fishing_interaction.lua').read_bytes(),
        'Scripts/GMFishing/water.lua':water,
        'Scripts/GMFishing/runtime.lua':(here/'fishing_runtime.lua').read_text().replace('__ROD_GUID__',ROD).replace('__CAST_RELEASE__',str(CAST_RELEASE)).replace('__CAST_HOLD__',str(CAST_HOLD-CAST_START)).encode()})
    from fishing_meshes import resources as fishing_mesh_resources, rod_resources
    with zipfile.ZipFile(game/'Data/IPL_Objects-part5.pak') as z:
        resources.update(fishing_mesh_resources(z))
    with zipfile.ZipFile(game/'Data/IPL_Objects-part3.pak') as z:
        resources.update(rod_resources(z))
    library=ET.Element('ParticleLibrary',Name='gm_fishing',ParticleVersion='28')
    effect=ET.SubElement(library,'Particles',Name='ripple')
    # Native ripple atlas/material, explicitly horizontal in world space.
    # Increase visibility range for casts rather than the native 4m footstep range.
    ET.SubElement(effect,'Params',Count='1',Continuous='false',ParticleLifeTime='1.0',Facing='Horizontal',TextureTiling='TilesX=4,TilesY=2,FirstTile=1,AnimFramesCount=7,AnimBlend=true',Material='Materials/particles/water_ripple',Alpha='0.18,ParticleAge=(v=0;t=0.15,v=1;t=0.5,v=0.6;t=1,v=0)',Size='0.3',InitAngles='x=0,y=0,z=0',MoveRelativeEmitter='false',OrientToVelocity='false',CameraMaxDistance='60',SortOffset='0.5',Speed='0',GravityScale='0')
    resources['Libs/Particles/gm_fishing.xml']=xml(library)
    strings=ET.Element('Table')
    for key,value in TEXT.items():
        row=ET.SubElement(strings,'Row')
        for text in ('gm_fishing_'+key,value,value):ET.SubElement(row,'Cell').text=text
    with zipfile.ZipFile(source/localization) as z:
        strings=merge_localization(read(z,'text_ui_items.xml'),xml(strings))
    report=dict(installed=False,runtime_verified=False,rod_id=ROD,water_polygons=count,baseline={},packages={})
    for rel,replacements in {travel:resources,localization:{'text_ui_items.xml':strings}}.items():
        report['baseline'][rel]=digest(mod/rel);target=output/'package'/rel
        rewrite(source/rel,target,replacements)
        with zipfile.ZipFile(source/rel) as a,zipfile.ZipFile(target) as b:
            assert {i.filename:(i.CRC,i.file_size) for i in a.infolist() if i.filename not in replacements}=={i.filename:(i.CRC,i.file_size) for i in b.infolist() if i.filename not in replacements}
            assert all(read(b,n)==v for n,v in replacements.items())
        report['packages'][rel]=digest(target)
    (output/'report.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report))


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ('game','mod','output'):parser.add_argument('--'+name,type=Path,required=True)
    parser.add_argument('--baseline',type=Path,help='Pre-fishing backup of travel and localization packages for upgrades')
    build(**vars(parser.parse_args()))
