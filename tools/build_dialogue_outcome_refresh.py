"""Refresh source-derived skill outcomes without rebuilding presentation assets."""
import argparse
import json
from pathlib import Path
import xml.etree.ElementTree as ET
import zipfile

from build_horse_trader_test import digest, rewrite
from campaign_dialogue_outcomes import refresh


def build(archive, output, dialogue_models, quest_models):
    models = {m['start_topic']: m for m in dialogue_models}
    changes, reports = {}, {}
    with zipfile.ZipFile(archive) as pak:
        for name in pak.namelist():
            if not name.startswith('Quests/') or not name.endswith('.xml'):
                continue
            blob = pak.read(name)
            root = ET.fromstring(blob)
            decision = root.find('.//Dialogue/Decision')
            if decision is None:
                continue
            topic = decision.get('Name', '').removeprefix('topic_')
            if topic not in models:
                continue
            replacement, aliases = refresh(blob, models[topic], quest_models)
            if aliases:
                changes[name], reports[name] = replacement, aliases
    if not changes:
        raise ValueError('No selected source skill outcomes require refresh')
    output.mkdir(parents=True, exist_ok=False)
    target = output / archive.name
    rewrite(archive, target, changes)
    with zipfile.ZipFile(target) as pak:
        if pak.testzip():
            raise ValueError('Package CRC validation failed')
    report = dict(source_archive=str(archive), before_sha256=digest(archive),
                  package_sha256=digest(target), dialogues=reports, runtime_verified=False)
    (output / 'report.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--archive', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--dialogue-model', type=Path, action='append', required=True)
    parser.add_argument('--quest-model', type=Path, action='append', required=True)
    args = parser.parse_args()
    load = lambda paths: [json.loads(p.read_text(encoding='utf-8')) for p in paths]
    print(json.dumps(build(args.archive, args.output, load(args.dialogue_model), load(args.quest_model)), indent=2))
