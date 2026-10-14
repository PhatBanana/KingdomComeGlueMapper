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
from campaign_dialogue_conditions import expand_functions
from quest_import import walk, behavior_path


def reachable_behaviors(model):
    """Walk registered controller callbacks and their actual include/work edges."""
    def path(value):
        normalized = value.replace('\\', '/').lower()
        return normalized if normalized.startswith('libs/ai/') else behavior_path(value).lower()
    registration = model.get('controller_registration') or {}
    entries = registration.get('entry_points', [])
    if not entries:
        return {(document, tree) for document, record in model['behavior_documents'].items()
                for tree in record['trees']}
    edges = defaultdict(set)
    for include in model.get('includes', []):
        if include.get('target') and include.get('name'):
            edges[(include['document'], include['tree'])].add((include['target'], include['name']))
    for call in model.get('work_program_calls', []):
        for candidate in call.get('candidates', []):
            if candidate.get('file') and candidate.get('tree'):
                edges[(call['document'], call['tree'])].add((path(candidate['file']), candidate['tree']))
    queue = deque((path(e['file']), e['tree']) for e in entries)
    visited = set()
    while queue:
        identity = queue.popleft()
        if identity in visited: continue
        visited.add(identity)
        queue.extend(edges[identity] - visited)
    return visited


def discover(tables, quest_id, quest_name, behavior_model=None):
    topics = unique_index(tables['topic'], 'topic_id')
    sequences = unique_index(tables['sequence'], 'sequence_id')
    predecessors, membership, reasons = defaultdict(set), defaultdict(set), defaultdict(list)
    unresolved, inactive = [], []
    functions = {r['function_name']: r['expression'] for r in
                 unique_index(tables.get('dialogue_functions', []), 'function_name').values()}
    dependencies = defaultdict(set)
    sequence_references = []
    for row in tables['topic2sequence']:
        tid, sid = row['topic_id'], row['sequence_id']
        if tid not in topics or sid not in sequences:
            raise ValueError('Unresolved dialogue membership')
        membership[sid].add(tid)
        target = sequences[sid]['next']
        if target != '0':
            if target not in topics: raise ValueError('Unresolved next dialogue topic: ' + target)
            predecessors[target].add(tid)
            dependencies[tid].add(target)
        for field in ('entry_condition', 'npc_entry_condition'):
            source = row.get(field, '')
            try:
                expression = expand_functions(source, functions)
            except ValueError as error:
                unresolved.append(dict(reason=str(error), topic_id=tid, sequence_id=sid, field=field))
                continue
            # Resolve database predicates before looking for literal quest IDs.
            if re.search(r"['\"]" + re.escape(quest_name) + r"['\"]", expression):
                reasons[tid].append(dict(kind=field, sequence_id=sid, source=source, expanded=expression))
            # Ignore quoted text; a string mentioning a function is not a call.
            code = re.sub(r"'(?:[^'\\]|\\.)*'|\"(?:[^\"\\]|\\.)*\"", "''", expression)
            for referenced in re.findall(r'\bIsSeqAvailable\s*\(\s*(\d+)\s*\)', code):
                sequence_references.append((tid, sid, referenced))
    for tid, sid, referenced in sequence_references:
        if referenced not in membership:
            unresolved.append(dict(reason='Sequence availability references missing membership',
                                   topic_id=tid, sequence_id=sid, referenced_sequence=referenced))
        else:
            dependencies[tid].update(membership[referenced])
    if behavior_model:
        reachable = reachable_behaviors(behavior_model)
        labels = defaultdict(list)
        for tid, topic in topics.items():
            if topic.get('label'): labels[topic['label']].append(tid)
        for document, record in behavior_model['behavior_documents'].items():
            for tree, body in record['trees'].items():
                if (document, tree) not in reachable: continue
                for index, node in enumerate(walk(body['root'])):
                    for field, value in node['attributes'].items():
                        # Source message alias(...) and dialog parameter assignments.
                        aliases = re.findall(r'\balias\(\s*([A-Za-z_]\w*)\s*\)', value)
                        aliases += re.findall(r"\.alias\s*=\s*['\"]([A-Za-z_]\w*)['\"]", value)
                        for alias in aliases:
                            site = dict(document=document, tree=tree, preorder_index=index, field=field, alias=alias)
                            if len(labels[alias]) != 1:
                                unresolved.append(dict(reason='Missing or ambiguous behavior dialogue alias', **site))
                            else:
                                reasons[labels[alias][0]].append(dict(kind='behavior_dialogue_alias', **site))
    for effect in tables['sequence2quest_objective']:
        if effect['quest_id'] != str(quest_id): continue
        if effect['sequence_id'] not in membership:
            # Retail tables retain deleted/unlinked sequences. They are not an
            # executable root; preserve evidence instead of activating them.
            inactive.append(dict(reason='Quest callback has no dialogue membership', source=effect))
            continue
        for tid in membership[effect['sequence_id']]:
            reasons[tid].append(dict(kind='objective_callback', source=effect))
    reached, queue = set(reasons), deque(reasons)
    while queue:
        tid = queue.popleft()
        for parent in predecessors[tid] | dependencies[tid]:
            if parent not in reached:
                reached.add(parent); queue.append(parent)
    branches = []
    for branch in tables['v_branch']:
        tid = branch['start_topic']
        if tid not in reached: continue
        if branch.get('is_test') == 'True':
            inactive.append(dict(reason='Source test-only dialogue branch', source=branch))
            continue
        branches.append(dict(source=branch, topic=topics[tid],
                             participants=[r for r in tables['topictorole'] if r['topic_id'] == tid]))
    # Do not request actors that are reachable only from a source test branch.
    production = set()
    queue = deque(b['source']['start_topic'] for b in branches)
    while queue:
        tid = queue.popleft()
        if tid in production: continue
        production.add(tid)
        queue.extend(dependencies[tid] - production)
    reached = production
    unresolved = [r for r in unresolved if 'topic_id' not in r or r['topic_id'] in reached]
    return dict(quest=quest_name, quest_id=str(quest_id), branches=branches,
                reachable_topics=sorted(reached),
                references=[dict(topic_id=tid, sites=sites) for tid, sites in sorted(reasons.items())],
                unresolved=unresolved, inactive_source_records=inactive, runtime_verified=False, executable=False)


def import_participants(closure, dialogue_tables, source_tables, importer, *, eligible_souls=None):
    """Request source NPC souls even when they lack explicit quest asset links."""
    roles = {r['role_id']: r for r in source_tables.get('rpg/role')['rows']}
    meta = {r['metarole_id']: r['metarole_name'] for r in source_tables.get('rpg/metarole')['rows']}
    memberships = defaultdict(set)
    for row in source_tables.get('rpg/soul2role')['rows']:
        memberships[row['role_id']].add(row['soul_id'])
    reached = set(closure['reachable_topics'])
    requested = {}
    participants = [dict(p, dependency_kind='topic_participant') for p in dialogue_tables['topictorole']
                    if p['topic_id'] in reached]
    sequence_topics = defaultdict(set)
    for row in dialogue_tables.get('topic2sequence', []):
        if row['topic_id'] in reached:
            sequence_topics[row['sequence_id']].add(row['topic_id'])
    line_topics = {row['sequence_line_id']: sequence_topics[row['sequence_id']]
                   for row in dialogue_tables.get('sequence_line', []) if row['sequence_id'] in sequence_topics}
    for row in dialogue_tables.get('response', []):
        for topic in sorted(line_topics.get(row['sequence_line_id'], ())):
            participants.append(dict(topic_id=topic, role_id=row['role_id'],
                                     sequence_line_id=row['sequence_line_id'], dependency_kind='response_speaker'))
    for row in dialogue_tables.get('v_dialogue_commands', []):
        for topic in sorted(line_topics.get(row['sequence_line_id'], ())):
            for field in ('who', 'target'):
                if row.get(field) not in (None, '', '0'):
                    participants.append(dict(topic_id=topic, role_id=row[field],
                        sequence_line_id=row['sequence_line_id'], dependency_kind='command_' + field))
    for participant in participants:
        rid = participant['role_id']
        role = roles.get(rid)
        if role is None or role['metarole_id'] not in meta:
            closure['unresolved'].append(dict(reason='Unresolved source dialogue role', role_id=rid))
            continue
        if meta[role['metarole_id']] != 'NPC': continue
        if not memberships[rid]:
            closure['unresolved'].append(dict(reason='NPC dialogue role has no source soul', role_id=rid))
        candidates = memberships[rid]
        if eligible_souls is not None:
            candidates = candidates & set(eligible_souls)
            if not candidates and memberships[rid]:
                closure['unresolved'].append(dict(reason='NPC dialogue role has no actor in selected source profiles',
                    role_id=rid, candidates=sorted(memberships[rid]), site=participant))
        for soul in sorted(candidates):
            target = importer.ensure('souls', soul, dict(kind='dialogue_participant', quest=closure['quest'],
                                     **participant))
            requested[soul] = target
    return requested


def scope_to_quest(closure, dialogue_tables, quest_subchapters):
    """Separate later quest references using source ownership, not name prefixes.

    Unowned branches remain candidates. Explicit behavior calls stay dependencies
    even when their dialogue lives in another source subchapter. This is an
    import boundary, not permission to execute a branch or advance quest state.
    """
    import copy
    result = copy.deepcopy(closure)
    owned = {r['skald_subchapter_id'] for r in quest_subchapters if r['quest_id'] == closure['quest_id']}
    if not owned: raise ValueError('Source quest has no dialogue ownership declaration')
    owners = defaultdict(set)
    for row in dialogue_tables['v_topic2subchapter_id']:
        owners[row['start_topic']].add(row['skald_subchapter_id'])
    called = {r['topic_id'] for r in closure['references']
              if any(s['kind'] == 'behavior_dialogue_alias' for s in r['sites'])}
    selected, external = [], []
    for branch in closure['branches']:
        tid = branch['source']['start_topic']
        if owners[tid] and not owners[tid] & owned and tid not in called:
            external.append(dict(branch=branch, subchapters=sorted(owners[tid]),
                                 reason='Different source quest ownership; reference is not an execution request'))
        else: selected.append(branch)
    # Keep every reachable child/availability dependency of selected roots.
    edges = defaultdict(set)
    seqs = {s['sequence_id']: s for s in dialogue_tables['sequence']}
    membership = defaultdict(set)
    for row in dialogue_tables['topic2sequence']:
        membership[row['sequence_id']].add(row['topic_id'])
    functions = {r['function_name']: r['expression'] for r in dialogue_tables.get('dialogue_functions', [])}
    rows_by_topic = defaultdict(list)
    for row in dialogue_tables['topic2sequence']:
        rows_by_topic[row['topic_id']].append(row)
    reached, queue = set(), deque(b['source']['start_topic'] for b in selected)
    while queue:
        tid = queue.popleft()
        if tid in reached: continue
        reached.add(tid)
        for row in rows_by_topic[tid]:
            nxt = seqs[row['sequence_id']]['next']
            if nxt != '0': edges[tid].add(nxt)
            for key in ('entry_condition', 'npc_entry_condition'):
                expression = expand_functions(row.get(key, ''), functions)
                code = re.sub(r"'(?:[^'\\]|\\.)*'|\"(?:[^\"\\]|\\.)*\"", "''", expression)
                for sid in re.findall(r'\bIsSeqAvailable\s*\(\s*(\d+)\s*\)', code):
                    if sid not in membership:
                        raise ValueError('Scoped dialogue references missing sequence: ' + sid)
                    edges[tid].update(membership[sid])
        queue.extend(edges[tid] - reached)
    result.update(branches=selected, reachable_topics=sorted(reached), excluded_external_branches=external,
                  source_subchapters=sorted(owned))
    return result


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--kcd1', required=True, type=Path)
    p.add_argument('--quest-ir', required=True, type=Path)
    p.add_argument('--output', required=True, type=Path)
    a = p.parse_args()
    if a.output.exists(): raise FileExistsError('Choose a fresh report path')
    model = json.loads(a.quest_ir.read_text(encoding='utf-8'))
    sources = retail_sources(a.kcd1, {n: ('Tables.pak', 'Libs/Tables/text/' + n + '.xml') for n in (*TABLES, 'dialogue_functions')})
    tables = {n: [dict(r.attrib) for r in ET.fromstring(s['data']).findall('./table/rows/row')]
              for n,s in sources.items()}
    report = discover(tables, model['quest_id'], model['quest'], model)
    report['provenance'] = {n:s['candidates'] for n,s in sources.items()}
    a.output.parent.mkdir(parents=True, exist_ok=True)
    a.output.write_text(json.dumps(report, indent=2), encoding='utf-8')
    print(json.dumps(dict(branches=len(report['branches']), report=str(a.output))))


if __name__ == '__main__': main()
