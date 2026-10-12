"""Stage native sitting interactions against the currently installed test mod."""
import argparse
import json
from pathlib import Path
import zipfile
import xml.etree.ElementTree as ET
from seating_animations import install, ANIMATIONS

from build_horse_trader_test import digest, rewrite
from chairs import convert
from region_travel import guid
from upgrade_map import read


def build(source, target, mod, output, baseline=None, bench_area=None):
    if output.exists(): raise FileExistsError('Choose a fresh staging directory')
    original = baseline or mod/'Data/Levels/kcd1_travel/level.pak'
    with zipfile.ZipFile(original) as level:
        files = {name: read(level, name) for name in ('objects_mission0.xml', 'waitinglinks.xml')}
        for name in ('smartobjecthelpersetanimations.xml', 'tables/ai/smartobjectanimations.xml'):
            if name in level.namelist(): files[name] = read(level, name)
    with zipfile.ZipFile(source/'Data/Levels/rataje/level.pak') as source_level, \
         zipfile.ZipFile(target/'Data/Levels/trosecko/level.pak') as native:
        updated, report = convert(files, source_level, native, guid, incremental=True)
        from benches import convert as convert_benches
        with zipfile.ZipFile(source/'Data/GameData.pak') as game:
            helper_name = next(n for n in game.namelist() if n.lower() == 'libs/smartobjects.xml')
            updated, report['benches'] = convert_benches(updated, source_level, native, read(game, helper_name), guid, bench_area, incremental=True)
        updated, report['animation_contract'] = install(updated, native, prefixes=('gm_chair_', 'gm_bench_', 'gm_rental_'))
    destination = output/'Data/Levels/kcd1_travel/level.pak'
    rewrite(original, destination, updated)
    travel = mod/'Data/gluemappertravel.pak'
    modid = ET.parse(mod/'mod.manifest').findtext('info/modid')
    if not modid: raise ValueError('Missing mod id')
    mounted = f'Mods/{modid}/Data/Levels/kcd1_travel/{ANIMATIONS}'
    rewrite(travel, output/'Data/gluemappertravel.pak', {mounted: updated[ANIMATIONS]})
    report['travel_baseline_sha256'] = digest(travel)
    report.update(baseline=str(original), baseline_sha256=digest(original),
                  level_sha256=digest(destination), runtime_tested=False)
    (output/'chairs-report.json').write_text(json.dumps(report, indent=2)+'\n', encoding='utf-8')
    print(json.dumps({k:v for k,v in report.items() if k not in ('records', 'benches')}, indent=2))
    print('Benches:', report['benches']['converted_benches'], 'places:', report['benches']['places'])


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    for option in ('source', 'target', 'mod', 'output'):
        parser.add_argument('--'+option, type=Path, required=True)
    parser.add_argument('--baseline', type=Path)
    parser.add_argument('--bench-area', nargs=4, type=float, metavar=('X', 'Y', 'Z', 'RADIUS'))
    build(**vars(parser.parse_args()))
