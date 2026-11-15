"""Converter C2 driver: convert one quest's controller and keep a blocker ledger.

Developer tooling; never imported by Setup. It imports the quest's IR, applies
campaign_controller_contracts.prepare, runs the production behaviour compiler
with the audit's dependency adapters (AI types, enums, mailboxes, link types)
and reports, for the quest's own controller document:

    trees      emitted / blocked, with every blocked site and reason
    blockers   one row per reason: family, sites, trees, status
    layer 1    shape equivalence of every emitted tree with its source tree as
               prepared; rewritten operations are counted, and each rewrite
               rule is checked against its source form by the unit tests

A tree is emitted only when every site in it, and every tree it includes,
converted. No branch is omitted. World, item, buff and profile dependencies
need the full campaign importer; their reasons are marked `needs_importer`.
An operation with no native equivalent is marked `inexpressible`. The
hand-written notes of an existing blocker file are kept on regeneration.

  python tools/quest_controller_conversion.py --kcd1 <dir> --kcd2 <dir> --quest q_skalitz
      --work <fresh dir> [--with q_other ...] [--blockers <file.md>] [--golden <file>] [--write-golden]
"""
import argparse
from collections import Counter, defaultdict
import json
from pathlib import Path
import re
import xml.etree.ElementTree as ET
import zipfile

import campaign_controller_contracts

FAMILIES = (
    (r'^Inexpressible', 'op_inexpressible'), (r'^Native operation (lacks|has no|lives)', 'op_partial'),
    (r'[Dd]aycycle', 'daycycle_lifecycle'), (r'Lua|script requires', 'lua'),
    (r'operation needs an adapter', 'op_no_contract'), (r'attributes', 'op_attributes'),
    (r'buff', 'buff'), (r'index requires type|variable type|variable reference|variable has no|array index', 'typed_variables'),
    (r'link', 'link_types'), (r'profile', 'profile'), (r'mailbox|message_type|[Mm]onologue|request fields', 'message_type'),
    (r'combat|faction', 'combat_dispatch'), (r'item', 'items'), (r'[Qq]uest|[Oo]bjective|Missing-branch', 'quest_state'),
    (r'animation', 'animation'), (r'enum', 'enum'),
)
STATUS = dict(buff='needs_importer', items='needs_importer', profile='needs_importer',
              op_inexpressible='inexpressible')
# Source operations the compiler replaces with another native shape.
LOWERED = {'SetQuest', 'SetQuestObjective', 'QuestCondition', 'QuestObjectiveCondition', 'QuestObjectiveGate',
           'EnableProfile', 'ExecuteLua', 'PlayAnimation', 'SmartAreaBehaviorTag', 'SmartObjectBehaviorTag',
           'MeleeGuardAutomation', 'MeleeDefenseAutomation', 'MeleeOffenseAutomation', 'WeaponAutomation'}


NOTES = '## Notes'


def walk(node):
    yield node
    for child in node['children']: yield from walk(child)


def family(reason):
    for pattern, name in FAMILIES:
        if re.search(pattern, reason): return name
    return 'other'


def import_model(kcd1, quest, reader):
    from campaign_ai_registration import controller_definition
    from campaign_dependency_adapters import SourceTables
    from campaign_quest_graph import validate_model
    from quest_import import import_quest
    tables = SourceTables(Path(kcd1), reader)
    definition = controller_definition(tables, tables.row('quest/quest', 'quest_name', quest))
    bootstrap = sorted({entry['file'] for entry in (definition or {}).get('entry_points', [])})
    model, _ = import_quest(Path(kcd1), quest, bootstrap=bootstrap, source_reader=reader, require_behavior=False)
    model['controller_registration'] = definition
    validate_model(model)
    return model, tables


def shape(source, emitted, path, problems):
    """Emitted trees keep the source structure: same child count at every node."""
    op = source['op']
    if emitted.tag != op and op not in LOWERED and not emitted.tag.startswith('SendAIConceptSignal_'):
        problems.append(path + ': ' + op + ' became ' + emitted.tag)
    if op in LOWERED and op not in ('QuestCondition', 'QuestObjectiveCondition', 'QuestObjectiveGate'):
        return 1
    children = list(emitted)
    if len(children) != len(source['children']):
        problems.append('%s: %s has %d children, target %d' % (path, op, len(source['children']), len(children)))
        return 1
    return 1 + sum(shape(s, e, path + '/' + str(i), problems) for i, (s, e) in enumerate(zip(source['children'], children)))


def convert(kcd1, kcd2, quest, work, with_quests=()):
    from campaign_ai_registration import MailboxAdapter, NativeAIRegistry
    from campaign_ai_types import AIEnumAdapter, AIStructureAdapter, AITypeSource
    from campaign_behavior import convert_behaviors, native_catalog
    from campaign_dependencies import DependencyImporter
    from campaign_link_types import LinkTypeAdapter
    from campaign_profiles import STREAMING_SOURCE
    from campaign_sources import RetailSourceReader, retail_sources
    from upgrade_map import read
    kcd1, kcd2, work = Path(kcd1), Path(kcd2), Path(work)
    if work.exists(): raise ValueError('Choose a fresh work directory')
    campaign_controller_contracts.register()
    catalog = native_catalog(kcd2)
    types = AITypeSource.load(kcd1, retail_sources, 'C2', work / 'types')
    with RetailSourceReader(kcd1) as reader, zipfile.ZipFile(kcd2 / 'Data/Scripts.pak') as scripts:
        model, tables = import_model(kcd1, quest, reader)
        # Quests compiled alongside so cross-quest state operations can bind.
        others = [import_model(kcd1, name, reader)[0] for name in with_quests]
        models, prepared = campaign_controller_contracts.prepare([model, *others])
        links = LinkTypeAdapter.load(kcd1, kcd2, reader, 'C2', work / 'links')
        # Only the tags no definition declares are added (and reported).
        prepared['implicit_links'] = {identity: row for identity, row in prepared['implicit_links'].items()
                                      if identity not in links.source}
        links.source.update({identity: dict(row) for identity, row in prepared['implicit_links'].items()})
        importer = DependencyImporter(dict(
            ai_types=AIStructureAdapter(types, catalog['variable_types']), ai_enums=AIEnumAdapter(types),
            mailboxes=MailboxAdapter(tables, NativeAIRegistry.load(kcd2, 'C2')), link_types=links))
        behaviors, bridges, conversion = convert_behaviors(models, 'C2', catalog, importer=importer,
                                                           profile_streaming=read(scripts, STREAMING_SOURCE))
    return dict(model=models[0], prepared=prepared, behaviors=behaviors, bridges=bridges, conversion=conversion)


def ledger(run):
    model, conversion = run['model'], run['conversion']
    own = 'libs/ai/quests/' + model['quest'].lower() + '.xml'
    records = {(t['document'], t['tree']): t for t in conversion['trees']}
    emitted = {}
    for blob in run['behaviors'].values():
        root = ET.fromstring(blob)
        for tree in ([root] if root.tag == 'BehaviorTree' else root.iter('BehaviorTree')):
            emitted.setdefault(tree.get('name'), []).append(tree)
    trees, blockers = [], defaultdict(lambda: dict(sites=0, trees=set()))
    lua = defaultdict(lambda: dict(sites=0, trees=set()))
    checked = passed = nodes = rewritten = 0
    failures = []
    for name, source in model['behavior_documents'][own]['trees'].items():
        record = records[(own, name)]
        reasons = Counter(i['reason'] for i in record['unresolved'])
        for reason, count in reasons.items():
            blockers[reason]['sites'] += count; blockers[reason]['trees'].add(name)
        for item in record['unresolved']:
            site = item.get('site') or {}
            if site.get('operation') in ('ExecuteLua', 'LuaGate', 'LuaWrapper'):
                scripts = [site['arguments'][f] for f in ('code', 'onEnter', 'onExit') if f in site['arguments']]
                calls = sorted({call for script in scripts
                                for call in campaign_controller_contracts.lua_shape(
                                    script[1:-1] if script[:1] == script[-1:] == '"' and len(script) > 1 else script)})
                lua[' '.join(calls)]['sites'] += 1; lua[' '.join(calls)]['trees'].add(name)
        status = 'emitted' if record['native_emitted'] else 'blocked' if reasons else 'blocked_by_include'
        entry = dict(tree=name, status=status, blocked_sites=sum(reasons.values()), reasons=len(reasons))
        if record['native_emitted']:
            checked += 1
            candidates = [t for t in emitted.get(name, []) if t.find('Root') is not None]
            problems = []
            if len(candidates) != 1:
                problems.append('expected one emitted tree named ' + name + ', found %d' % len(candidates))
            else:
                nodes += shape(source['root'], candidates[0].find('Root'), 'Root', problems)
                rewritten += sum('source_op' in node for node in walk(source['root']))
                declared = [v.get('name') for v in candidates[0].findall('./Variables/*')]
                if declared != [v['name'] for v in source['variables']]:
                    problems.append('variable declarations differ from the source')
            if problems: failures.append(dict(tree=name, problems=problems[:10]))
            else: passed += 1
        trees.append(entry)
    rows = [dict(reason=reason, family=family(reason), sites=b['sites'], trees=sorted(b['trees']),
                 status=STATUS.get(family(reason), 'open'))
            for reason, b in sorted(blockers.items(), key=lambda p: (-p[1]['sites'], p[0]))]
    by_family = defaultdict(lambda: dict(reasons=0, sites=0, trees=set()))
    for row in rows:
        f = by_family[row['family']]; f['reasons'] += 1; f['sites'] += row['sites']; f['trees'].update(row['trees'])
    statuses = Counter(t['status'] for t in trees)
    return dict(schema=1, converter='C2', quest=model['quest'], document=own,
                trees=dict(total=len(trees), **statuses), tree_status=trees, blockers=rows,
                families={k: dict(reasons=v['reasons'], sites=v['sites'], trees=len(v['trees']))
                          for k, v in sorted(by_family.items(), key=lambda p: -p[1]['sites'])},
                prepared=dict(scope_resolutions=len(run['prepared']['scope_resolutions']),
                              renamed=dict(Counter(r['source'] + '->' + r['target'] for r in run['prepared']['renamed'])),
                              rename_blocked=len(run['prepared']['rename_blocked']),
                              initialisers=len(run['prepared'].get('initialisers', ())),
                              implicit_links=len(run['prepared'].get('implicit_links', ())),
                              value_renames=len(run['prepared'].get('value_renames', ())),
                              completed_branches=len(run['prepared'].get('completed_branches', ()))),
                lua_shapes=[dict(calls=calls, sites=v['sites'], trees=sorted(v['trees']))
                            for calls, v in sorted(lua.items(), key=lambda p: (-p[1]['sites'], p[0]))],
                layers=dict(source_equivalence=dict(verdict='FAIL' if failures else 'PASS',
                    summary=dict(checked=checked, passed=passed, failed=len(failures),
                                 residue=len(trees) - checked, nodes_compared=nodes,
                                 rewritten_nodes=rewritten), failures=failures)),
                runtime_verified=False)


def markdown(led, main_path=()):
    lines = ['# C2 blocker ledger: `%s`' % led['quest'], '',
             'Generated by `tools/quest_controller_conversion.py`. Offline; nothing is runtime-verified. '
             'No branch is omitted: a tree is emitted only when every site in it converts.', '',
             '**Trees:** %d total, %d emitted, %d blocked, %d blocked only by an included tree.' % (
                 led['trees']['total'], led['trees'].get('emitted', 0), led['trees'].get('blocked', 0),
                 led['trees'].get('blocked_by_include', 0)),
             '**Layer 1 (emitted trees vs source shape):** checked %(checked)d, passed %(passed)d, failed %(failed)d; '
             '%(residue)d trees not emitted; %(rewritten_nodes)d nodes of the emitted trees are rewritten operations.'
             % led['layers']['source_equivalence']['summary'], '',
             '## By family', '', '| Family | Reasons | Sites | Trees |', '|---|---:|---:|---:|']
    lines += ['| %s | %d | %d | %d |' % (k, v['reasons'], v['sites'], v['trees']) for k, v in led['families'].items()]
    if main_path:
        lines += ['', '## Main-path trees', '', '| Tree | Status | Blocked sites | Reasons |', '|---|---|---:|---:|']
        by_name = {t['tree']: t for t in led['tree_status']}
        lines += ['| %s | %s | %d | %d |' % (n, by_name[n]['status'], by_name[n]['blocked_sites'], by_name[n]['reasons'])
                  for n in main_path if n in by_name]
    lines += ['', '## Blockers', '', '| Reason | Family | Sites | Trees | Status |', '|---|---|---:|---:|---|']
    lines += ['| %s | %s | %d | %d | %s |' % (r['reason'].replace('|', '/')[:110], r['family'], r['sites'], len(r['trees']), r['status'])
              for r in led['blockers']]
    if led.get('lua_shapes'):
        lines += ['', '## Lua residue by call shape', '',
                  'Blocked Lua sites grouped by the calls they make (`campaign_controller_contracts.lua_shape`; '
                  '`<entity>` is a local bound to `XGenAIModule.GetEntityByWUID`, `data=` a write to a tree variable).',
                  '', '| Calls | Sites | Trees |', '|---|---:|---|']
        lines += ['| `%s` | %d | %s |' % (r['calls'].replace('|', '/') or '(none)', r['sites'], ', '.join(r['trees']))
                  for r in led['lua_shapes']]
    return '\n'.join(lines) + '\n'


def golden(led):
    return dict(schema=1, quest=led['quest'], converter='C2', trees=led['trees'], families=led['families'],
                emitted=sorted(t['tree'] for t in led['tree_status'] if t['status'] == 'emitted'),
                blockers=[dict(reason=r['reason'], sites=r['sites'], trees=len(r['trees'])) for r in led['blockers']],
                prepared=led['prepared'], source_equivalence=led['layers']['source_equivalence']['summary'],
                lua_shapes=[dict(calls=r['calls'], sites=r['sites']) for r in led.get('lua_shapes', [])])


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('--kcd1', type=Path, required=True); p.add_argument('--kcd2', type=Path, required=True)
    p.add_argument('--quest', required=True); p.add_argument('--work', type=Path, required=True)
    p.add_argument('--with', dest='with_quests', nargs='*', default=[])
    p.add_argument('--main-path', nargs='*', default=[], help='Trees to list first in the blocker file')
    p.add_argument('--blockers', type=Path); p.add_argument('--golden', type=Path)
    p.add_argument('--write-golden', action='store_true')
    a = p.parse_args()
    led = ledger(convert(a.kcd1, a.kcd2, a.quest, a.work, a.with_quests))
    print(json.dumps(dict(quest=led['quest'], trees=led['trees'], families=led['families'],
                          layer1=led['layers']['source_equivalence']['summary'])))
    failed = led['layers']['source_equivalence']['verdict'] != 'PASS'
    for failure in led['layers']['source_equivalence']['failures']: print('  FAIL', failure)
    if a.blockers:
        a.blockers.parent.mkdir(parents=True, exist_ok=True)
        old = a.blockers.read_text(encoding='utf-8') if a.blockers.is_file() else ''
        notes = '\n' + old[old.index(NOTES):] if NOTES in old else ''
        a.blockers.write_text(markdown(led, a.main_path) + notes, encoding='utf-8', newline='\n')
    if a.golden:
        current = json.loads(json.dumps(golden(led), sort_keys=True))
        if a.write_golden:
            a.golden.write_text(json.dumps(current, indent=2, sort_keys=True) + '\n', encoding='utf-8', newline='\n')
        elif json.loads(a.golden.read_text(encoding='utf-8')) != current:
            print('  FAIL golden fixture differs:', a.golden); failed = True
    return 1 if failed else 0


if __name__ == '__main__': raise SystemExit(main())
