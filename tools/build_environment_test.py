"""Stage an additive environmental conversion against an installed world."""
import argparse
import json
from pathlib import Path
import zipfile

from build_horse_trader_test import rewrite, digest
from region_travel import guid
from upgrade_map import read
from world_environment import build as convert


def build(source, target, level, output):
    if output.exists(): raise FileExistsError('Choose a fresh staging directory')
    with zipfile.ZipFile(level) as archive:
        mission, report = convert(read(archive, 'objects_mission0.xml'), source, target, guid)
    output.mkdir(parents=True)
    rewrite(level, output/'level.pak', {'objects_mission0.xml': mission})
    with zipfile.ZipFile(level) as before, zipfile.ZipFile(output/'level.pak') as after:
        baseline = {i.filename:(i.CRC,i.file_size) for i in before.infolist() if i.filename != 'objects_mission0.xml'}
        staged = {i.filename:(i.CRC,i.file_size) for i in after.infolist() if i.filename != 'objects_mission0.xml'}
        if baseline != staged: raise ValueError('Unrelated archive entries changed')
    report.update(baseline_sha256=digest(level), staged_sha256=digest(output/'level.pak'),
                  preserved_archive_entries=len(baseline))
    (output/'report.json').write_text(json.dumps(report, indent=2)+'\n', encoding='utf-8')
    print(json.dumps({k:v for k,v in report.items() if k != 'records'}, indent=2))
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('source','target','level','output'): parser.add_argument('--'+name, type=Path, required=True)
    build(**vars(parser.parse_args()))
