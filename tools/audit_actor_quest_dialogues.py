"""Preflight every quest-scoped branch owned by a source actor, without installing.

The supplied closure comes from campaign_quest_dialogues. Actor membership is
read from the installed source tables; labels and topic numbers are not rules.
Successful XML emission does not establish actor, work or quest integration.
"""
import argparse
import hashlib
import json
from pathlib import Path
import zipfile

from campaign_actor_dialogues import actor_branches
from campaign_dependency_adapters import SourceTables
from campaign_dialogue import emit, load_many
from campaign_dialogue_selection import SelectionCompiler, load_contract
from campaign_sources import RetailSourceReader
from upgrade_map import read
from world_item_definitions import native_items, native_item_registry


def audit(source, target, mod, quest_ir, closure_file, soul_name, output):
    if output.exists():
        raise FileExistsError('Choose a fresh audit directory')
    quest = json.loads(quest_ir.read_text(encoding='utf-8'))
    closure = json.loads(closure_file.read_text(encoding='utf-8'))
    if (closure['quest'], closure['quest_id']) != (quest['quest'], quest['quest_id']):
        raise ValueError('Dialogue closure belongs to a different quest')
    with RetailSourceReader(source) as reader:
        tables = SourceTables(source, reader)
        matches = [r for r in tables.get('rpg/soul')['rows'] if r['soul_name'] == soul_name]
        if len(matches) != 1:
            raise ValueError('Missing or ambiguous source soul')
        soul = matches[0]
        branches = actor_branches(closure, tables.get('rpg/soul2role')['rows'], [soul['soul_id']])
    item_tables = []
    for pak in sorted((mod / 'Data').glob('*.pak')):
        with zipfile.ZipFile(pak) as archive:
            item_tables.extend(read(archive, n) for n in archive.namelist()
                if n.lower().startswith('libs/tables/item/item__') and n.endswith('.xml'))
    items = native_item_registry(native_items(target, item_tables))
    contract = load_contract(source, target, {})
    contract['preserve_reputation_caps'] = True
    output.mkdir(parents=True)
    report = dict(soul=soul, quest=quest['quest'], branches=[], installed=False,
                  runtime_verified=False, provenance={str(p): hashlib.sha256(p.read_bytes()).hexdigest()
                                                      for p in (quest_ir, closure_file)})
    for branch in branches:
        tid = branch['source']['start_topic']
        row = dict(topic=tid, label=branch['topic']['label'],
                   branch_type=branch['source']['branch_type_id'])
        try:
            model = load_many(source, [(None, tid)])[0]
            (output / ('dialogue-' + tid + '.json')).write_text(json.dumps(model, indent=2), encoding='utf-8')
            row['conditions'] = [dict(sequence=s['source']['sequence_id'], entry=s['entry'],
                effects=s['effects'], script=s['source'].get('script'))
                for t in model['topics'].values() for s in t['sequences']]
            row['sequence_count'] = len(row['conditions'])
            blob, converted = emit(model, 'audit_' + tid, [quest],
                selection_compiler=SelectionCompiler(**contract), registered_items=items,
                kind='Dialog' if row['branch_type'] == '6' else 'FaderDialog')
            (output / ('dialogue-' + tid + '.xml')).write_bytes(blob)
            row.update(emitted=True, conversion=converted)
        except ValueError as error:
            row.update(emitted=False, failure=str(error))
        report['branches'].append(row)
        print(tid + ': ' + row.get('failure', 'XML emitted; integration unverified'), flush=True)
    (output / 'report.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('source', 'target', 'mod', 'quest-ir', 'closure', 'output'):
        parser.add_argument('--' + name, type=Path, required=True)
    parser.add_argument('--soul-name', required=True)
    args = parser.parse_args()
    audit(args.source, args.target, args.mod, args.quest_ir, args.closure, args.soul_name, args.output)
