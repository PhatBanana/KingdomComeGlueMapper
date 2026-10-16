"""Combine accessible altar prayer with a stocked chest at the upper Rattay smithy."""
import argparse
from collections import Counter
import copy
import json
from pathlib import Path
import re
import xml.etree.ElementTree as ET
import zipfile

from build_church_prayer import attach_altars, FILES, ANIMATIONS, SCHEDULER
from build_horse_trader_test import digest, rewrite
from region_travel import guid
from upgrade_map import read, xml

PRESET='gm_rattay_smithing_supplies'
PRESET_FILE='Libs/Tables/item/InventoryPreset__kingdomcomegluemapper.xml'


def all_supplies(tables,batches=10):
    items={};recipes={}
    for name in tables.namelist():
        if re.fullmatch(r'Libs/Tables/item/item(?:__[^/]+)?\.xml',name,re.I):
            for row in ET.fromstring(read(tables,name)).findall('ItemClasses/*'):items[row.get('Id')]=row
        if re.fullmatch(r'Libs/Tables/minigame/BlacksmithRecipes(?:__[^/]+)?\.xml',name,re.I) and 'autotest' not in name.lower():
            for row in ET.fromstring(read(tables,name)).iter('BlacksmithRecipe'):recipes[row.get('Id')]=row
    books=[e for e in items.values() if e.get('BlacksmithRecipeId') in recipes]
    counts=Counter({e.get('Id'):1 for e in books})
    # Include ingredients for every native recipe, including ones whose unlock
    # comes from quests/perks rather than a readable recipe document.
    for recipe in recipes.values():
        for ingredient in recipe.findall('Ingredients/BlacksmithRecipeIngredient'):
            item=ingredient.get('ItemClassId')
            if item not in items:raise ValueError('Missing ingredient item '+str(item))
            counts[item]+=int(ingredient.get('Amount'))*batches
    result=[dict(id=k,name=items[k].get('Name'),amount=v) for k,v in sorted(counts.items())]
    return result,dict(recipe_documents=len(books),recipes=len(recipes),batches=batches,
        recipes_without_document=sorted(set(recipes)-{e.get('BlacksmithRecipeId') for e in books}))


def add_chest(mission,preset_blob,items):
    root=ET.fromstring(mission)
    if any(e.get('Name')==PRESET for e in root):raise ValueError('Workshop chest already exists')
    donor=next(e for e in root if e.get('Name')=='gm_debug_supply_chest')
    chest=copy.deepcopy(donor)
    chest.set('Name',PRESET);chest.set('EntityGuid',guid(PRESET))
    chest.set('EntityId',str(max(int(e.get('EntityId','0')) for e in root)+1))
    # Beside the open approach, away from the anvil and bellows animations.
    chest.set('Pos','2673.6,660.0,99.6947');chest.set('Rotate','1,0,0,0')
    for attr in ('ParentId','ParentGuid','Layer','Prefab'):chest.attrib.pop(attr,None)
    for link in list(chest.findall('EntityLinks')):chest.remove(link)
    props=chest.find('Properties')
    props.find('Database').set('sInventoryPreset',PRESET)
    props.find('Lock').set('bLocked','0');props.find('Script').set('bLootIsLegal','1')
    root.append(chest)
    tables=ET.fromstring(preset_blob);presets=tables.find('InventoryPresets')
    if any(e.get('Name')==PRESET for e in presets):raise ValueError('Workshop preset already exists')
    preset=ET.SubElement(presets,'InventoryPreset',Name=PRESET,Mode='All',Health='1')
    for item in items:ET.SubElement(preset,'PresetItem',Name=item['name'],ItemClassId=item['id'],Amount=str(item['amount']),Health='1',Quality='1')
    return xml(root),xml(tables)


def build(game,mod,output):
    if output.exists():raise FileExistsError(output)
    level='Data/Levels/kcd1_travel/level.pak';travel='Data/gluemappertravel.pak'
    with zipfile.ZipFile(game/'Data/Tables.pak') as z:items,stock=all_supplies(z)
    with zipfile.ZipFile(mod/level) as z:files,sites=attach_altars({n:read(z,n) for n in FILES})
    with zipfile.ZipFile(mod/travel) as z:
        files['objects_mission0.xml'],preset=add_chest(files['objects_mission0.xml'],read(z,PRESET_FILE),items)
    resources={PRESET_FILE:preset}
    script='Scripts/Entities/WH/Minigames/Smithery.lua'
    with zipfile.ZipFile(game/'Data/Scripts.pak') as z:
        native=read(z,script).decode('utf-8')
    hook='function Smithery:OnUsed( user, slot )'
    if native.count(hook)!=1:raise ValueError('Native smithery entry changed')
    diagnostic='''
    if string.find(self:GetName(), "gm_rattay_smith_", 1, true) == 1 then
        System.SetCVar("wh_pl_BlacksmithDebugDraw", 1)
        for _, key in ipairs({"wh_pl_BlacksmithQualityLossMultiplier", "wh_pl_BlacksmithCompletionGainMultiplier", "wh_pl_BlacksmithColdWorkpieceTemperature", "wh_pl_BlacksmithWorkpieceCannotBreak", "wh_pl_BlacksmithDisableHeatLoss"}) do
            System.LogAlways("GM_SMITH_DIAGNOSTIC " .. key .. "=" .. tostring(System.GetCVar(key)))
        end
    end
'''
    resources[script]=native.replace(hook,hook+diagnostic).encode('utf-8')
    for n in (ANIMATIONS,SCHEDULER):resources['Mods/kingdomcomegluemapper/Data/Levels/kcd1_travel/'+n]=files[n]
    changes={level:files,travel:resources}
    report=dict(installed=False,runtime_verified=False,baseline={},packages={},items=items,stock=stock,altars=sites,chest_position=[2673.6,660,99.6947])
    for rel,replacements in changes.items():
        report['baseline'][rel]=digest(mod/rel);target=output/'package'/rel
        rewrite(mod/rel,target,replacements)
        with zipfile.ZipFile(mod/rel) as a,zipfile.ZipFile(target) as b:
            assert {i.filename:(i.CRC,i.file_size) for i in a.infolist() if i.filename not in replacements}=={i.filename:(i.CRC,i.file_size) for i in b.infolist() if i.filename not in replacements}
            assert all(read(b,n)==v for n,v in replacements.items())
        report['packages'][rel]=digest(target)
    (output/'report.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(stock))


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for key in ('game','mod','output'):p.add_argument('--'+key,type=Path,required=True)
    build(**vars(p.parse_args()))
