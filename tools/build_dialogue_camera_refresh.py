"""Rebuild installed source-imported conversation cameras without quest edits."""
import argparse
import json
from pathlib import Path
import xml.etree.ElementTree as ET
import zipfile

from build_horse_trader_test import rewrite, digest
from campaign_dialogue import load_many
from campaign_refresh import dialogue_camera_selection
from upgrade_map import read


def build(source, archive, output):
    output.mkdir(parents=True, exist_ok=False)
    selected, aliases = [], set()
    with zipfile.ZipFile(archive) as pak:
        for name in pak.namelist():
            if not name.lower().startswith('quests/') or not name.endswith('.xml'):
                continue
            blob = read(pak, name)
            root = ET.fromstring(blob)
            aliases.update(a.get('Name') for a in root.iter('CameraAsset'))
            skald = root.find('Skald')
            if skald is None or len(skald) != 1:
                continue
            host = skald[0]
            if host.tag not in ('FaderDialog', 'ForcedDialog'):
                continue
            decision = host.find('./Dialogue/Decision')
            if decision is None or not decision.get('Name', '').startswith('topic_'):
                continue
            topic = decision.get('Name')[6:]
            if not topic.isdigit():
                raise ValueError('Invalid imported source topic: ' + topic)
            selected.append((name, blob, topic))
    if not selected:
        raise ValueError('No source-imported cinematic dialogues found')
    models = load_many(source, [(None, topic) for _, _, topic in selected])
    changes, reports = {}, {}
    for (name, blob, _), model in zip(selected, models):
        changes[name], reports[name] = dialogue_camera_selection(blob, model, aliases)
    target = output / archive.name
    rewrite(archive, target, changes)
    report = dict(source_archive=str(archive), before_sha256=digest(archive),
                  package_sha256=digest(target), dialogues=reports, runtime_verified=False)
    (output / 'report.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--archive', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(build(args.source, args.archive, args.output), indent=2))
