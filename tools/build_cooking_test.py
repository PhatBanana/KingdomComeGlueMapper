"""Stage a cooking upgrade without rebuilding or replacing the existing world."""
import argparse
import json
from pathlib import Path
import zipfile

from build_horse_trader_test import digest, rewrite
from cooking_pots import convert
from region_travel import guid
from upgrade_map import read


def build(source, target, mod, output):
    if output.exists(): raise FileExistsError('Choose a fresh staging directory')
    original = mod/'Data/Levels/kcd1_travel/level.pak'
    with zipfile.ZipFile(original) as level, \
         zipfile.ZipFile(source/'Data/Levels/rataje/level.pak') as source_level, \
         zipfile.ZipFile(target/'Data/Levels/trosecko/level.pak') as native_level:
        files = {name: read(level, name) for name in ('objects_mission0.xml', 'waitinglinks.xml')}
        upgraded, report = convert(files, source_level, native_level, guid)
    destination = output/'Data/Levels/kcd1_travel/level.pak'
    rewrite(original, destination, upgraded)
    report.update(baseline=str(original), baseline_sha256=digest(original),
                  staged=str(destination), staged_sha256=digest(destination),
                  runtime_tested=False)
    (output/'cooking-report.json').write_text(json.dumps(report, indent=2)+'\n', encoding='utf-8')
    print(json.dumps({k: v for k, v in report.items() if k not in ('records', 'inactive_layer_pots')}, indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    for option in ('source', 'target', 'mod', 'output'):
        parser.add_argument('--'+option, type=Path, required=True)
    build(**vars(parser.parse_args()))
