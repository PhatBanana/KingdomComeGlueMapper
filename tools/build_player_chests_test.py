"""Stage native shared player storage against the currently installed test mod."""
import argparse
import json
from pathlib import Path
import zipfile

from build_horse_trader_test import digest, rewrite
from player_chests import build as build_chests
from region_travel import guid
from upgrade_map import read


def build(source, target, mod, output):
    if output.exists(): raise FileExistsError('Choose a fresh staging directory')
    original = mod/'Data/Levels/kcd1_travel/level.pak'
    with zipfile.ZipFile(original) as level:
        files = {name: read(level, name) for name in ('objects_mission0.xml', 'waitinglinks.xml', 'whdata_0')}
    updated, resources, report = build_chests(files, source, target, guid)
    destination = output/'Data/Levels/kcd1_travel/level.pak'
    rewrite(original, destination, updated)
    asset_pak = output/'Data/gluemapper_player_chests.pak'
    with zipfile.ZipFile(asset_pak, 'x', zipfile.ZIP_STORED, allowZip64=False) as archive:
        for name, payload in resources.items(): archive.writestr(name, payload)
    report.update(baseline=str(original), baseline_sha256=digest(original),
                  level_sha256=digest(destination), assets_sha256=digest(asset_pak),
                  runtime_tested=False, asset_files=len(resources))
    (output/'player-chests-report.json').write_text(json.dumps(report, indent=2)+'\n', encoding='utf-8')
    print(json.dumps({k:v for k,v in report.items() if k not in ('records', 'positions')}, indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    for option in ('source', 'target', 'mod', 'output'):
        parser.add_argument('--'+option, type=Path, required=True)
    build(**vars(parser.parse_args()))
