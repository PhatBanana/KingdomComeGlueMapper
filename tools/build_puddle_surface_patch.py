"""Stage muddy-puddle proxy corrections in existing mod packages.

Only matching material XML is changed. Install staged archives while the game
is closed. No terrain, placement, texture, or visible shader edits are made.
"""
import argparse
import copy
import hashlib
import json
from pathlib import Path
import shutil
import xml.etree.ElementTree as ET
import zipfile

from puddle_materials import convert_puddle_proxies


def stage(data, output):
    output.mkdir(parents=True, exist_ok=False)
    report = []
    for source in sorted(data.glob('*.pak')):
        changes = {}
        with zipfile.ZipFile(source) as archive:
            for entry in archive.infolist():
                if not entry.filename.lower().endswith('.mtl'):
                    continue
                original = archive.read(entry)
                if b'mat_water' not in original or b'mat_mudwater' not in original:
                    continue
                material = ET.fromstring(original)
                count = convert_puddle_proxies(material)
                if count:
                    changes[entry.filename] = ET.tostring(material, encoding='utf-8', xml_declaration=True)
                    report.append(dict(package=source.name, material=entry.filename, proxies=count,
                                       original_sha256=hashlib.sha256(original).hexdigest()))
            if not changes:
                continue
            names = archive.namelist()
            if len(names) != len(set(names)):
                raise ValueError(f'Duplicate archive entries: {source}')
            destination = output / source.name
            with zipfile.ZipFile(destination, 'x') as target:
                for entry in archive.infolist():
                    if entry.filename in changes:
                        target.writestr(copy.copy(entry), changes[entry.filename])
                    else:
                        with archive.open(entry) as src, target.open(copy.copy(entry), 'w') as dst:
                            shutil.copyfileobj(src, dst, 1024 * 1024)
            with zipfile.ZipFile(destination) as check:
                assert check.namelist() == names
                for old in archive.infolist():
                    new = check.getinfo(old.filename)
                    if old.filename in changes:
                        assert check.read(new) == changes[old.filename]
                    else:
                        assert (old.CRC, old.file_size) == (new.CRC, new.file_size)
    (output / 'report.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    result = stage(args.data, args.output)
    print(f'Staged {sum(r["proxies"] for r in result)} proxies in {len(result)} materials')
