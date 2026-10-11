"""Stage native room rental into the installed combined test mod."""
import argparse
import json
from pathlib import Path
import zipfile

from build_horse_trader_test import digest, rewrite
from region_travel import guid
from room_rental import build as convert
from upgrade_map import read


def build(source, target, mod, output):
    if output.exists(): raise FileExistsError('Choose a fresh staging directory')
    level = mod/'Data/Levels/kcd1_travel/level.pak'
    travel = mod/'Data/gluemappertravel.pak'
    with zipfile.ZipFile(level) as archive:
        files = {n: read(archive,n) for n in ('objects_mission0.xml','waitinglinks.xml',
            'triggerareas.fubar','smartobjecthelpersetanimations.xml','tables/ai/smartobjectanimations.xml',
            'tables/ai/scheduler.xml')}
    with zipfile.ZipFile(travel) as archive:
        resources = {n: read(archive,n) for n in archive.namelist() if n.startswith('Quests/') and n.endswith('.xml')}
    files, resources, report = convert(files, resources, source, target, guid)
    # The engine also resolves level tables through the mod virtual path.
    import xml.etree.ElementTree as ET
    modid = ET.parse(mod/'mod.manifest').findtext('info/modid')
    for name in ('smartobjectanimations','scheduler'):
        path=f'tables/ai/{name}.xml'
        resources[f'Mods/{modid}/Data/Levels/kcd1_travel/{path}'] = files[path]
    originals = {str(p.relative_to(mod)):digest(p) for p in (level,travel)}
    rewrite(level,output/'Data/Levels/kcd1_travel/level.pak',files)
    rewrite(travel,output/'Data/gluemappertravel.pak',resources)
    report.update(baseline=originals)
    (output/'rental-report.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(report,indent=2))


if __name__ == '__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ('source','target','mod','output'): parser.add_argument('--'+name,type=Path,required=True)
    build(**vars(parser.parse_args()))
