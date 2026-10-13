"""Discover named and unnamed retail conversation branches touching a quest.

Follow original sequence membership and next-topic edges backwards from quest
callbacks and conditions. Labels are not required and shared branches retain
their original identities. This inventory is evidence, not an installable quest.
"""
import argparse
from collections import defaultdict, deque
import json
from pathlib import Path
import re
import xml.etree.ElementTree as ET

from campaign_dialogue import TABLES, unique_index
from campaign_sources import retail_sources


def discover(tables, quest_id, quest_name):
    topics = unique_index(tables['topic'], 'topic_id')
    sequences = unique_index(tables['sequence'], 'sequence_id')
    predecessors, membership, reasons = defaultdict(set), defaultdict(set), defaultdict(list)
    unresolved = []
    for row in tables['topic2sequence']:
        tid, sid = row['topic_id'], row['sequence_id']
        if tid not in topics or sid not in sequences:
            raise ValueError('Unresolved dialogue membership')
        membership[sid].add(tid)
        target = sequences[sid]['next']
        if target != '0':
            if target not in topics: raise ValueError('Unresolved next dialogue topic: ' + target)
            predecessors[target].add(tid)
        # Only literal quest references count; a similar label is not evidence.
        if re.search(r"['\"]" + re.escape(quest_name) + r"['\"]", row.get('entry_condition', '')):
            reasons[tid].append(dict(kind='entry_condition', sequence_id=sid, source=row['entry_condition']))
        if re.search(r"['\"]" + re.escape(quest_name) + r"['\"]", row.get('npc_entry_condition', '')):
            reasons[tid].append(dict(kind='npc_entry_condition', sequence_id=sid, source=row['npc_entry_condition']))
    for effect in tables['sequence2quest_objective']:
        if effect['quest_id'] != str(quest_id): continue
        if effect['sequence_id'] not in membership:
            unresolved.append(dict(reason='Quest callback has no dialogue membership', source=effect))
            continue
        for tid in membership[effect['sequence_id']]:
            reasons[tid].append(dict(kind='objective_callback', source=effect))
    reached, queue = set(reasons), deque(reasons)
    while queue:
        for parent in predecessors[queue.popleft()]:
            if parent not in reached:
                reached.add(parent); queue.append(parent)
    branches = []
    for branch in tables['v_branch']:
        tid = branch['start_topic']
        if tid not in reached: continue
        branches.append(dict(source=branch, topic=topics[tid],
                             participants=[r for r in tables['topictorole'] if r['topic_id'] == tid]))
    return dict(quest=quest_name, quest_id=str(quest_id), branches=branches,
                references=[dict(topic_id=tid, sites=sites) for tid, sites in sorted(reasons.items())],
                unresolved=unresolved, runtime_verified=False, executable=False)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--kcd1', required=True, type=Path)
    p.add_argument('--quest-ir', required=True, type=Path)
    p.add_argument('--output', required=True, type=Path)
    a = p.parse_args()
    if a.output.exists(): raise FileExistsError('Choose a fresh report path')
    model = json.loads(a.quest_ir.read_text(encoding='utf-8'))
    sources = retail_sources(a.kcd1, {n: ('Tables.pak', 'Libs/Tables/text/' + n + '.xml') for n in TABLES})
    tables = {n: [dict(r.attrib) for r in ET.fromstring(s['data']).findall('./table/rows/row')]
              for n,s in sources.items()}
    report = discover(tables, model['quest_id'], model['quest'])
    report['provenance'] = {n:s['candidates'] for n,s in sources.items()}
    a.output.parent.mkdir(parents=True, exist_ok=True)
    a.output.write_text(json.dumps(report, indent=2), encoding='utf-8')
    print(json.dumps(dict(branches=len(report['branches']), report=str(a.output))))


if __name__ == '__main__': main()
