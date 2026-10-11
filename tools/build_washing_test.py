"""Stage native washing troughs into the current combined test mod."""
import argparse
import json
from pathlib import Path
import xml.etree.ElementTree as ET
import zipfile

from build_horse_trader_test import digest, rewrite
from region_travel import guid
from washing_troughs import convert
from upgrade_map import read


def build(source,target,mod,output):
    if output.exists():raise FileExistsError('Choose a fresh staging directory')
    level=mod/'Data/Levels/kcd1_travel/level.pak';travel=mod/'Data/gluemappertravel.pak'
    with zipfile.ZipFile(level) as archive, \
         zipfile.ZipFile(source/'Data/Levels/rataje/level.pak') as src, \
         zipfile.ZipFile(target/'Data/Levels/trosecko/level.pak') as native, \
         zipfile.ZipFile(source/'Data/GameData.pak') as src_game, \
         zipfile.ZipFile(target/'Data/IPL_GameData.pak') as game:
        files={n:read(archive,n) for n in ('objects_mission0.xml','waitinglinks.xml',
              'tables/ai/scheduler.xml','tables/ai/smartobjectanimations.xml','smartobjecthelpersetanimations.xml')}
        files,report=convert(files,src,native,src_game,game,guid)
    modid=ET.parse(mod/'mod.manifest').findtext('info/modid')
    resources={f'Mods/{modid}/Data/Levels/kcd1_travel/{n}':files[n]
               for n in ('tables/ai/scheduler.xml','tables/ai/smartobjectanimations.xml')}
    report['baseline']={str(p.relative_to(mod)):digest(p) for p in (level,travel)}
    rewrite(level,output/'Data/Levels/kcd1_travel/level.pak',files)
    rewrite(travel,output/'Data/gluemappertravel.pak',resources)
    (output/'washing-report.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({k:v for k,v in report.items() if k!='records'},indent=2))


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ('source','target','mod','output'):parser.add_argument('--'+name,type=Path,required=True)
    build(**vars(parser.parse_args()))
