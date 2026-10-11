"""Stage Peshek's native supply shop and source daycycle in the current test mod."""
import argparse
import json
from pathlib import Path
import xml.etree.ElementTree as ET
import zipfile

from build_horse_trader_test import digest, rewrite, LEVEL_FILES
from character_person import actor_resources
from character_person_ai import FACTION_PATH
from character_person_appearance import build_appearance
import miller
import miller_world
from region_travel import guid
from region_travel_dialogue import merge_localization
from region_travel_tables import managed_patches
from upgrade_map import read, xml


def build(source, target, mod, output):
    if output.exists(): raise FileExistsError('Choose a fresh staging directory')
    output.mkdir(parents=True)
    modid=ET.parse(mod/'mod.manifest').findtext('info/modid')
    if not modid: raise ValueError('Missing manifest mod ID')
    paths=['Data/Levels/kcd1_travel/level.pak','Data/gluemappertravel.pak','Localization/English_xml.pak']
    baseline={name:digest(mod/name) for name in paths}
    with zipfile.ZipFile(mod/paths[0]) as z:
        files={n:read(z,n) for n in (*LEVEL_FILES,'smartobjecthelpersetanimations.xml','tables/ai/smartobjectanimations.xml')}
    with zipfile.ZipFile(mod/paths[1]) as z:
        resources={n:read(z,n) for n in z.namelist() if n.startswith(('Libs/Tables/','Libs/Storm/','Quests/')) and n.endswith('.xml')}
    if any(e.get('Name')==miller.NAME for e in ET.fromstring(files['objects_mission0.xml']).iter('Entity')):
        raise ValueError('Miller already installed; rebuild from baseline')
    faction=f'Libs/Tables/rpg/FactionTree__{modid}.xml'
    if faction in resources:resources[FACTION_PATH]=resources.pop(faction)
    print('Resolving Peshek, source stock and work/sleep schedule',flush=True)
    person=miller.resolve(source)
    stock,shop=miller.resources(person,target);resources.update(stock)
    character_dir=output/'miller-character'
    print('Converting source Peshek appearance and clothing',flush=True)
    character=build_appearance(source,target,person,miller.NAMESPACE,character_dir)
    resources=actor_resources(target,person,character,miller.NAMESPACE,role_name=miller.ROLE,
        native_soul_table='Libs/Tables/rpg/soul__ttac.xml',native_soul_name='ttac_procek',
        native_role_name='PREVOZNIK_TROSECKO',resources=resources)
    print('Registering shop, authored work point, home and native bed',flush=True)
    files,resources,world=miller_world.register(files,resources,person,shop,source,target,guid)
    assets={}
    for path in character_dir.rglob('*'):
        if not path.is_file():continue
        name=path.relative_to(character_dir).as_posix()
        if name.startswith('Localization/'):continue
        if name in resources:raise ValueError('Character resource collision: '+name)
        (resources if name.startswith('Libs/Tables/') else assets)[name]=path.read_bytes()
    resources=managed_patches(resources,modid)
    for name,blob in files.items():
        if name.startswith('tables/'):resources[f'Mods/{modid}/Data/Levels/kcd1_travel/{name}']=blob
    with zipfile.ZipFile(mod/paths[2]) as z:texts={n:read(z,n) for n in z.namelist()}
    strings=ET.Element('Table');row=ET.SubElement(strings,'Row')
    for v in ('ui_gm_miller_trade','(Trade)','(Trade)'):ET.SubElement(row,'Cell').text=v
    texts['text_ui_dialog.xml']=merge_localization(texts['text_ui_dialog.xml'],xml(strings))
    key=person['instance'].findtext('StaticData/NameStringId')
    with zipfile.ZipFile(source/'Localization/English_xml.pak') as z:
        names=ET.fromstring(read(z,'text_ui_soul.xml'))
    selected=ET.Element('Table')
    for row in names.findall('Row'):
        if row.findtext('Cell')==key:selected.append(row)
    if len(selected)!=1:raise ValueError('Missing source miller UI name')
    texts['text_ui_soul.xml']=merge_localization(texts['text_ui_soul.xml'],xml(selected))
    item_names=character_dir/'Localization/English/text_ui_items.xml'
    if item_names.exists():texts['text_ui_items.xml']=merge_localization(texts['text_ui_items.xml'],item_names.read_bytes())
    package=output/'package'
    for name,replacements in zip(paths,(files,resources,texts)):rewrite(mod/name,package/name,replacements)
    if sum(map(len,assets.values()))>1024**3-1024**2:raise ValueError('Miller assets require another shard')
    with zipfile.ZipFile(package/'Data/gluemapper_miller_assets.pak','x',zipfile.ZIP_STORED,allowZip64=False) as z:
        for name,blob in assets.items():z.writestr(name,blob)
    for name,blob in resources.items():
        if name.startswith('Libs/Tables/'):
            p=output/'validation'/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(blob)
    for name in ('scheduler','smartobjectanimations'):
        p=output/'validation/Libs/Tables/ai'/(name+'.xml');p.parent.mkdir(parents=True,exist_ok=True)
        p.write_bytes(files['tables/ai/'+name+'.xml'])
    report=dict(baseline=baseline,source_mod=str(mod),shop=shop,world=world,character=character,
        files={p.relative_to(package).as_posix():digest(p) for p in package.rglob('*') if p.is_file()},runtime_verified=False)
    (output/'miller-report.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
    return report


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ('source','target','mod','output'):parser.add_argument('--'+name,type=Path,required=True)
    build(**vars(parser.parse_args()))
