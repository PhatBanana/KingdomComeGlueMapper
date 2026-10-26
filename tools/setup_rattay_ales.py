"""Source selection and offline preflight for Ales' Rattay hunting activity.

Content selection only, in the style of setup_gameplay: the quest, its source
actor and the source branch IDs. Conditions, effects, objectives, item IDs,
rewards and positions are read from KCD1 by the shared importers. Nothing here
installs content; `require_ready` refuses a recipe stage while any shared
adapter still rejects part of the source quest.
"""
import argparse
import json
from pathlib import Path
import re
import xml.etree.ElementTree as ET

QUEST = 'a_huntsman_alex'
PERSON = 'rat_refugee_ales'
SOURCE_LEVEL = 'rataje'
# (skald_element_id, start_topic) pairs from the source branch table.
BRANCHES = (('38230', '27371'), ('38231', '27375'))
DIALOGUES = (('gm_ales_hunting', 'FaderDialog', tuple(t for _, t in BRANCHES)),)
LIFECYCLE = re.compile(r"QuestSystem\.(\w+)\s*\(\s*'(\w+)'")


def source_quest(source, reader):
    from quest_import import import_quest
    return import_quest(source, QUEST, source_reader=reader)[0]


def closure(source, model):
    from campaign_dialogue import TABLES
    from campaign_quest_dialogues import discover
    from campaign_sources import retail_sources
    files = {n: ('Tables.pak', 'Libs/Tables/text/' + n + '.xml') for n in (*TABLES, 'dialogue_functions')}
    tables = {n: [dict(r.attrib) for r in ET.fromstring(s['data']).findall('./table/rows/row')]
              for n, s in retail_sources(source, files).items()}
    return discover(tables, model['quest_id'], model['quest'], model)


def storm_roles(data, person):
    """Roles the source Storm quest rule adds to this person, by exact name."""
    roles = []
    for rule in ET.fromstring(data).iter('rule'):
        names = {s.get('name') for s in rule.iter('hasName')}
        if person in names:
            roles.extend(r.get('name') for r in rule.iter('addRole'))
    return roles


def lifecycle_sites(dialogues, quest=QUEST):
    """Source exit scripts that change this quest, with their gating condition."""
    sites = []
    for model in dialogues:
        for tid, topic in model['topics'].items():
            for record in topic['sequences']:
                for function, name in LIFECYCLE.findall(record['source']['script'] or ''):
                    if name == quest:
                        sites.append(dict(topic=tid, sequence=record['source']['sequence_id'],
                            function=function, entry_condition=record['entry']['entry_condition']))
    return sites


def external_quests(dialogues, quest=QUEST):
    from campaign_quest_dependencies import predicate_references
    found = {}
    for model in dialogues:
        for topic in model['topics'].values():
            for record in topic['sequences']:
                for ref in predicate_references(record['entry']['entry_condition'], model.get('functions')):
                    if ref['quest'] != quest:
                        found.setdefault(ref['quest'], []).append(record['source']['sequence_id'])
    return found


def check_selection(found, soul_id, quest_npcs, roles, participants):
    """The hand selection must equal what the source tables say."""
    actual = {(b['source']['skald_element_id'], b['source']['start_topic']) for b in found['branches']}
    if actual != set(BRANCHES):
        raise ValueError('Source branch closure differs from selection: ' + repr(sorted(actual)))
    if [s.lower() for s in quest_npcs] != [soul_id.lower()]:
        raise ValueError('Quest NPC asset is not the selected person')
    if len(roles) != 1 or roles[0] not in participants:
        raise ValueError('Storm role does not name the source dialogue participant: ' + repr(roles))


def emit_dialogues(source, model, dialogues):
    from campaign_dialogue import emit
    rows = []
    (namespace, kind, topics), = DIALOGUES
    for tid in topics:
        loaded = next(d for d in dialogues if d['start_topic'] == tid)
        try:
            _, conversion = emit(loaded, namespace + '_' + tid, [model], kind=kind)
            rows.append(dict(topic=tid, emitted=True, exit_scripts=conversion['exit_scripts']))
        except ValueError as error:
            rows.append(dict(topic=tid, emitted=False, failure=str(error)))
    return rows


def blockers(report):
    found = []
    for row in report['dialogues']:
        if not row['emitted']:
            found.append(dict(kind='dialogue', topic=row['topic'], reason=row['failure']))
    seen = set()
    for site in report['lifecycle']:
        key = (site['sequence'], site['function'])
        if site['function'] in ('ActivateQuest', 'StartQuest', 'OpenInventory') and key not in seen:
            seen.add(key)
            found.append(dict(kind='exit_script', sequence=site['sequence'],
                reason='Source Lua quest call is copied, not lowered: QuestSystem.' + site['function']))
    for item in report['quest_graph_unsupported']:
        found.append(dict(kind='quest_graph', reason=item['kind'], objective=item.get('objective'),
                          table=item.get('table')))
    for item in report['tracked_items']['pending']:
        found.append(dict(kind='tracked_items', objective=item['objective'], reason='; '.join(item['reasons'])))
    return found


def preflight(source, target=None):
    """Run the shared importers in memory. Returns evidence, never installs."""
    from campaign_dependency_adapters import SourceTables
    from campaign_dialogue import load_many
    from campaign_quest_graph import emit_project
    from campaign_quest_items import plan
    from campaign_sources import RetailSourceReader
    from character_person import resolve_person
    source = Path(source)
    with RetailSourceReader(source) as reader:
        model = source_quest(source, reader)
        storm = reader(source, {'role': ('GameData.pak', 'Libs/Storm/roles/quests/' + QUEST + '.xml')})['role']
        tables = SourceTables(source, reader)
        soul = tables.row('rpg/soul', 'soul_name', PERSON)
    found = closure(source, model)
    dialogues = load_many(source, [(None, t) for _, t in BRANCHES])
    participants = {d['roles'][p['role_id']]['role_name'] for d in dialogues
                    for b in found['branches'] for p in b['participants'] if p['role_id'] in d['roles']}
    roles = storm_roles(storm['data'], PERSON)
    check_selection(found, soul['soul_id'], [r['soul_id'] for r in model['tables']['quest_npc']['rows']],
                    roles, participants)
    person = resolve_person(source, PERSON, SOURCE_LEVEL)
    _, conversion = emit_project([model], 'GlueAlesPreflight')
    report = dict(quest=QUEST, quest_id=model['quest_id'], person=PERSON, soul=soul['soul_id'],
        source_entity=person['actor'].get('EntityGuid'), storm_roles=roles,
        branches=[dict(skald_element_id=e, start_topic=t) for e, t in BRANCHES],
        lifecycle=lifecycle_sites(dialogues), external_quests=external_quests(dialogues),
        dialogues=emit_dialogues(source, model, dialogues),
        quest_graph_unsupported=conversion['quests'][0]['unsupported'],
        tracked_items=plan(model, {}, ()), installed=False, runtime_verified=False)
    if target is not None:
        report['target_lua_questsystem_calls'] = target_questsystem_calls(target)
    report['blockers'] = blockers(report)
    return report


def target_questsystem_calls(target):
    """Count KCD2 shipped Lua references to the KCD1 QuestSystem table."""
    import zipfile
    count = 0
    with zipfile.ZipFile(Path(target) / 'Data/Scripts.pak') as archive:
        for name in archive.namelist():
            if name.lower().endswith('.lua'):
                count += archive.read(name).count(b'QuestSystem.')
    return count


def source_expectations(model):
    """Objective roles and the accepted start state, read from the source tables only."""
    from collections import defaultdict
    tables = model['tables']
    rows = {r['objective_id']: r for r in tables['quest_objective']['rows']}
    tracked = defaultdict(set)
    for r in tables['quest_tracked_asset']['rows']:
        tracked[r['objective_id']].add(r['quest_asset_id'])
    items = {r['quest_asset_id'] for r in tables['quest_item']['rows']}
    goods = [rows[o]['objective_name'] for o in sorted(tracked, key=int) if tracked[o] & items]
    following = defaultdict(list); linked = set()
    for r in tables['quest_transition']['rows']:
        if r['enabled'] == 'True':
            following[r['from_objective_id']].append(r['to_objective_id'])
        linked.update((r['from_objective_id'], r['to_objective_id']))
    begins = [i for i, n in model['graph']['nodes'].items() if n['attributes'].get('Class') == 'Quest:Begin']
    if len(begins) != 1:
        raise ValueError('Expected one source quest begin node')
    started, queue = {}, list(following[begins[0]])
    while queue:
        oid = queue.pop(0)
        if oid not in rows or oid in started:
            continue
        # Condition '1' without a tracked asset completes on start in the source graph.
        if rows[oid]['condition'].strip() == '1' and not tracked[oid]:
            started[oid] = 'Completed'; queue.extend(following[oid])
        else:
            started[oid] = 'Started'
    refusals = [r['objective_name'] for o, r in rows.items()
                if r['is_hidden'] == 'True' and o not in linked and not tracked[o]]
    if len(refusals) != 1:
        raise ValueError('Expected one unlinked hidden source objective: ' + repr(refusals))
    return dict(goods=goods, accepted={rows[o]['objective_name']: s for o, s in started.items()},
                refusal=refusals[0], objectives=[r['objective_name'] for r in rows.values()])


def lab_scenarios(model, source='graph'):
    """quest_lab scenarios for what the emitter lowers, plus explicit UNSUPPORTED items."""
    from campaign_quest_graph import objective_identifier
    facts = source_expectations(model)
    names = {n: objective_identifier(n) for n in facts['objectives']}
    def state(values, **extra):
        # Exhaustive per objective: the expected state is true and every other is false.
        out = {'output.' + names[n] + '_' + s: s == expected for n, expected in values.items()
               for s in ('Unchanged', 'Started', 'Completed', 'Failed', 'Canceled')}
        out.update({'output.' + k: v for k, v in extra.items()})
        return out
    untouched = {n: 'Unchanged' for n in facts['objectives']}
    accepted = dict(untouched, **facts['accepted'])
    first = next(n for n in facts['goods'] if accepted[n] == 'Started')
    other = next(n for n in facts['goods'] if accepted[n] == 'Unchanged')
    accept = [dict(action='fire', port='activate'), dict(action='fire', port='start'),
              dict(action='advance', duration='1m')]
    scenario = lambda name, steps: dict(schema=1, name=name, source=source, entry=QUEST, steps=steps)
    runs = [
        scenario('No source input leaves the quest untouched', [dict(action='advance', duration='2h'),
            dict(action='assert', values=state(untouched, started=False, available=False))]),
        scenario('Accept starts only the first source hunt', accept + [
            dict(action='assert', values=state(accepted, started=True, completed=False))]),
        scenario('Refusal is recorded without starting the quest', [dict(action='fire', port='activate'),
            dict(action='fire', port='start_' + names[facts['refusal']]), dict(action='advance', duration='1m'),
            dict(action='assert', values=state(dict(untouched, **{facts['refusal']: 'Started'}), started=False))]),
        scenario('Snapshot mid-quest restores the same hunt and a repeated start does not reset it', accept + [
            dict(action='save', name='mid'), dict(action='advance', duration='2h'), dict(action='load', name='mid'),
            dict(action='assert', values=state(accepted, started=True)),
            dict(action='fire', port='start'), dict(action='advance', duration='1m'),
            dict(action='assert', values=state(accepted, started=True))]),
        scenario('Hunt objectives change independently', accept + [
            dict(action='fire', port='complete_' + names[first]),
            dict(action='assert', values=state(dict(accepted, **{first: 'Completed'}))),
            dict(action='fire', port='start_' + names[other]),
            dict(action='assert', values=state(dict(accepted, **{first: 'Completed', other: 'Started'}))),
            dict(action='fire', port='cancel_' + names[first]),
            dict(action='assert', values=state(dict(accepted, **{first: 'Canceled', other: 'Started'})))]),
    ]
    reason = 'quest graph does not lower tracked item completion; campaign_quest_items rejects these rows'
    unsupported = [
        dict(name='Early talk before q_huntPtacek is a no-op', reason='dialogue 27371 not emitted: q_huntPtacek is not a registered quest'),
        dict(name='Accept/refuse reached from the source conversation', reason='QuestSystem.ActivateQuest/StartQuest exit scripts are copied, not lowered; quest_lab rejects dialogue exit scripts'),
        *(dict(name='Hand-in ' + g + ' below/at/above the tracked count', reason=reason) for g in facts['goods']),
        dict(name='Exactly one money payout per hand-in', reason='quest_reward_money rows are converter-unsupported'),
        dict(name='Snapshot after payout does not pay twice', reason='no payout is emitted'),
        dict(name='Freshness (min_health) of handed-in meat', reason='min_health item filter rejected by campaign_quest_items; quest_lab rejects quality descriptors'),
        dict(name='Reputation rows on hand-in', reason='quest_reward_reputation rows are converter-unsupported'),
        dict(name='Hand-in inventory opened from dialogue', reason='QuestSystem.OpenInventory has no lowering'),
    ]
    return runs, unsupported


def write_lab(model, directory):
    from campaign_quest_graph import emit_project
    directory = Path(directory)
    if directory.exists():
        raise FileExistsError('Choose a fresh lab directory')
    blobs, _ = emit_project([model], 'GlueAlesLab')
    for name, blob in blobs.items():
        path = directory / 'graph' / name; path.parent.mkdir(parents=True, exist_ok=True); path.write_bytes(blob)
    runs, unsupported = lab_scenarios(model, source='graph')
    paths = []
    for index, s in enumerate(runs, 1):
        path = directory / ('%02d-scenario.json' % index)
        path.write_text(json.dumps(s, indent=2), encoding='utf-8'); paths.append(path)
    (directory / 'unsupported.json').write_text(json.dumps(unsupported, indent=2), encoding='utf-8')
    return paths


def require_ready(report):
    if report['blockers']:
        raise ValueError('Ales hunting activity is not installable; blockers: ' +
            '; '.join(b['kind'] + ':' + b['reason'] for b in report['blockers']))
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--kcd1', type=Path, required=True)
    parser.add_argument('--kcd2', type=Path)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--lab', type=Path, help='Fresh directory for quest_lab graph and scenarios')
    args = parser.parse_args()
    if args.output.exists():
        raise FileExistsError('Choose a fresh report path')
    report = preflight(args.kcd1, args.kcd2)
    if args.lab:
        from campaign_sources import RetailSourceReader
        with RetailSourceReader(args.kcd1) as reader:
            report['lab_scenarios'] = [str(p) for p in write_lab(source_quest(args.kcd1, reader), args.lab)]
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2), encoding='utf-8')
    print(json.dumps(dict(blockers=len(report['blockers']), report=str(args.output))))


if __name__ == '__main__':
    main()
