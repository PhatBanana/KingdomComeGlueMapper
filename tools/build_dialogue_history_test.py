"""Upgrade native sequence-history registration in an existing dialogue package."""
import argparse
import json
from pathlib import Path
import xml.etree.ElementTree as ET
import zipfile

from campaign_dialogue import expose_sequence_history
from build_horse_trader_test import digest, rewrite
from upgrade_map import read, xml


def build(source, output):
    if output.exists():
        raise FileExistsError('Choose a fresh staging directory')
    replacements, changes = {}, {}
    with zipfile.ZipFile(source) as archive:
        for name in archive.namelist():
            if not name.lower().endswith('.xml'):
                continue
            blob = read(archive, name)
            if b'SequenceUsed(' not in blob:
                continue
            root = ET.fromstring(blob)
            changed = expose_sequence_history(root)
            if changed:
                replacements[name] = xml(root)
                changes[name] = changed
    if not changes:
        raise ValueError('No missing sequence history registrations found')
    output.mkdir(parents=True)
    target = output / source.name
    rewrite(source, target, replacements)
    report = dict(source=str(source), source_sha256=digest(source),
                  target=str(target), target_sha256=digest(target), changes=changes)
    (output / 'report.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(build(args.source, args.output), indent=2))
