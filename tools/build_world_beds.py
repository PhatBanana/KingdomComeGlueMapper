"""Stage native bed interactions in an existing combined mod without installing."""
import argparse
import json
from pathlib import Path
import xml.etree.ElementTree as ET
import zipfile

from build_horse_trader_test import digest, rewrite
from region_travel import guid
from upgrade_map import read
from world_beds import build as convert, LEVEL_FILES, ANIMATIONS, SCHEDULER


def build(source, target, mod, output):
    if output.exists():
        raise FileExistsError('Choose a fresh staging directory')
    level = mod/'Data/Levels/kcd1_travel/level.pak'
    travel = mod/'Data/gluemappertravel.pak'
    modid = ET.parse(mod/'mod.manifest').findtext('info/modid')
    if not modid:
        raise ValueError('Missing mod id')
    with zipfile.ZipFile(level) as archive:
        files = {n: read(archive, n) for n in LEVEL_FILES}
    updated, report = convert(files, source, target, guid)
    destination = output/'Data/Levels/kcd1_travel/level.pak'
    rewrite(level, destination, updated)
    mounted = {f'Mods/{modid}/Data/Levels/kcd1_travel/{n}': updated[n]
               for n in (ANIMATIONS, SCHEDULER)}
    rewrite(travel, output/'Data/gluemappertravel.pak', mounted)
    preserved = {}
    for old, new, replacements in ((level, destination, updated),
            (travel, output/'Data/gluemappertravel.pak', mounted)):
        with zipfile.ZipFile(old) as a, zipfile.ZipFile(new) as b:
            before = {i.filename: (i.CRC, i.file_size) for i in a.infolist() if i.filename not in replacements}
            after = {i.filename: (i.CRC, i.file_size) for i in b.infolist() if i.filename not in replacements}
            if before != after:
                raise ValueError('Unrelated archive entries changed: ' + str(old))
            for name, payload in replacements.items():
                if read(b, name) != payload:
                    raise ValueError('Staged table mismatch: ' + name)
            preserved[old.name] = len(before)
    report.update(baseline_sha256=digest(level), travel_baseline_sha256=digest(travel),
                  staged_level_sha256=digest(destination), unrelated_entries_preserved=preserved)
    (output/'report.json').write_text(json.dumps(report, indent=2)+'\n', encoding='utf-8')
    print(json.dumps({k: v for k, v in report.items() if k not in ('records', 'inactive_layers')}, indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('source', 'target', 'mod', 'output'):
        parser.add_argument('--'+name, type=Path, required=True)
    build(**vars(parser.parse_args()))
