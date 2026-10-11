"""Stage interactive doors into the existing combined test build."""
import argparse
import json
from pathlib import Path
import xml.etree.ElementTree as ET
import zipfile

from build_horse_trader_test import digest, rewrite
from region_travel_dialogue import merge_localization
from region_travel_tables import managed_patches
from upgrade_map import read
from world_doors import build as convert


def build(source,target,mod,output):
    if output.exists():raise FileExistsError('Choose a fresh staging directory')
    level=mod/'Data/Levels/kcd1_travel/level.pak';travel=mod/'Data/gluemappertravel.pak'
    localization=mod/'Localization/English_xml.pak'
    with zipfile.ZipFile(level) as z:
        files={n:read(z,n) for n in ('objects_mission0.xml','waitinglinks.xml',
              'tables/ai/scheduler.xml','tables/ai/smartobjectanimations.xml','smartobjecthelpersetanimations.xml')}
    files,resources,strings,report=convert(files,source,target)
    modid=ET.parse(mod/'mod.manifest').findtext('info/modid')
    with zipfile.ZipFile(travel) as z:
        name='Libs/Tables/item/item__'+modid+'.xml'
        resources[name]=read(z,name)
    resources=managed_patches(resources,modid)
    resources.update({f'Mods/{modid}/Data/Levels/kcd1_travel/{n}':files[n]
                      for n in files if n.startswith('tables/')})
    with zipfile.ZipFile(localization) as z:
        strings=merge_localization(read(z,'text_ui_items.xml'),strings)
    report['baseline']={str(p.relative_to(mod)):digest(p) for p in (level,travel,localization)}
    rewrite(level,output/'Data/Levels/kcd1_travel/level.pak',files)
    rewrite(travel,output/'Data/gluemappertravel.pak',resources)
    rewrite(localization,output/'Localization/English_xml.pak',{'text_ui_items.xml':strings})
    (output/'doors-report.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({k:v for k,v in report.items() if k not in ('records','inactive_layer_doors')},indent=2))


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ('source','target','mod','output'):parser.add_argument('--'+name,type=Path,required=True)
    build(**vars(parser.parse_args()))
