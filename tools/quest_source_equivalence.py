"""Layer 1: compare a converted quest with its KCD1 source, record by record.

Works on any quest that went through campaign_quest_graph.emit_project and
campaign_quest_lowerings.lower. The expectation is derived here from the source
tables alone, not read back from the converter's own report, and is then
compared with the emitted Skald XML. Each source record must end in exactly one
of two places: a native mechanism of the expected kind, or a residue record in
the quest's `unsupported` list. Anything else is a FAIL:

    a record with neither (silently dropped)
    a record with both (converted and still reported)
    a native completion, start or cancel edge with no source record behind it
    a timer whose duration or clock differs from the source
    an asset alias, item class or edge source that does not resolve

Checked categories: objectives (count, ids, order, ports, journal visibility),
transitions (per destination: predecessors and join), quest end, completion
(per objective), tracked assets, rewards (per source row), references.

This is a static comparison. It proves the conversion says what the source
says; it does not prove the game runs it.

  python tools/quest_source_equivalence.py --kcd1 <dir> --kcd2 <dir> --quest q_skalitz
      [--with q_other ...] [--golden <file>] [--write-golden] [--output report.json]
"""
import argparse
from collections import Counter, defaultdict
import hashlib
import json
from pathlib import Path
import re
import xml.etree.ElementTree as ET

from campaign_objective_conditions import counted_asset
from campaign_quest_graph import objective_identifier

UNSET = ('', '-1', None)
TIMEOUT = re.compile(r'\s*(\d+(?:\.\d+)?)\s*(ms|s|m|h|d)\s*(?:#(GT|WT))?\s*')
CLOCK = dict(GT='GameTime', WT='WorldTime')
PROGRESS = ('Started', 'Completed', 'Failed', 'Canceled', 'Unchanged')
VERBS = dict(start='SetStarted', complete='SetCompleted', fail='SetFailed', cancel='SetCanceled')
# Native completion mechanisms, by the node that feeds SetCompleted.
MECHANISMS = (
    (re.compile(r'complete_(\d+)_if_started\.True'), 'emitter_timer'),
    (re.compile(r'lowered_policy_(\d+)_if_started\.True'), 'policy_timer'),
    (re.compile(r'lowered_track_(\d+)_complete\.True'), 'tracking'),
    (re.compile(r'tracked_items_(\d+)_complete\.True'), 'quest_items'),
    (re.compile(r'source_condition_(\d+)_apply_\d+_gate\.True'), 'condition'),
)
ALLOWED = dict(external=set(), never=set(), constant={'emitter_timer'},
               timed={'emitter_timer', 'policy_timer'}, tracked_auto={'tracking', 'quest_items'},
               tracked_manual=set(), expression={'condition', 'linked_condition'}, unestablished=set())
# Classes whose source record asks for something; an empty native side then
# needs a residue record. 'external' and 'never' ask for nothing.
DEMANDING = {'constant', 'timed', 'tracked_auto', 'tracked_manual', 'expression', 'unestablished'}


def completion_class(row, tracked_rows):
    """How the source says this objective completes, from its table row alone."""
    condition = (row.get('condition') or '').strip()
    timeout, expiration = row.get('autocomplete_timeout_str'), row.get('expiration_timeout_str')
    counted = [t for t in tracked_rows if counted_asset(t)]
    markers = [t for t in tracked_rows if not counted_asset(t)]
    record = dict(condition=condition, autocomplete=timeout, expiration=expiration,
                  counted=len(counted), markers=len(markers))
    if expiration not in UNSET or row.get('time', '0') not in ('', '0'):
        return dict(record, kind='unestablished', why='expiration timeout')
    if counted:
        if timeout not in UNSET:
            return dict(record, kind='unestablished', why='timeout on a tracked objective')
        if condition == '1': return dict(record, kind='tracked_auto')
        if condition in ('', '0'): return dict(record, kind='tracked_manual')
        return dict(record, kind='unestablished', why='expression on a tracked objective')
    if timeout not in UNSET:
        match = TIMEOUT.fullmatch(timeout)
        if condition != '1' or match is None or match[3] is None:
            return dict(record, kind='unestablished', why='timeout without a constant condition or a named clock')
        return dict(record, kind='timed', duration=match[1] + match[2], clock=CLOCK[match[3]])
    if condition == '':
        return dict(record, kind='external')
    if condition == '0':
        return dict(record, kind='never')
    if condition == '1':
        # A constant-true objective that only shows a marker: whether the
        # source completes it on start is not established (tracking adapter).
        return dict(record, kind='unestablished', why='constant condition with a marker') if markers \
            else dict(record, kind='constant')
    return dict(record, kind='expression')


def expected(model):
    """The source-side statement the checker compares against."""
    tables = model['tables']
    rows = sorted(tables['quest_objective']['rows'], key=lambda r: int(r['objective_id']))
    tracked = defaultdict(list)
    for row in tables.get('quest_tracked_asset', {}).get('rows', []):
        tracked[row['objective_id']].append(row)
    begin = [i for i, n in model['graph']['nodes'].items() if n['attributes'].get('Class') == 'Quest:Begin']
    end = [i for i, n in model['graph']['nodes'].items() if n['attributes'].get('Class') == 'Quest:End']
    incoming = defaultdict(list)
    for r in tables['quest_transition']['rows']:
        if r['enabled'] == 'True':
            incoming[r['to_objective_id']].append(r['from_objective_id'])
    by_id = {r['objective_id']: r for r in rows}
    joins = {}
    for target, predecessors in incoming.items():
        exclusive = [p for p in predecessors if p not in begin and by_id[p]['is_exclusive'] == 'True']
        joins[target] = dict(predecessors=sorted(predecessors, key=int),
            join='mixed' if exclusive and len(exclusive) != len(predecessors) else 'any' if exclusive else 'all')
    rewards = defaultdict(list)
    for table, payload in tables.items():
        if table.startswith('quest_reward'):
            for row in payload['rows']:
                rewards[row.get('objective_id')].append(dict(table=table, row=row))
    return dict(quest=model['quest'], begin=begin[0] if len(begin) == 1 else None,
                end=end[0] if len(end) == 1 else None,
                objectives=[dict(id=r['objective_id'], name=r['objective_name'], hidden=r['is_hidden'] == 'True',
                                 exclusive=r['is_exclusive'] == 'True',
                                 completion=completion_class(r, tracked[r['objective_id']])) for r in rows],
                joins=joins, rewards={k: v for k, v in rewards.items()})


class Checker:
    def __init__(self, model, blob, quest_report, bindings, project_blob=None):
        self.model, self.report, self.bindings = model, quest_report, bindings or {}
        self.project = ET.fromstring(project_blob) if project_blob else None
        self.expected = expected(model)
        self.root = ET.fromstring(blob)
        self.quest = self.root.find('./Skald/Quest')
        self.nodes = self.quest.find('Nodes') if self.quest is not None else None
        self.checks = []
        self.unsupported = defaultdict(list)
        for record in quest_report.get('unsupported', []):
            self.unsupported[(record['kind'], record.get('objective') or record.get('table'))].append(record)

    def add(self, category, item, status, detail=''):
        self.checks.append(dict(category=category, item=str(item), status=status, detail=detail))

    def verdict(self, category, item, problems, residue=None):
        if problems: self.add(category, item, 'FAIL', '; '.join(problems))
        elif residue: self.add(category, item, 'RESIDUE', residue)
        else: self.add(category, item, 'PASS')

    def node(self, name):
        found = [n for n in self.nodes if n.get('Name') == name]
        return found[0] if len(found) == 1 else None

    def sources(self, node, port):
        return sorted(e.get('From') for e in node.findall('Edge') if e.get('To') == port)

    def check_objectives(self):
        rows = self.expected['objectives']
        states = [n.get('Name')[10:] for n in self.nodes if n.tag == 'State' and re.fullmatch(r'objective_\d+', n.get('Name', ''))]
        self.verdict('objectives', 'count', [] if len(states) == len(rows) else
                     ['source has %d objectives, target has %d' % (len(rows), len(states))])
        self.verdict('objectives', 'ids_and_order', [] if states == [r['id'] for r in rows] else
                     ['objective id sequence differs from the source table'])
        ports = {(p.get('Name'), p.get('Direction'), p.get('Type')) for p in self.quest.find('Ports')}
        journal = self.report.get('journal_visible', True)
        declared = {o.get('Name') for o in self.quest.find('Objectives')} if self.quest.find('Objectives') is not None else set()
        names = Counter(objective_identifier(r['name']) for r in rows)
        for row in rows:
            name, problems = objective_identifier(row['name']), []
            state = self.node('objective_' + row['id'])
            if state is None:
                self.add('objectives', row['name'], 'FAIL', 'no native state'); continue
            if names[name] != 1: problems.append('objective name is not unique after normalisation')
            for verb, target in VERBS.items():
                if (verb + '_' + name, 'In', 'trigger') not in ports or verb + '_' + name not in self.sources(state, target):
                    problems.append('missing input ' + verb)
            for value in PROGRESS:
                if (name + '_' + value, 'Out', 'bool') not in ports: problems.append('missing output ' + value)
            if (name in declared) != (journal and not row['hidden']):
                problems.append('journal visibility differs (source hidden=%s)' % row['hidden'])
            self.verdict('objectives', row['name'], problems)

    def check_transitions(self):
        exp, by_id = self.expected, {r['id']: r for r in self.expected['objectives']}
        mixed = {r.get('objective') for r in self.report.get('unsupported', []) if r['kind'] == 'mixed_exclusive_transition'}
        for row in exp['objectives']:
            state = self.node('objective_' + row['id'])
            if state is None: continue
            started = [s for s in self.sources(state, 'SetStarted') if s != 'start_' + objective_identifier(row['name'])]
            join = exp['joins'].get(row['id'])
            label = 'into ' + row['name']
            if join is None:
                self.verdict('transitions', label, ['native start edge without a source transition: ' + s for s in started])
                continue
            residue = objective_identifier(row['name']) in mixed
            if join['join'] == 'mixed':
                self.verdict('transitions', label, [] if residue and not started else
                             ['mixed exclusive join must be residue and unconverted'], 'mixed exclusive join')
                continue
            problems = ['reported as residue but the join is not mixed'] if residue else []
            if started != ['advance_' + row['id'] + '.True']:
                problems.append('expected exactly advance_%s, found %s' % (row['id'], started))
            gate = self.node('advance_' + row['id'])
            if gate is None:
                self.verdict('transitions', label, problems + ['missing advance gate']); continue
            want = sorted('quest_progress.OnActive' if p == exp['begin'] else 'objective_' + p + '.OnCompleted'
                          for p in join['predecessors'])
            if self.sources(gate, 'Exec') != want:
                problems.append('predecessor events differ from the source transitions')
            problems += self.join_problems('ready_' + row['id'], join)
            self.verdict('transitions', label, problems)
        for row in exp['objectives']:
            state = self.node('objective_' + row['id'])
            if state is None: continue
            extra = [s for s in self.sources(state, 'SetCanceled') if s != 'cancel_' + objective_identifier(row['name'])]
            allowed = {'exclusive_cancel_%s_%s.True' % (a, row['id'])
                       for join in exp['joins'].values() if join['join'] == 'any' and row['id'] in join['predecessors']
                       for a in join['predecessors'] if a != row['id']}
            if extra or allowed:
                self.verdict('transitions', 'exclusive cancel of ' + row['name'],
                             [] if set(extra) == allowed else ['exclusive cancellations differ: %s vs %s' % (sorted(extra), sorted(allowed))])

    def join_problems(self, ready, join):
        """The emitted prerequisite must fold exactly the source predecessors."""
        fold = [n for n in self.nodes if re.fullmatch(re.escape(ready) + r'_predecessors_\d+', n.get('Name', ''))]
        terms = set()
        for node in fold:
            for port in ('A', 'B'):
                terms.update(s for s in self.sources(node, port) if not s.startswith(ready + '_predecessors_'))
        want = {'quest_progress.Active' if p == self.expected['begin'] else 'objective_' + p + '.Completed'
                for p in join['predecessors']}
        problems = []
        if len(join['predecessors']) > 1:
            if terms != want: problems.append('join terms differ from the source predecessors')
            methods = {n.get('MethodName').rsplit('::', 1)[1] for n in fold}
            if methods != {'Or' if join['join'] == 'any' else 'And'}:
                problems.append('join is %s in the source, %s in the target' % (join['join'], sorted(methods)))
        return problems

    def check_quest_end(self):
        exp = self.expected
        join = exp['joins'].get(exp['end']) if exp['end'] else None
        progress = self.node('quest_progress')
        done = [s for s in self.sources(progress, 'SetDone') if s != 'complete'] if progress is not None else []
        mixed = any(r['kind'] == 'mixed_exclusive_transition' and r.get('objective') == 'Quest:End'
                    for r in self.report.get('unsupported', []))
        if join is None:
            self.verdict('quest_end', 'Quest:End', ['native quest end without a source transition'] if done else [],
                         None if not done else None)
            return
        if join['join'] == 'mixed':
            self.verdict('quest_end', 'Quest:End', [] if mixed and not done else ['mixed join must be residue'],
                         'mixed exclusive join')
            return
        problems = []
        if done != ['advance_' + exp['end'] + '.True']: problems.append('quest end is not driven by its source join')
        timer = self.node('quest_end_' + exp['end'] + '_queued')
        want = sorted('quest_progress.OnActive' if p == exp['begin'] else 'objective_' + p + '.OnCompleted'
                      for p in join['predecessors'])
        if timer is None or self.sources(timer, 'SetRunning') != want:
            problems.append('quest end predecessors differ from the source transitions')
        problems += self.join_problems('ready_' + exp['end'], join)
        self.verdict('quest_end', 'Quest:End', problems)

    def mechanisms(self, row):
        state = self.node('objective_' + row['id'])
        found, unknown = set(), []
        for source in self.sources(state, 'SetCompleted'):
            if source == 'complete_' + objective_identifier(row['name']): continue
            for pattern, kind in MECHANISMS:
                match = pattern.fullmatch(source)
                if match and match[1] == row['id']:
                    found.add(kind); break
            else:
                unknown.append(source)
        # A cross-quest condition is wired in the project file and drives this
        # quest's own complete_<objective> input, so the quest file shows nothing.
        if any(c.get('objective') == row['name'] for c in self.report.get('converted_linked_conditions', [])):
            stem = 'linked_condition_' + hashlib.sha256((self.model['quest'] + ':' + row['id']).encode()).hexdigest()[:20]
            if self.project is None or self.project.find(".//Nodes/Timer[@Name='" + stem + "']") is not None:
                found.add('linked_condition')
            else:
                unknown.append('reported linked condition is missing from the project: ' + stem)
        return found, unknown

    def check_completion(self):
        for row in self.expected['objectives']:
            if self.node('objective_' + row['id']) is None: continue
            completion, name = row['completion'], objective_identifier(row['name'])
            found, unknown = self.mechanisms(row)
            policy, tracking = self.unsupported.get(('completion_policy', name), []), self.unsupported.get(('tracked_completion', name), [])
            problems = ['completion edge with no source record: ' + s for s in unknown]
            kind = completion['kind']
            inert = False
            if kind == 'never' and found == {'condition'}:
                # The emitter wires a constant-false source condition as
                # `Started AND false`. That gate cannot fire, so it is the same
                # statement as the source's '0'. Anything else is a mismatch.
                gate = self.node('source_condition_' + row['id'] + '_apply_0_condition')
                constants = [c.get('Value') for c in gate.findall('Constant')] if gate is not None else []
                if gate is not None and gate.get('MethodName') == 'math::boolean::And' and constants == ['false']:
                    found, inert = set(), True
            if found - ALLOWED[kind]:
                problems.append('%s objective has native %s' % (kind, sorted(found - ALLOWED[kind])))
            if len(found) > 1: problems.append('more than one native completion: ' + str(sorted(found)))
            if found and (policy or (tracking and kind != 'tracked_manual')):
                problems.append('converted and still reported as residue')
            residue = None
            if not found and kind in DEMANDING:
                predicate = self.quest.find("Ports/Port[@Name='" + name + "_TrackedCompleted']") is not None
                if kind == 'tracked_manual' and predicate and not tracking:
                    pass                                   # manual completion keeps its source path; predicate exposed
                elif policy or tracking:
                    residue = completion.get('why') or kind
                else:
                    problems.append('%s completion has neither a native mechanism nor a residue record' % kind)
            if kind == 'tracked_manual' and found:
                problems.append('manual tracked objective must not complete by itself')
            if kind in ('constant', 'timed') and found and not problems:
                problems += self.timer_problems(row, completion, found)
            if kind in ('tracked_auto', 'tracked_manual') and not residue and 'quest_items' not in found:
                watched = {n.get('Name').split('_')[3] for n in self.nodes
                           if re.fullmatch(r'lowered_track_' + row['id'] + r'_\d+_\w+', n.get('Name', ''))}
                if len(watched) != completion['counted']:
                    problems.append('source tracks %d counted assets, target watches %d' % (completion['counted'], len(watched)))
            self.verdict('completion', row['name'] + ' [' + kind + (', inert constant-false gate' if inert else '') + ']',
                         problems, residue)

    def timer_problems(self, row, completion, found):
        name = 'complete_%s_queued' if 'emitter_timer' in found else 'lowered_policy_%s_timer'
        timer = self.node(name % row['id'])
        if timer is None: return ['missing completion timer']
        values = {c.get('Name'): c.get('Value') for c in timer.findall('Constant')}
        want = (completion.get('duration', '0s'), completion.get('clock', 'GameTime'))
        return [] if (values.get('Duration'), values.get('TimeType')) == want else \
            ['timer is %s %s, source says %s %s' % (values.get('Duration'), values.get('TimeType'), *want)]

    def check_rewards(self):
        lowered = self.report.get('lowerings', {}).get('rewards', {})
        omitted = Counter((r['table'], json.dumps(r['row'], sort_keys=True)) for r in lowered.get('omitted', []))
        residue = Counter()
        for record in self.report.get('unsupported', []):
            if record['kind'] == 'rewards':
                for row in record['rows']: residue[(record['table'], json.dumps(row, sort_keys=True))] += 1
        native = defaultdict(int)
        for node in self.nodes:
            match = re.fullmatch(r'lowered_reward_(\d+)(?:_deferred)?', node.get('Name', ''))
            if match and node.tag == 'AddReward':
                native[match[1]] += len(node.find('Rewards') if node.find('Rewards') is not None else [])
        for oid, rows in sorted(self.expected['rewards'].items(), key=lambda p: str(p[0])):
            left = sum(1 for r in rows if residue[(r['table'], json.dumps(r['row'], sort_keys=True))])
            skipped = sum(1 for r in rows if omitted[(r['table'], json.dumps(r['row'], sort_keys=True))])
            want = len(rows) - left - skipped
            label = 'objective ' + str(oid) + ' (%d rows)' % len(rows)
            problems = [] if native.get(oid, 0) == want else \
                ['%d source rows, %d residue, %d omitted by policy, but %d native rewards' % (len(rows), left, skipped, native.get(oid, 0))]
            self.verdict('rewards', label, problems,
                         ('%d of %d rows are residue' % (left, len(rows))) if left else
                         ('%d rows omitted by policy' % skipped if skipped and not want else None))
        for oid in sorted(set(native) - {str(k) for k in self.expected['rewards']}):
            self.add('rewards', 'objective ' + oid, 'FAIL', 'native reward without a source row')

    def check_references(self):
        b = self.bindings
        aliases = {b.get('player_asset'), *b.get('soul_assets', {}).values(),
                   *(r.get('alias') for r in b.get('place_assets', {}).values())} - {None}
        items = {str(i).lower() for i in b.get('registered_items', ())}
        names = {n.get('Name') for n in self.nodes}
        inputs = {p.get('Name') for p in self.quest.find('Ports') if p.get('Direction') == 'In'}
        if len(names) != len(self.nodes):
            self.add('references', 'node names', 'FAIL', 'duplicate node name')
        for node in self.nodes:
            for asset in node.findall('Asset'):
                self.verdict('references', node.get('Name') + ' asset ' + asset.get('Alias', ''),
                             [] if asset.get('Alias') in aliases else ['asset alias is not registered by the bindings'])
            for constant in node.findall('Constant'):
                if constant.get('Name') == 'ItemClass':
                    self.verdict('references', node.get('Name') + ' item ' + constant.get('Value', ''),
                                 [] if constant.get('Value', '').lower() in items else ['item class is not registered'])
        dangling = sorted({e.get('From') for n in self.nodes for e in n.findall('Edge')
                           if e.get('From').split('.', 1)[0] not in names and e.get('From') not in inputs})
        self.verdict('references', 'edge sources', ['dangling edge source: ' + d for d in dangling[:10]])

    def run(self):
        if self.quest is None or self.quest.get('Name') != self.model['quest'] or self.nodes is None:
            self.add('objectives', 'quest identity', 'FAIL', 'target is not this quest')
        else:
            for step in (self.check_objectives, self.check_transitions, self.check_quest_end,
                         self.check_completion, self.check_rewards, self.check_references):
                step()
        return result(self.model['quest'], self.checks)


def result(quest, checks):
    by_category = defaultdict(Counter)
    for check in checks: by_category[check['category']][check['status']] += 1
    total = Counter(c['status'] for c in checks)
    summary = lambda c: dict(checked=sum(c.values()), passed=c['PASS'], failed=c['FAIL'], residue=c['RESIDUE'])
    return dict(schema=1, layer='source_equivalence', quest=quest, verdict='FAIL' if total['FAIL'] else 'PASS',
                summary=summary(total), categories={k: summary(v) for k, v in sorted(by_category.items())},
                failures=[c for c in checks if c['status'] == 'FAIL'],
                residue=[c for c in checks if c['status'] == 'RESIDUE'], checks=checks, runtime_verified=False)


def check(model, blob, quest_report, bindings=None, project_blob=None):
    """Compare one converted quest with its source model. Never raises on a mismatch."""
    return Checker(model, blob, quest_report, bindings, project_blob).run()


def check_project(files, report, models, bindings=None):
    by_name = {m['quest']: m for m in models}
    return [check(by_name[q['quest']], files[report['project'] + '/' + q['quest'] + '.xml'], q, bindings,
                  files.get(report['project'] + '.xml')) for q in report['quests']]


def main():
    from quest_conversion_ledger import convert, golden, write_json
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('--kcd1', type=Path, required=True)
    p.add_argument('--kcd2', type=Path, required=True)
    p.add_argument('--quest', nargs='+', required=True)
    p.add_argument('--with', dest='with_quests', nargs='*', default=[])
    p.add_argument('--golden', type=Path, help='Golden fixture to compare with (one quest)')
    p.add_argument('--write-golden', action='store_true')
    p.add_argument('--output', type=Path)
    a = p.parse_args()
    run = convert(a.kcd1, a.kcd2, a.quest, a.with_quests)
    failed = False
    for ledger in run['ledgers']:
        if ledger['quest'] not in a.quest: continue
        layer = ledger['layers']['source_equivalence']
        print(json.dumps(dict(quest=ledger['quest'], verdict=layer['verdict'], **layer['summary'],
                              residue_before=ledger['counts']['before_total'], residue_after=ledger['counts']['after_total'])))
        for failure in layer['failures']:
            print('  FAIL', failure['category'], failure['item'], '-', failure['detail'])
        failed |= layer['verdict'] != 'PASS'
        if a.golden:
            if len(a.quest) != 1: raise SystemExit('--golden takes exactly one --quest')
            current = golden(ledger, run['files'][run['project'] + '/' + ledger['quest'] + '.xml'])
            if a.write_golden:
                write_json(a.golden, current)
            elif json.loads(a.golden.read_text(encoding='utf-8')) != current:
                print('  FAIL golden fixture differs:', a.golden); failed = True
    if a.output:
        write_json(a.output, run['ledgers'])
    return 1 if failed else 0


if __name__ == '__main__': raise SystemExit(main())
