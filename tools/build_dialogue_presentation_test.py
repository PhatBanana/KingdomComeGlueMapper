"""Stage source presentation reconciliation for all topic-based imported dialogues."""
import argparse
import json
from pathlib import Path
import re
import xml.etree.ElementTree as ET
import zipfile
from campaign_dialogue import load_many
from campaign_dialogue_presentation import upgrade
from build_horse_trader_test import rewrite, digest
from upgrade_map import read


def build(source, travel, output):
    if output.exists(): raise FileExistsError('Choose a fresh output directory')
    selected = {}
    with zipfile.ZipFile(travel) as archive:
        for name in archive.namelist():
            if not name.startswith('Quests/') or not name.endswith('.xml'): continue
            blob = read(archive, name)
            root = ET.fromstring(blob)
            decision = root.find('.//Dialogue/Decision')
            match = re.fullmatch(r'topic_(\d+)', decision.get('Name', '')) if decision is not None else None
            if match: selected[name] = (match[1], blob)
    models = load_many(source, [(None, topic) for topic, _ in selected.values()])
    replacements, reports = {}, {}
    for (name, (_, blob)), model in zip(selected.items(), models):
        changed, report = upgrade(blob, model)
        reports[name] = report
        if report['added']: replacements[name] = changed
    output.mkdir(parents=True)
    target = output / travel.name
    rewrite(travel, target, replacements)
    report = dict(source_sha256=digest(travel), target_sha256=digest(target), dialogues=reports)
    (output/'report.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    print(json.dumps({name: dict(responses=r['responses'], added=len(r['added']), outside_targeting_scope=len(r['outside_targeting_scope'])) for name,r in reports.items()}, indent=2))


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    for arg in ('source', 'travel', 'output'): p.add_argument('--'+arg, required=True, type=Path)
    a = p.parse_args()
    build(a.source, a.travel, a.output)
