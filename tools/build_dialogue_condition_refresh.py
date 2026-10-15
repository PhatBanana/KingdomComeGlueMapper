"""Refresh boolean literals in imported Skald predicates, preserving other assets."""
import argparse
import json
from pathlib import Path
import xml.etree.ElementTree as ET
import zipfile

from build_horse_trader_test import digest, rewrite
from campaign_dialogue_conditions import normalize_boolean_literals
from upgrade_map import read, xml


def refresh(blob):
    root = ET.fromstring(blob)
    skald = root.find('Skald')
    if skald is None or not any(
            d.get('Name', '').startswith('topic_') for d in skald.iter('Decision')):
        return blob, 0
    count = 0
    for node in skald.iter():
        for key in ('EntryCondition', 'Condition'):
            if key not in node.attrib:
                continue
            before = node.get(key)
            after = normalize_boolean_literals(before)
            if after != before:
                node.set(key, after)
                count += 1
    return (xml(root) if count else blob), count


def build(archive, output):
    output.mkdir(parents=True, exist_ok=False)
    changes, counts = {}, {}
    with zipfile.ZipFile(archive) as pak:
        for name in pak.namelist():
            if not name.startswith('Quests/') or not name.endswith('.xml'):
                continue
            blob, count = refresh(read(pak, name))
            if count:
                changes[name], counts[name] = blob, count
    if not changes:
        raise ValueError('No imported predicates require refresh')
    target = output / archive.name
    rewrite(archive, target, changes)
    with zipfile.ZipFile(target) as pak:
        if pak.testzip():
            raise ValueError('Package CRC validation failed')
    report = dict(source_archive=str(archive), before_sha256=digest(archive),
                  package_sha256=digest(target), conditions=counts, runtime_verified=False)
    (output / 'report.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--archive', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(build(args.archive, args.output), indent=2))
