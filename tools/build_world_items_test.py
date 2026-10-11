"""Stage native world pickups in the current test mod without changing it."""
import argparse
import json
from pathlib import Path
import xml.etree.ElementTree as ET
import zipfile
from build_horse_trader_test import digest,rewrite
from region_travel_tables import managed_patches
from region_travel_dialogue import merge_localization
from upgrade_map import read
import world_items


def build(source,target,mod,output):
    if output.exists():raise FileExistsError('Choose a fresh output directory')
    output.mkdir(parents=True)
    modid=ET.parse(mod/'mod.manifest').findtext('info/modid')
    if not modid:raise ValueError('Missing mod ID')
    paths=['Data/Levels/kcd1_travel/level.pak','Data/gluemappertravel.pak','Localization/English_xml.pak']
    baseline={n:digest(mod/n) for n in paths}
    with zipfile.ZipFile(mod/paths[0]) as z:files={'objects_mission0.xml':read(z,'objects_mission0.xml')}
    with zipfile.ZipFile(mod/paths[1]) as z:
        resources={n:read(z,n) for n in z.namelist() if n.startswith('Libs/Tables/') and n.endswith('.xml')}
    files,resources,strings,assets,report=world_items.build(files,resources,source,target,output/'conversion')
    resources=managed_patches(resources,modid)
    with zipfile.ZipFile(mod/paths[2]) as z:texts={n:read(z,n) for n in z.namelist()}
    for name,blob in strings.items():texts[name]=merge_localization(texts.get(name,b'<Table/>'),blob)
    package=output/'package'
    for name,replacements in zip(paths,(files,resources,texts)):rewrite(mod/name,package/name,replacements)
    world_items.pack_assets(package/'Data/gluemapper_world_items.pak',assets)
    for name,blob in resources.items():
        p=output/'validation'/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(blob)
    report.update(baseline=baseline,source_mod=str(mod),
        files={p.relative_to(package).as_posix():digest(p) for p in package.rglob('*') if p.is_file()})
    (output/'world-items-report.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
    return report


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ('source','target','mod','output'):parser.add_argument('--'+name,type=Path,required=True)
    build(**vars(parser.parse_args()))
