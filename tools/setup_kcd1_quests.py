"""Port selected KCD1 quests into the kcd1_travel campaign.

Selection only: the quest, its giver, the source dialogue branches and the quests
whose state its conditions read. Objectives, conditions, rewards, counts, item
classes, recordings and positions are read from KCD1 by the shared importers
(quest graph, tracking, policy and reward lowerings, dialogue lifecycle and
hand-in lowerings). Nothing here is runtime-verified.

    python tools/setup_kcd1_quests.py --plan                 # retail only, in memory
    python tools/setup_kcd1_quests.py --plan --package <map> # every quest, on top of a built package
    python tools/setup_kcd1_quests.py --check <package>      # read-only audit of a built package
    python tools/setup_kcd1_quests.py --lab <dir>            # quest_lab graph and scenarios

`upgrade` runs from setup_package_upgrade.finalize after the last person and shop
stage. It stages everything beside the package and applies one overlay at the
end, so a failure leaves the package untouched.
"""
import argparse
import contextlib
import copy
import hashlib
import json
import os
from pathlib import Path
import posixpath
import re
import tempfile
from types import SimpleNamespace
import xml.etree.ElementTree as ET
import zipfile

VERSION = 1
QUESTS = (dict(
    quest='a_huntsman_alex',
    people=('rat_refugee_ales',),
    # (skald element, start topic)
    branches=(('38230', '27371'), ('38231', '27375')),
    namespace='gm_kcd1_quest_a_huntsman_alex',
    # Quests the dialogue conditions read that are not ported: bound to declared stand-ins.
    prerequisites={'q_huntPtacek': 'completed'},
    # Reward rows the package cannot register (their souls are not in it); anything else pending is refused.
    accepted_pending=tuple(sorted(
        'quest_reward_reputation:' + objective + ':' + soul
        for objective in ('boar', 'deer', 'doe', 'hare', 'mushrooms')
        for soul in ('rat_bailiff', 'rat_berthold', 'rat_hanus'))),
    # Objective order for the lab's "next order" scenario: the hunt that follows the first.
    lab_order=('hare', 'boar')),
    dict(
    quest='a_huntsman_butcher',
    people=('sas_butcher',),
    branches=(('38322', '27388'), ('38324', '27396')),
    namespace='gm_kcd1_quest_a_huntsman_butcher',
    prerequisites={'q_returnToSkalitz': 'completed'},
    # The bailiff's soul is not in the package and faction 81 is not in its FactionTree.
    accepted_pending=tuple(sorted(
        'quest_reward_reputation:' + objective + ':' + target
        for objective in ('boarMoney', 'endOfFun', 'kidneyMoney', 'liverMoney', 'offalMoney')
        for target in ('faction_81', 'sas_bailiff'))),
    lab_order=('boar', 'offal'),
    # Two of its item classes (offal, liver) exist only in a package that has the shop imports,
    # so `plan` needs that package; the stage always reads the package it is upgrading.
    needs_package=True))
FOLDER = 'Quests/GlueTravel/gm_kcd1_quests/'
MARKER = 'Libs/GlueMapper/kcd1_quests.json'
PROJECT_NAME = 'gm_kcd1_quests'
HOST = 'gm_kcd1_quest_host'
CONTAINER = 'kcd1_travel'

TRAVEL = 'Data/gluemappertravel.pak'
LEVEL_PAK = 'Data/Levels/kcd1_travel/level.pak'
ENGLISH = 'Localization/English.pak'
ENGLISH_XML = 'Localization/English_xml.pak'
FACIALS = 'Data/gluemapper_dialogue_facials.pak'
ENTRY = 'Quests/GlueTravel/entry/kcd1_travel.xml'
PROJECT = 'Quests/GlueTravel/GlueTravel_kcd1.xml'
DIALOGUE_FOLDER = 'Quests/GlueTravel/entry/kcd1_travel/'
SOURCE_LEVEL = 'rataje'
PLAYER_ASSET = 'travel_player'      # the quest's player; the Project declares it
DIALOGUE_PLAYER = 'player'          # the Level entry's own player alias, as setup_gameplay's dialogues use
KCD1_DEFAULT = 'D:/SteamLibrary/steamapps/common/KingdomComeDeliverance'
KCD2_DEFAULT = 'D:/SteamLibrary/steamapps/common/KingdomComeDeliverance2'
SYNTHETIC_PLAYER = '4c2dcffb-dea1-6263-72d7-b39f4db2d8b5'
DEFINITIONS = 'Libs/concept/definitions.xml'


# ---------------------------------------------------------------- source checks (retail, read-only)

def row_for(quest):
    found = [r for r in QUESTS if r['quest'] == quest]
    if len(found) != 1:
        raise ValueError('Unknown KCD1 quest selection: ' + str(quest))
    return found[0]


def source_model(source, name, reader, behavior=True):
    from quest_import import import_quest
    return import_quest(source, name, source_reader=reader, require_behavior=behavior)[0]


def closure(source, model):
    import xml.etree.ElementTree as E
    from campaign_dialogue import TABLES
    from campaign_quest_dialogues import discover
    from campaign_sources import retail_sources
    files = {n: ('Tables.pak', 'Libs/Tables/text/' + n + '.xml') for n in (*TABLES, 'dialogue_functions')}
    tables = {n: [dict(r.attrib) for r in E.fromstring(s['data']).findall('./table/rows/row')]
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


def check_selection(found, soul_id, quest_npcs, roles, participants, branches=QUESTS[0]['branches']):
    """The hand selection must equal what the source tables say."""
    actual = {(b['source']['skald_element_id'], b['source']['start_topic']) for b in found['branches']}
    if actual != set(branches):
        raise ValueError('Source branch closure differs from selection: ' + repr(sorted(actual)))
    if [s.lower() for s in quest_npcs] != [soul_id.lower()]:
        raise ValueError('Quest NPC asset is not the selected person')
    if len(roles) != 1 or roles[0] not in participants:
        raise ValueError('Storm role does not name the source dialogue participant: ' + repr(roles))


def verify_selection(source, row, reader):
    """Quest model plus the evidence that the selection equals the source tables."""
    from campaign_dependency_adapters import SourceTables
    from campaign_dialogue import load_many
    if len(row['people']) != 1:
        raise ValueError('One giver per selected quest')
    person = row['people'][0]
    model = source_model(source, row['quest'], reader)
    storm = reader(source, {'role': ('GameData.pak', 'Libs/Storm/roles/quests/' + row['quest'] + '.xml')})['role']
    tables = SourceTables(source, reader)
    soul = tables.row('rpg/soul', 'soul_name', person)
    found = closure(source, model)
    dialogues = load_many(source, [(None, t) for _, t in row['branches']])
    participants = {d['roles'][p['role_id']]['role_name'] for d in dialogues
                    for b in found['branches'] for p in b['participants'] if p['role_id'] in d['roles']}
    roles = storm_roles(storm['data'], person)
    check_selection(found, soul['soul_id'], [r['soul_id'] for r in model['tables']['quest_npc']['rows']],
                    roles, participants, row['branches'])
    return model, dict(person=person, soul=soul['soul_id'], faction=soul.get('faction') or '', storm_roles=roles,
                       branches=[dict(skald_element_id=e, start_topic=t) for e, t in row['branches']])


# ---------------------------------------------------------------- quest_lab scenarios

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
    # What a completion starts: a target whose enabled, non-exclusive predecessors are all objectives.
    joins = {rows[target]['objective_name']: [rows[p]['objective_name'] for p in predecessors]
             for target, predecessors in ((t, [p for p, targets in following.items() if t in targets]) for t in rows)
             if predecessors and all(p in rows and rows[p]['is_exclusive'] != 'True' for p in predecessors)}
    automatic = {rows[o]['objective_name'] for o in rows if rows[o]['condition'].strip() == '1' and not tracked[o]}
    return dict(goods=goods, accepted={rows[o]['objective_name']: s for o, s in started.items()},
                refusal=refusals[0], objectives=[r['objective_name'] for r in rows.values()],
                joins=joins, automatic=automatic)


def after_completion(facts, values, name):
    """Objective states once `name` is completed: the source transitions it satisfies start their targets."""
    values = dict(values, **{name: 'Completed'})
    queue = [name]
    while queue:
        done = queue.pop(0)
        for target, predecessors in facts['joins'].items():
            if (done in predecessors and values[target] in ('Unchanged', 'Canceled')
                    and all(values[p] == 'Completed' for p in predecessors)):
                if target in facts['automatic']:
                    values[target] = 'Completed'; queue.append(target)
                else:
                    values[target] = 'Started'
    return values


def lab_scenarios(model, source='graph', order=None, prerequisites=('q_huntPtacek',)):
    """quest_lab scenarios for the objective state machine, plus the items quest_lab cannot model.

    order is (first hunt, the hunt KCD1 gives next); by default the first started hunt and the first
    unstarted one.
    """
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
    if order is None:
        order = (next(n for n in facts['goods'] if accepted[n] == 'Started'),
                 next(n for n in facts['goods'] if accepted[n] == 'Unchanged'))
    first, other = order
    if accepted.get(first) != 'Started' or accepted.get(other) != 'Unchanged':
        raise ValueError('Lab order must name the accepted hunt and a hunt not yet started: ' + repr(order))
    accept = [dict(action='fire', port='activate'), dict(action='fire', port='start'),
              dict(action='advance', duration='1m')]
    # Completing a hunt may start what the source graph chains to it (the butcher's payment objectives).
    done = after_completion(facts, accepted, first)
    if done.get(other) != 'Unchanged':
        raise ValueError('Lab order: completing the first hunt must not start the next one: ' + repr(order))
    complete = [dict(action='fire', port='complete_' + names[first])]
    if any(done[n] != accepted[n] and n in facts['automatic'] for n in done):
        complete.append(dict(action='advance', duration='1m'))       # queued automatic completions
    scenario = lambda name, steps: dict(schema=1, name=name, source=source, entry=model['quest'], steps=steps)
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
        scenario('Hunt objectives change independently', accept + complete + [
            dict(action='assert', values=state(done)),
            dict(action='fire', port='start_' + names[other]),
            dict(action='assert', values=state(dict(done, **{other: 'Started'}))),
            dict(action='fire', port='cancel_' + names[first]),
            dict(action='assert', values=state(dict(done, **{first: 'Canceled', other: 'Started'})))]),
        scenario('Completing the first hunt is recorded', accept + complete + [
            dict(action='assert', values={'output.' + names[first] + '_Completed': True})]),
        scenario('Cancelling the finished hunt and starting the next gives the next order', accept + complete + [
            dict(action='fire', port='cancel_' + names[first]),
            dict(action='fire', port='start_' + names[other]),
            dict(action='assert', values=state(dict(done, **{first: 'Canceled', other: 'Started'}), started=True))]),
    ]
    reason = 'quest_lab does not model ItemDeliveryHandler, tracked item descriptors or the dialogue hand-in window'
    unsupported = [
        dict(name='Early talk before ' + ', '.join(sorted(prerequisites)) + ' is a no-op',
             reason='the prerequisite is a declared stand-in; quest_lab does not run dialogue conditions'),
        dict(name='Accept/refuse reached from the source conversation',
             reason='lifecycle triggers are dialogue-side; quest_lab does not run dialogues'),
        *(dict(name='Hand-in ' + g + ' below/at/above the tracked count', reason=reason) for g in facts['goods']),
        dict(name='Exactly one money payout per hand-in', reason='quest_lab does not model AddReward'),
        dict(name='Snapshot after payout does not pay twice', reason='quest_lab does not model AddReward'),
        dict(name='Freshness (min_health) of handed-in meat', reason='quest_lab rejects quality descriptors'),
        dict(name='Reputation rows on hand-in', reason='quest_lab does not model AddReward'),
        dict(name='Death of the giver ends the quest', reason='quest_lab does not model SoulDeathTrigger'),
    ]
    return runs, unsupported


def write_lab(model, directory, order=None, blobs=None, prerequisites=('q_huntPtacek',)):
    """Graph and scenarios for `python tools/quest_lab_test.py run <dir>/*-scenario.json --output <out>`.

    blobs maps a path to the quest definition files of a built package; by default the quest is emitted
    unlowered from the source model.
    """
    from campaign_quest_graph import emit_project
    directory = Path(directory)
    if directory.exists():
        raise FileExistsError('Choose a fresh lab directory')
    if blobs is None:
        blobs, _ = emit_project([model], 'GlueQuestsLab')
    for name, blob in blobs.items():
        path = directory / 'graph' / name; path.parent.mkdir(parents=True, exist_ok=True); path.write_bytes(blob)
    runs, unsupported = lab_scenarios(model, source='graph', order=order, prerequisites=prerequisites)
    paths = []
    for index, s in enumerate(runs, 1):
        path = directory / ('%02d-scenario.json' % index)
        path.write_text(json.dumps(s, indent=2), encoding='utf-8'); paths.append(path)
    (directory / 'unsupported.json').write_text(json.dumps(unsupported, indent=2), encoding='utf-8')
    return paths


# ---------------------------------------------------------------- bindings and pending policy

def referenced_souls(model):
    """Lower-cased soul ids any table row of the quest names."""
    return {row['soul_id'].lower() for table in model['tables'].values() for row in table.get('rows', ())
            if row.get('soul_id')}


def bindings_for(model, context, souls, factions):
    """`campaign_quest_lowerings.lower` bindings limited to what the package really registers.

    souls: soul ids that have an entity in the level; factions: {source faction id: native faction name}.
    Only the souls and factions the quest names are bound.
    """
    import quest_lowering_report as report
    source, target = context
    bindings = report.build_bindings([model], source, target, False, player_asset=PLAYER_ASSET)
    names = source['souls']
    named = referenced_souls(model)
    bindings['soul_assets'] = {s.lower(): report.soul_alias(names[s.lower()]) for s in sorted(souls)
                               if s.lower() in names and s.lower() in named}
    wanted = {row['faction_id'] for table in model['tables'].values() for row in table.get('rows', ())
              if row.get('faction_id')}
    bindings['factions'] = {f: n for f, n in factions.items() if f in wanted}
    bindings['registered']['faction'] = sorted(set(bindings['registered']['faction']) | set(bindings['factions'].values()))
    return bindings


def pending_set(quest_report, model, souls):
    """Everything the lowerings left pending, one stable string each."""
    objectives = {r['objective_id']: r['objective_name'] for r in model['tables']['quest_objective']['rows']}
    lowered = quest_report['lowerings']
    found = set()
    for record in lowered['rewards']['pending']:
        row = record['row']
        target = souls.get(row.get('soul_id', '').lower()) or ('faction_' + row['faction_id'] if row.get('faction_id') else '?')
        found.add(record['table'] + ':' + objectives[row['objective_id']] + ':' + target)
    for record in lowered['tracking']['pending']:
        found.add('tracking:' + record['objective'])
    for record in lowered['policy']['pending']:
        found.add('policy:' + record['objective'])
    for record in quest_report['unsupported']:
        if record['kind'] != 'rewards':
            found.add('unsupported:' + record['kind'] + ':' + str(record.get('objective') or record.get('table')))
    return found


def check_pending(found, accepted):
    extra, missing = sorted(set(found) - set(accepted)), sorted(set(accepted) - set(found))
    if extra or missing:
        raise ValueError('Pending quest records differ from the accepted set; unexpected: ' + ', '.join(extra)
                         + '; no longer pending: ' + ', '.join(missing))


@contextlib.contextmanager
def tracked_predicate():
    """IsObjectiveTrackedCompleted resolves only while quests that went through `lower` are compiled."""
    from campaign_dialogue_conditions import OBJECTIVE
    import campaign_quest_lowerings
    had = 'IsObjectiveTrackedCompleted' in OBJECTIVE
    campaign_quest_lowerings.enable_tracked_predicate()
    try:
        yield
    finally:
        if not had:
            OBJECTIVE.pop('IsObjectiveTrackedCompleted', None)


# ---------------------------------------------------------------- the container (travel archive contents)

def read_travel(path, prefixes=('Quests/',), suffix='.xml'):
    from upgrade_map import read
    with zipfile.ZipFile(path) as archive:
        return {n: read(archive, n) for n in archive.namelist() if n.startswith(prefixes) and n.endswith(suffix)}


def synthetic_container():
    """Minimal Project and Level entry with the aliases the quest and its dialogues use (plan only)."""
    from campaign_quest_graph import definition, xml
    root, project = definition('Project', 'GlueTravel_kcd1')
    definitions = ET.SubElement(project, 'Definitions')
    ET.SubElement(definitions, 'Definition', File='entry/kcd1_travel.xml')
    nodes = ET.SubElement(project, 'Nodes')
    ET.SubElement(nodes, CONTAINER, Name=CONTAINER)
    ET.SubElement(ET.SubElement(project, 'Assets'), 'SoulAsset', Name=PLAYER_ASSET, SharedSoulGuids=SYNTHETIC_PLAYER)
    entry_root, level = definition('Level', CONTAINER)
    ET.SubElement(level, 'Definitions'); ET.SubElement(level, 'Nodes')
    ET.SubElement(ET.SubElement(level, 'Assets'), 'SoulAsset', Name=DIALOGUE_PLAYER, SharedSoulGuids=SYNTHETIC_PLAYER)
    return {PROJECT: xml(root), ENTRY: xml(entry_root)}


def visible_assets(resources):
    names = set()
    for path in (PROJECT, ENTRY):
        for node in ET.fromstring(resources[path]).iterfind('./Skald/*/Assets/*'):
            names.add(node.get('Name'))
    return names


def faction_names(resources):
    """{source faction id: native name} for every importer-owned faction leaf in the given tables."""
    from character_factions import LEAF
    found = {}
    for path, blob in resources.items():
        if posixpath.basename(path).startswith('FactionTree') and path.endswith('.xml'):
            for node in ET.fromstring(blob).iter('Faction'):
                name = node.get('Name', '')
                if name.startswith(LEAF):
                    found[name[len(LEAF):]] = name
    return found


def level_souls(level_pak):
    """Soul ids that have an entity in the level (the registered people)."""
    from upgrade_map import read
    with zipfile.ZipFile(level_pak) as archive:
        mission = ET.fromstring(read(archive, 'objects_mission0.xml'))
        wh = ET.fromstring(read(archive, 'whdata_0'))
    entities = {e.get('EntityGuid') for e in mission}
    return {s.findtext('SharedSoulGuid') for s in wh.findall('./SoulList/Souls/Soul')
            if s.findtext('EntityGuid') in entities}


def quest_records(model):
    return json.loads(json.dumps(model))


def prerequisite_report(row, source):
    """Every stand-in with the source condition text and sequences that read it."""
    from campaign_dialogue import load_many
    from campaign_quest_prerequisites import assumed_prerequisites
    topics = [t for _, t in row['branches']]
    models = [dict(m, alias=m.get('alias') or row['namespace'] + '_' + t)
              for t, m in zip(topics, load_many(source, [(None, t) for t in topics]))]
    return assumed_prerequisites(models, row['prerequisites'])


# ---------------------------------------------------------------- stage: emit, lower, register

def stage_quest(row, model, resources, context, souls, factions, text):
    """Emit, lower and register one quest in `resources` (archive path -> bytes).

    Returns (resources, bindings, report). Refuses a pending set other than row['accepted_pending'].
    """
    import campaign_quest_prerequisites as prerequisites
    import campaign_quest_registration as registration
    import campaign_quest_rewards
    from campaign_quest_graph import emit_project
    from campaign_quest_lowerings import lower
    resources = dict(resources)
    name = row['quest']
    bindings = bindings_for(model, context, souls, factions)
    names = context[0]['souls']
    files, emitted = emit_project([model], PROJECT_NAME, localization=text)
    before = len(emitted['quests'][0]['unsupported'])
    files, emitted = lower(files, emitted, [model], bindings)
    quest_report = emitted['quests'][0]
    pending = pending_set(quest_report, model, names)
    check_pending(pending, row['accepted_pending'])
    path = PROJECT_NAME + '/' + name + '.xml'
    aliases = {s: bindings['soul_assets'][s.lower()] for s in sorted(souls) if s.lower() in bindings['soul_assets']}
    group = model['tables']['quest']['rows'][0].get('group')
    resources[PROJECT], resources[ENTRY], quest_blob, registered = registration.register(
        resources[PROJECT], resources[ENTRY], files[PROJECT_NAME + '.xml'], files[path],
        '../' + PROJECT_NAME + '/' + name + '.xml', model=model, souls=aliases, group=group, shared_types=True)
    resources[FOLDER + name + '.xml'] = quest_blob
    for quest, state in sorted(row['prerequisites'].items()):
        # A stand-in another ported quest already declared is shared, never registered twice.
        blob = prerequisites.stub(quest, state)
        if FOLDER + quest + '.xml' in resources:
            if resources[FOLDER + quest + '.xml'] != blob:
                raise ValueError('Prerequisite stand-in is already declared differently: ' + quest)
            continue
        resources[FOLDER + quest + '.xml'] = blob
        resources[ENTRY] = prerequisites.register(resources[ENTRY], '../' + PROJECT_NAME + '/' + quest + '.xml', quest)
    if FOLDER + HOST + '.xml' not in resources:
        resources[FOLDER + HOST + '.xml'] = prerequisites.host(HOST)
        resources[ENTRY] = prerequisites.register(resources[ENTRY], '../' + PROJECT_NAME + '/' + HOST + '.xml', HOST)
    used = lambda table, key: sorted({reward['native'][key][len(campaign_quest_rewards.KCD1_VALUE_PREFIX):]
        for group_ in quest_report['lowerings']['rewards']['converted'] for reward in group_['rewards']
        if reward['table'] == table and reward['native'][key].startswith(campaign_quest_rewards.KCD1_VALUE_PREFIX)})
    value_names = dict(money=used('quest_reward_money', 'Amount'), reputation=used('quest_reward_reputation', 'ReputationChange'))
    report = dict(quest=name, unsupported_before=before, unsupported_after=len(quest_report['unsupported']),
                  remaining=[dict(kind=r['kind'], table=r.get('table'), objective=r.get('objective'),
                                  rows=len(r.get('rows', ()))) for r in quest_report['unsupported']],
                  pending=sorted(pending), tracking=[dict(objective=r['objective'], mode=r['mode'],
                      requirements=r['requirements']) for r in quest_report['lowerings']['tracking']['converted']],
                  rewards=[dict(objective=g['objective'], timing=g['timing'], rows=len(g['rewards']))
                           for g in quest_report['lowerings']['rewards']['converted']],
                  policy=quest_report['lowerings']['policy']['converted'], registration=registered,
                  value_names=value_names, journal_strings=len(quest_report['journal_strings']),
                  soul_assets=aliases, factions=dict(factions))
    return resources, bindings, report, quest_report['journal_strings']


def merged_value_names(report, marker=None):
    """The quest's value names together with those of every quest the marker already holds."""
    names = {kind: set(report['value_names'][kind]) for kind in ('money', 'reputation')}
    for entry in (marker or {}).get('quests', {}).values():
        for kind in names:
            names[kind].update(entry.get('report', {}).get('value_names', {}).get(kind, ()))
    return {kind: sorted(found) for kind, found in names.items()}


def value_tables(source, report, marker=None):
    """The 'kcd1_<name>' money and reputation rows the ported quests' AddReward nodes name.

    Each table is one file for all quests, so it is written with the rows of the quests already ported too.
    """
    import quest_lowering_report as lowering
    import campaign_quest_rewards
    from campaign_sources import RetailSourceReader
    source = Path(source)
    names = merged_value_names(report, marker)
    with RetailSourceReader(source) as reader:
        money = lowering.source_rows(reader, source, 'quest/money_change')
        reputation = lowering.source_rows(reader, source, 'rpg/reputation_change')
    return campaign_quest_rewards.kcd1_value_tables(money, reputation, names['money'], names['reputation'])


# ---------------------------------------------------------------- stage: dialogues

def emit_dialogues(row, model, prerequisites, resources, source):
    """Light dialogue emission for `plan`: the same emit and attach as the real stage, without audio or roles."""
    from campaign_dialogue import emit, load_many
    from campaign_dialogue_runtime import attach_dialogue
    files = {n.removeprefix('Quests/'): b for n, b in resources.items() if n.startswith('Quests/')}
    quests = [quest_records(m) for m in (model, *prerequisites)]
    topics = [t for _, t in row['branches']]
    for topic, loaded in zip(topics, load_many(source, [(None, t) for t in topics])):
        blob, report = emit(loaded, row['namespace'] + '_' + topic, quests, kind='FaderDialog',
                            participant_assets={'Dude': DIALOGUE_PLAYER}, area_assets={})
        files = attach_dialogue(files, CONTAINER, blob, report, HOST + '.active', ENTRY.removeprefix('Quests/'))
    out = dict(resources)
    out.update({'Quests/' + n: b for n, b in files.items()})
    return out


def exit_script_calls(blob):
    root = ET.fromstring(blob)
    return [(s.get('Name'), s.get('ExitScript')) for s in root.iter('Sequence')
            if 'QuestSystem.' in (s.get('ExitScript') or '')]


def bind_scripts(row, model, resources, bindings, npc_assets):
    """Lower the lifecycle and hand-in exit scripts of the quest's dialogues; returns (resources, report)."""
    import campaign_dialogue_delivery as delivery
    import campaign_dialogue_lifecycle as lifecycle
    import campaign_quest_tracking as tracking
    resources = dict(resources)
    quest = row['quest']
    quests = {quest: resources[FOLDER + quest + '.xml']}
    plan_ = tracking.plan(model, bindings)
    assets = visible_assets(resources)
    report = dict(lifecycle=[], delivery=[])
    for _, topic in row['branches']:
        path = DIALOGUE_FOLDER + row['namespace'] + '_' + topic + '.xml'
        if path not in resources:
            raise ValueError('Missing converted dialogue: ' + path)
        dialogue, entry = resources[path], resources[ENTRY]
        found = lifecycle.plan(dialogue, quests.keys())
        dialogue, entry = lifecycle.bind(dialogue, entry, found, quests)
        report['lifecycle'].append(dict(dialogue=found['dialogue'], topic=topic,
            sites=[dict(sequence=s['sequence'], function=s['function'], port=s['port']) for s in found['sites']]))
        hand_in = delivery.plan(dialogue, entry, quests[quest], plan_, npc_assets)
        dialogue, entry = delivery.bind(dialogue, entry, quests[quest], hand_in, plan_, npc_assets, assets=assets)
        report['delivery'].append(dict(dialogue=hand_in['dialogue'], topic=topic, sites=list(hand_in['sites']),
            groups=[dict(dict(name=g['name'], objectives=g['objectives'], descriptors=len(g['descriptors'])),
                         **({'aggregate': g['aggregate']} if g.get('aggregate') else {}))
                    for g in hand_in['groups']],
            decision=hand_in.get('decision'), accept=hand_in.get('accept_sequence'),
            reject=hand_in.get('reject_sequence'), assumptions=hand_in.get('assumptions', [])))
        left = exit_script_calls(dialogue)
        if left:
            raise ValueError('QuestSystem calls remain in ' + path + ': ' + ', '.join(s for s, _ in left))
        resources[path], resources[ENTRY] = dialogue, entry
    return resources, report


# ---------------------------------------------------------------- plan

def kcd_roots(source, target):
    source, target = Path(source), Path(target)
    for game, pak in ((source, 'Data/Tables.pak'), (target, 'Data/Tables.pak')):
        if not (game / pak).is_file():
            raise ValueError('Game folder is missing ' + pak + ': ' + str(game))
    return source, target


def plan_quest(row, source, target, package=None, context=None, base=None):
    """Steps 2 to 4 of the stage in memory. Returns (resources, report); writes nothing.

    base is the archive content to plan on instead of the package's own (the result of the quest
    planned before this one), so quests share what the stage registers once.
    """
    from character_factions import LEAF
    from campaign_quest_text import load as load_text
    import quest_lowering_report as lowering
    from campaign_sources import RetailSourceReader
    source, target = kcd_roots(source, target)
    with RetailSourceReader(source) as reader:
        model, evidence = verify_selection(source, row, reader)
        prerequisites = [source_model(source, name, reader, behavior=False) for name in sorted(row['prerequisites'])]
    context = context or lowering.load_context(source, target, package)
    people = {evidence['soul']}
    if package is None:
        base = base or synthetic_container()
        references = sorted({r['faction_id'] for r in model['tables'].get('quest_reward_reputation', {}).get('rows', [])
                             if r.get('faction_id')})
        factions = {f: LEAF + f for f in references}
        assumed = ['factions ' + ', '.join(references) + ' assumed registered: there is no package FactionTree to read']
        souls = people
        archives = [TRAVEL, LEVEL_PAK, ENGLISH, ENGLISH_XML, FACIALS]
    else:
        package = Path(package)
        base = base or read_travel(package / TRAVEL, ('Quests/', 'Libs/Tables/rpg/FactionTree'))
        if ENTRY not in base:
            raise ValueError('Package has no kcd1_travel campaign entry')
        factions = faction_names(base)
        if evidence['faction']:
            factions.setdefault(evidence['faction'], LEAF + evidence['faction'])
        assumed = ['faction ' + evidence['faction'] + ' arrives with ' + evidence['person']] if evidence['faction'] else []
        souls = level_souls(package / LEVEL_PAK) | people
        archives = [TRAVEL, LEVEL_PAK, ENGLISH, ENGLISH_XML, FACIALS]
    text, text_report = load_text(source, [model], 'English')
    if text_report['missing']:
        raise ValueError('Missing journal strings: ' + repr(text_report['missing']))
    resources, bindings, report, _ = stage_quest(row, model, base, context, souls, factions, text)
    npc_assets = {evidence['storm_roles'][0]: lowering.soul_alias(evidence['person'])}
    with tracked_predicate():
        resources = emit_dialogues(row, model, prerequisites, resources, source)
        resources, scripts = bind_scripts(row, model, resources, bindings, npc_assets)
    written = {p for p, b in resources.items() if base.get(p) != b} | {MARKER, *value_paths(report)}
    report.update(scripts, evidence=evidence, npc_assets=npc_assets, assumed=assumed,
                  assumed_prerequisites=prerequisite_report(row, source),
                  controller_pending=controller_pending(model), files=sorted(written),
                  archives=archives, runtime_verified=False)
    return resources, report


def value_paths(report):
    import campaign_quest_rewards
    paths = []
    if report['value_names']['money']:
        paths.append(campaign_quest_rewards.KCD1_MONEY_TABLE)
    if report['value_names']['reputation']:
        paths.append(campaign_quest_rewards.KCD1_REPUTATION_TABLE)
    return paths


def controller_pending(model):
    """The source controller behaviour is not converted; it is reported, never hand-wired."""
    return dict(entry=model.get('behavior_entry'), status=model.get('behavior_status'),
                operations=len(model.get('operations') or ()), converted=False)


def plan(source, target, package=None, notify=lambda *a: None):
    """Report of what the stage does for every selected quest. Reads retail (and the package, if given).

    With a package the quests are planned one on top of the other, as the stage ports them. Without one,
    a quest that needs package content is listed under `skipped` and every other quest is planned alone.
    """
    quests, skipped, resources = {}, {}, None
    for index, row in enumerate(QUESTS):
        notify('Plan KCD1 quest', index, len(QUESTS), row['quest'])
        if package is None and row.get('needs_package'):
            skipped[row['quest']] = 'needs a package that has the shop imports (--package)'
            continue
        planned, quests[row['quest']] = plan_quest(row, source, target, package,
                                                   base=resources if package is not None else None)
        if package is not None:
            resources = planned
    report = dict(version=VERSION, quests=quests, runtime_verified=False)
    if skipped:
        report['skipped'] = skipped
    return report


def summary(report):
    out = []
    for name, q in report['quests'].items():
        out.append(dict(quest=name, people=q['evidence']['person'], unsupported_before=q['unsupported_before'],
            unsupported_after=q['unsupported_after'],
            lifecycle_sites=sum(len(d['sites']) for d in q['lifecycle']),
            delivery_sites=sum(len(d['sites']) for d in q['delivery']),
            delivery_groups=sum(len(d['groups']) for d in q['delivery']),
            pending=len(q['pending']), files=len(q['files'])))
    return out


# ---------------------------------------------------------------- upgrade

def selection_digest(row):
    keys = ('quest', 'people', 'branches', 'namespace', 'prerequisites', 'accepted_pending')
    return hashlib.sha256(json.dumps({k: row[k] for k in keys}, sort_keys=True).encode()).hexdigest()


def digests(resources, paths):
    return {p: hashlib.sha256(resources[p]).hexdigest() for p in sorted(paths) if p in resources}


def merge_marker(existing, name, entry):
    marker = dict(existing or dict(version=VERSION, quests={}))
    marker['quests'] = dict(marker['quests'], **{name: entry})
    return marker


def read_marker(package):
    from upgrade_map import read
    with zipfile.ZipFile(package / TRAVEL) as archive:
        names = set(archive.namelist())
        if ENTRY not in names:
            return None, False
        if MARKER not in names:
            return None, True
        marker = json.loads(read(archive, MARKER))
    if marker.get('version') != VERSION:
        raise ValueError('Unsupported KCD1 quest migration version: ' + str(marker.get('version')))
    return marker, True


def migrate_quest(package, source, target, row, marker, notify):
    """One quest in a TemporaryDirectory beside the package, then one overlay. Returns (files, report)."""
    from build_actor_dialogues_test import build as build_dialogues
    from build_english_audio_test import merge_audio_strings
    from build_horse_trader_test import rewrite
    from build_quest_people_test import build as build_people
    from build_recipe import apply_overlay
    from campaign_quest_text import load as load_text, localization_table
    from campaign_sources import RetailSourceReader
    from upgrade_map import read
    import quest_lowering_report as lowering
    name = row['quest']
    label = 'Port the KCD1 quest ' + name
    with tempfile.TemporaryDirectory(prefix='kcd1-quests-', dir=package.parent) as temporary:
        temporary = Path(temporary)
        notify(label, 0, 5, 'Verify the selection')
        with RetailSourceReader(source) as reader:
            model, evidence = verify_selection(source, row, reader)
            prerequisites = [source_model(source, n, reader, behavior=False) for n in sorted(row['prerequisites'])]
        text, text_report = load_text(source, [model], 'English')
        if text_report['missing']:
            raise ValueError('Missing journal strings: ' + repr(text_report['missing']))
        # 1. People. A giver already in the level is kept.
        notify(label, 1, 5, ', '.join(row['people']))
        stage = temporary / 'people'
        build_people(SimpleNamespace(source=source, target=target, mod=package, output=stage, model=None,
            person=list(row['people']), source_level=SOURCE_LEVEL, level=CONTAINER, source_profile=[],
            dialogue_profile=[], dialogue_model=[], quest_path=None, project_path=PROJECT, progress=notify))
        people_report = json.loads((stage / 'report.json').read_text(encoding='utf-8'))
        if people_report['pending']:
            raise ValueError('Quest giver conversion is incomplete: ' + json.dumps(people_report['pending']))
        people_travel = stage / 'package' / TRAVEL
        people_level = stage / 'package' / LEVEL_PAK
        # 2. Quest.
        notify(label, 2, 5, 'Emit, lower and register')
        base = read_travel(people_travel, ('Quests/', 'Libs/Tables/rpg/FactionTree'))
        context = lowering.load_context(source, target, package)
        souls = level_souls(people_level)
        resources, bindings, report, records = stage_quest(
            row, model, base, context, souls, faction_names(base), text)
        journal = localization_table(records)
        tables = value_tables(source, report, marker)
        resources.update(tables)
        quest_travel = temporary / 'quest' / TRAVEL
        rewrite(people_travel, quest_travel, {p: b for p, b in resources.items() if base.get(p) != b})
        people_travel.unlink()
        # 3. Dialogues, with their voices, text and facial tracks.
        notify(label, 3, 5, 'Convert the dialogues')
        ir = temporary / 'ir'; ir.mkdir()
        files = []
        for m in (model, *prerequisites):
            (ir / (m['quest'] + '.json')).write_text(json.dumps(m), encoding='utf-8'); files.append(ir / (m['quest'] + '.json'))
        with tracked_predicate():
            build_dialogues(SimpleNamespace(source=source, target=target, mod=package, output=temporary / 'dialogues',
                archive=quest_travel, quest_ir=files, start_topic=[t for _, t in row['branches']],
                namespace=row['namespace'], kind='FaderDialog', container=ENTRY.removeprefix('Quests/'),
                container_name=CONTAINER, activation=HOST + '.active', skill_upgrade=[],
                participant_asset=['Dude=' + DIALOGUE_PLAYER], area_asset=[]))
            dialogue_travel = temporary / 'dialogues' / 'package' / TRAVEL
            staged = read_travel(dialogue_travel, ('Quests/',))
            quest_travel.unlink()
            # 4. Exit scripts.
            notify(label, 4, 5, 'Lower quest calls in dialogue scripts')
            npc_assets = {evidence['storm_roles'][0]: lowering.soul_alias(evidence['person'])}
            final, scripts = bind_scripts(row, model, staged, bindings, npc_assets)
        entry = dict(selection=selection_digest(row), report={k: v for k, v in report.items()},
                     lifecycle=scripts['lifecycle'], delivery=scripts['delivery'], evidence=evidence,
                     npc_assets=npc_assets, controller_pending=controller_pending(model),
                     assumed_prerequisites=prerequisite_report(row, source),
                     people=dict(converted=[p['person'] for p in people_report['converted']],
                                 existing=[p.get('person') for p in people_report['existing']]),
                     dialogues=[row['namespace'] + '_' + t for _, t in row['branches']],
                     hashes=digests({**final, **tables}, [*(p for p in final if base.get(p) != final[p]), *tables]),
                     runtime_verified=False)
        document = merge_marker(marker, name, entry)
        replacements = {p: b for p, b in final.items() if staged.get(p) != b}
        replacements[MARKER] = json.dumps(document, indent=1, sort_keys=True).encode('utf-8')
        changed_travel = temporary / 'final' / TRAVEL
        rewrite(dialogue_travel, changed_travel, replacements)
        dialogue_travel.unlink()
        # Collect the overlay: travel archive, level, actors, dialogue audio, facials, strings.
        overlay = temporary / 'final'
        (overlay / 'Data/Levels/kcd1_travel').mkdir(parents=True, exist_ok=True)
        people_level.replace(overlay / LEVEL_PAK)
        for pak in sorted((stage / 'package' / 'Data').glob('*.pak')):
            if pak.name != 'gluemappertravel.pak':
                pak.replace(overlay / 'Data' / pak.name)
        (overlay / 'Localization').mkdir(parents=True, exist_ok=True)
        dialogue_stage = temporary / 'dialogues' / 'package'
        (dialogue_stage / ENGLISH).replace(overlay / ENGLISH)
        (dialogue_stage / FACIALS).replace(overlay / FACIALS)
        with zipfile.ZipFile(dialogue_stage / ENGLISH_XML) as archive:
            dialog = read(archive, 'text_ui_dialog.xml')
        with zipfile.ZipFile(stage / 'package' / ENGLISH_XML) as archive:
            quest_text = merge_audio_strings(read(archive, 'text_ui_quest.xml'), journal)
        rewrite(stage / 'package' / ENGLISH_XML, overlay / ENGLISH_XML,
                {'text_ui_dialog.xml': dialog, 'text_ui_quest.xml': quest_text})
        changed = apply_overlay(package, overlay, consume=True)
    notify(label, 5, 5, str(len(changed)) + ' archives')
    return changed, dict(entry, files=sorted(changed))


def upgrade(package, source, target, notify=lambda *a: None):
    """Idempotent: a second run changes nothing. Returns (files, report) like every stage.

    A package without the kcd1_travel campaign entry is left alone.
    """
    package = Path(package)
    if not (package / TRAVEL).is_file():
        return {}, {}
    marker, has_entry = read_marker(package)
    if not has_entry:
        return {}, {}
    done = (marker or {}).get('quests', {})
    for name, entry in done.items():
        if entry['selection'] != selection_digest(row_for(name)):
            raise ValueError('The KCD1 quest selection changed since it was ported: ' + name)
    pending = [r for r in QUESTS if r['quest'] not in done]
    if not pending:
        return {}, dict(version=VERSION, quests=done)
    if source is None or target is None:
        raise ValueError('KCD1 and KCD2 folders required to port KCD1 quests')
    source, target = kcd_roots(source, target)
    files, reports = {}, dict(done)
    for row in pending:
        changed, entry = migrate_quest(package, source, target, row, marker, notify)
        files.update(changed)
        reports[row['quest']] = entry
        marker = merge_marker(marker, row['quest'], {k: v for k, v in entry.items() if k != 'files'})
    return files, dict(version=VERSION, quests=reports)


# ---------------------------------------------------------------- offline audit of a built package (read-only)

# Their ports (SetTrue, OnChanged, ...) follow the TypeT they are instantiated with.
DYNAMIC = frozenset(('State', 'Watch'))
LEVEL_EVENTS = frozenset(('OnWake', 'OnLevelSwitched', 'OnSleep'))
DISCRIMINATORS = {'Function': ('MethodName', 'DeclaringType'), 'MemberFunction': ('MethodName', 'DeclaringType'),
                  'EventFunction': ('MethodName', 'DeclaringType'), 'EventMemberFunction': ('MethodName', 'DeclaringType'),
                  'IfFunction': ('MethodName', 'DeclaringType'), 'ObjectProperties': ('DeclaringType',)}


class Definitions:
    """Retail KCD2 node catalogue (Libs/concept/definitions.xml): tags, methods and ports."""

    def __init__(self, blob):
        self.by_type = {}
        for node in ET.fromstring(blob).find('Nodes'):
            ports = {}
            for kind in ('CompileTimePort', 'RunTimePort'):
                for port in node.iterfind('Ports/' + kind):
                    ports[port.get('Name')] = (port.get('Direction'), port.get('IsVariadic') == 'true')
            properties = {p.get('Name'): p.get('Value') for p in node.iterfind('Properties/Property')}
            self.by_type.setdefault(node.get('TypeName'), []).append((dict(node.attrib, **properties), ports))

    def resolve(self, node):
        """(ports or None, kind): kind is 'retail', 'dynamic', 'unknown', 'method' or 'ambiguous'."""
        found = self.by_type.get(node.tag)
        if not found:
            return None, 'unknown'
        if node.tag in DISCRIMINATORS:
            keys = DISCRIMINATORS[node.tag]
            matches = [ports for attributes, ports in found if all(attributes.get(k) == node.get(k) for k in keys)]
            return (matches[0], 'retail') if matches else (None, 'method')
        if node.tag in DYNAMIC:
            return None, 'dynamic'
        if len(found) == 1:
            return found[0][1], 'retail'
        named = [ports for attributes, ports in found if attributes.get('Name') == node.tag]
        return (named[0], 'retail') if named else (None, 'ambiguous')


def host_of_blob(blob):
    skald = ET.fromstring(blob).find('Skald')
    if skald is None or len(skald) != 1:
        raise ValueError('Expected one definition host')
    return skald[0]


def local_types(resources):
    """{definition name: ports} for every Skald definition file, and the objective names (quest node types)."""
    ports, objectives = {}, set()
    for path, blob in resources.items():
        if not path.endswith('.xml'):
            continue
        try:
            host = host_of_blob(blob)
        except (ValueError, ET.ParseError):
            continue
        ports[host.get('Name')] = {p.get('Name'): (p.get('Direction'), False) for p in host.iterfind('Ports/Port')}
        objectives.update(o.get('Name') for o in host.iterfind('Objectives/Objective'))
    return ports, objectives


def graph_audit(resources, paths, owned, definitions, aliases):
    """Node tags, methods, ports and asset aliases of the given definition files.

    The Level entry is audited only where this stage wrote: the nodes in `owned`, and any node that takes an edge
    from one of them. Returns dict(nodes, edges, unchecked, problems).
    """
    ports_by_name, objectives = local_types(resources)
    result = dict(nodes=0, edges=0, unchecked=0, problems=[])
    problems = result['problems']
    for path in paths:
        if path not in resources:
            problems.append('missing graph file ' + path)
            continue
        host = host_of_blob(resources[path])
        nodes = host.find('Nodes')
        own = {p.get('Name'): p.get('Direction') for p in host.iterfind('Ports/Port')}
        entry = path == ENTRY
        if nodes is None:
            nodes = ET.Element('Nodes')
        by_id = {n.get('Name'): n for n in nodes}
        declared = aliases | {a.get('Name') for a in host.iterfind('Assets/*')}
        resolved = {}
        for node in nodes:
            if node.tag in ports_by_name:
                resolved[node.get('Name')] = (ports_by_name[node.tag], 'local')
            elif node.tag in objectives:
                resolved[node.get('Name')] = (None, 'dynamic')
            else:
                resolved[node.get('Name')] = definitions.resolve(node)
        for node in nodes:
            name = node.get('Name')
            ports, kind = resolved[name]
            touched = not entry or name in owned or any(
                e.get('From', '').split('.', 1)[0] in owned for e in node.findall('Edge'))
            if not touched:
                continue
            result['nodes'] += 1
            where = path.rsplit('/', 1)[-1] + ':' + str(name)
            if kind in ('unknown', 'method', 'ambiguous'):
                problems.append('%s: node %s%s is not in the retail definitions' % (
                    where, node.tag, (' ' + str(node.get('MethodName') or node.get('DeclaringType'))) if kind == 'method' else ''))
            if ports is None:
                result['unchecked'] += 1
            variadic = lambda direction: ports is not None and any(d == direction and v for d, v in ports.values())
            for child in node:
                if child.tag == 'Constant' and ports is not None and child.get('Name') not in ports and not variadic('In'):
                    problems.append('%s: constant %s is not a port of %s' % (where, child.get('Name'), node.tag))
                if child.tag == 'Asset':
                    if ports is not None and child.get('Name') not in ports:
                        problems.append('%s: asset port %s is not a port of %s' % (where, child.get('Name'), node.tag))
                    if child.get('Alias') not in declared:
                        problems.append('%s: asset alias %s is not declared by an ancestor' % (where, child.get('Alias')))
            for e in node.findall('Edge'):
                result['edges'] += 1
                to, source = e.get('To'), e.get('From')
                if node.tag == 'Output':
                    if own.get(to) != 'Out' and host.tag != 'Quest':
                        problems.append('%s: edge to %s is not a declared Out port of the definition' % (where, to))
                elif ports is not None:
                    if to not in ports and not variadic('In'):
                        problems.append('%s: edge to %s, which %s does not declare' % (where, to, node.tag))
                    elif to in ports and ports[to][0] != 'In':
                        problems.append('%s: edge to %s, which is not an In port' % (where, to))
                if '.' in source:
                    origin, port = source.split('.', 1)
                    if origin not in by_id:
                        problems.append('%s: edge from %s, which is not a node of this definition' % (where, source))
                        continue
                    origin_ports = resolved[origin][0]
                    if origin_ports is None:
                        continue
                    if port not in origin_ports and not any(d == 'Out' and v for d, v in origin_ports.values()):
                        problems.append('%s: edge from %s, which %s does not declare' % (where, source, by_id[origin].tag))
                    elif port in origin_ports and origin_ports[port][0] != 'Out':
                        problems.append('%s: edge from %s, which is not an Out port' % (where, source))
                elif own.get(source) != 'In' and source not in LEVEL_EVENTS:
                    problems.append('%s: edge from %s, which is not a declared In port' % (where, source))
    return result


def dialogue_audit(blob, name):
    """Port, trigger and condition references of one converted dialogue; no QuestSystem call may remain."""
    host = host_of_blob(blob)
    problems = []
    ports = {p.get('Name'): (p.get('Direction'), p.get('Type')) for p in host.iterfind('Ports/Port')}
    for sequence in host.iter('Sequence'):
        if 'QuestSystem.' in (sequence.get('ExitScript') or ''):
            problems.append('%s: %s keeps a QuestSystem call in its ExitScript' % (name, sequence.get('Name')))
        for port in sequence.iterfind('Triggers/Port'):
            if ports.get(port.get('Name'), (None,))[0] != 'Out':
                problems.append('%s: %s fires %s, which is not an Out port' % (name, sequence.get('Name'), port.get('Name')))
        for text in (sequence.get('EntryCondition') or '', sequence.get('NpcEntryCondition') or ''):
            for port in re.findall(r"Port\('([^']+)'\)", text):
                if ports.get(port, (None,))[0] != 'In':
                    problems.append('%s: %s reads %s, which is not an In port' % (name, sequence.get('Name'), port))
    return problems


def aliases_of(resources):
    names = set()
    for path in (PROJECT, ENTRY):
        names.update(n.get('Name') for n in host_of_blob(resources[path]).iterfind('Assets/*'))
    return names


def node_constants(node):
    return {c.get('Name'): c.get('Value') for c in node.findall('Constant')}


def expected_descriptors(model):
    """{objective name: [(item class, amount, minimum health)]} from KCD1's own tracked item rows."""
    from campaign_objective_conditions import counted_asset
    tables = model['tables']
    objectives = {r['objective_id']: r['objective_name'] for r in tables['quest_objective']['rows']}
    items = {r['quest_asset_id']: r for r in tables.get('quest_item', dict(rows=[]))['rows']}
    found = {}
    for row in tables.get('quest_tracked_asset', dict(rows=[]))['rows']:
        if row['quest_asset_id'] in items and counted_asset(row):
            item = items[row['quest_asset_id']]
            health = float(item.get('min_health') or 0)
            found.setdefault(row['objective_id'], []).append((item['item_id'].lower(), int(row['count']), health))
    return {oid: dict(objective=objectives[oid], descriptors=d) for oid, d in found.items()}


def tracking_audit(quest_blob, model, item_names):
    """Each tracked hunt has descriptors equal to KCD1's rows; each item class resolves and is named."""
    nodes = {n.get('Name'): n for n in host_of_blob(quest_blob).iterfind('Nodes/*')}
    problems, rows = [], []
    for oid, wanted in sorted(expected_descriptors(model).items(), key=lambda p: int(p[0])):
        found = []
        index = 0
        while 'lowered_track_%s_%d_descriptor' % (oid, index) in nodes:
            c = node_constants(nodes['lowered_track_%s_%d_descriptor' % (oid, index)])
            found.append((c.get('ItemClass', '').lower(), int(c.get('Amount', '0')), float(c.get('MinimumHealth', '0'))))
            index += 1
        if found != wanted['descriptors']:
            problems.append('tracking %s: descriptors %r differ from KCD1 rows %r' % (wanted['objective'], found, wanted['descriptors']))
        for item, _, _ in wanted['descriptors']:
            if item not in item_names:
                problems.append('tracking %s: item class %s has no item row' % (wanted['objective'], item))
            elif not item_names[item]:
                problems.append('tracking %s: item class %s has no English name' % (wanted['objective'], item))
        rows.append(dict(objective=wanted['objective'], descriptors=found, names=[item_names.get(i) for i, _, _ in found]))
    if not rows:
        problems.append('no tracked item objective found in the source model')
    return rows, problems


def delivery_audit(resources, quest, model, delivery, tracked):
    """One handler per expected group; delivery descriptors equal the tracking descriptors; the triggers are wired."""
    entry = host_of_blob(resources[ENTRY])
    nodes = {n.get('Name'): n for n in entry.iterfind('Nodes/*')}
    objective_ids = {r['objective_name']: r['objective_id'] for r in model['tables']['quest_objective']['rows']}
    problems = []
    for record in delivery:
        if not record['sites']:
            continue
        dialogue = record['dialogue']
        stem = 'lowered_delivery_' + dialogue + '_'
        handlers = sorted(n for n, node in nodes.items() if n.startswith(stem) and node.tag == 'ItemDeliveryHandler')
        expected = sorted(stem + g['name'] + '_handler' for g in record['groups'])
        if handlers != expected:
            problems.append('%s: handlers %r differ from the expected groups %r' % (dialogue, handlers, expected))
        for group in record['groups']:
            g = stem + group['name'] + '_'
            wanted = [d for o in group['objectives'] for d in tracked.get(objective_ids[o], dict(descriptors=[]))['descriptors']]
            found, index = [], 0
            while g + 'item_%d' % index in nodes:
                c = node_constants(nodes[g + 'item_%d' % index])
                found.append((c.get('ItemClass', '').lower(), int(c.get('Amount', '0')), float(c.get('MinimumHealth', '0'))))
                index += 1
            if found != wanted:
                problems.append('%s: delivery %s descriptors %r differ from tracking %r' % (dialogue, group['name'], found, wanted))
        if not record['groups']:
            continue
        first = stem + record['groups'][0]['name'] + '_'
        for verb in ('begin', 'accept', 'reject'):
            gate = nodes.get(first + verb)
            source = dialogue + '.delivery_' + verb
            if gate is None or not any(e.get('From') == source and e.get('To') == 'Exec' for e in gate.findall('Edge')):
                problems.append('%s: delivery_%s is not wired to the first gate' % (dialogue, verb))
        blob = resources[DIALOGUE_FOLDER + dialogue + '.xml']
        host = host_of_blob(blob)
        fired = {p.get('Name') for p in host.iterfind('.//Sequence/Triggers/Port')}
        for verb in ('begin', 'accept', 'reject'):
            if 'delivery_' + verb not in fired:
                problems.append('%s: no sequence fires delivery_%s' % (dialogue, verb))
    return problems


def reward_audit(quest_blob, tables, aliases, kcd1_amounts):
    """Every reward row, soul and faction the quest names resolves; kcd1_ rows carry KCD1's numbers."""
    problems, used = [], []
    for reward in host_of_blob(quest_blob).iterfind('.//AddReward/Rewards/*'):
        tag = reward.tag
        used.append(tag)
        if tag == 'MoneyReward':
            row = tables['money_change'].get(reward.get('Amount'))
            if row is None:
                problems.append('MoneyReward %s resolves to no money_change row' % reward.get('Amount'))
            else:
                check_amount(problems, 'money_change', reward.get('Amount'), row, kcd1_amounts['money'])
        elif tag in ('SoulReputationReward', 'FactionReputationReward'):
            row = tables['reputation_change'].get(reward.get('ReputationChange'))
            if row is None:
                problems.append('%s %s resolves to no reputation_change row' % (tag, reward.get('ReputationChange')))
            else:
                check_amount(problems, 'reputation_change', reward.get('ReputationChange'), row, kcd1_amounts['reputation'])
            target = reward.get('Target')
            if tag.startswith('Soul') and target not in aliases:
                problems.append('%s target %s is not a declared soul asset' % (tag, target))
            if tag.startswith('Faction') and target not in tables['factions']:
                problems.append('%s target %s is not in any FactionTree' % (tag, target))
        else:
            problems.append('unexpected reward element ' + tag)
    return used, problems


def check_amount(problems, kind, name, row, kcd1):
    from campaign_quest_rewards import KCD1_VALUE_PREFIX
    if name.startswith(KCD1_VALUE_PREFIX):
        source = name[len(KCD1_VALUE_PREFIX):]
        if source not in kcd1:
            problems.append('%s %s has no KCD1 row to compare with' % (kind, name))
        elif row.get('change') != kcd1[source]:
            problems.append('%s %s changes by %s, KCD1 %s by %s' % (kind, name, row.get('change'), source, kcd1[source]))


def dialogue_media_audit(blob, name, text, recordings, dubbing, facial_paths, voices):
    """Every response has text, a recording, a dubbing row and a facial track; the voices resolve."""
    from zlib import crc32
    host = host_of_blob(blob)
    problems, lines = [], 0
    for response in host.iter('Response'):
        key = response.find('Text').get('StringName')
        lines += 1
        if key not in text:
            problems.append('%s: no text row for %s' % (name, key))
        stems = recordings.get(name.lower(), {})
        path = next((member for stem, member in stems.items() if stem.endswith('_' + key.lower())), None)
        if path is None:
            problems.append('%s: no recording for %s' % (name, key))
            continue
        stem = path.rsplit('/', 1)[-1][:-4]
        if str(crc32(stem.encode('utf-8'))) not in dubbing:
            problems.append('%s: no dubbing row for %s' % (name, stem))
        if 'animations/humans/facials/' + path[:-4].lower() + '.caf' not in facial_paths:
            problems.append('%s: no facial track for %s' % (name, stem))
    for soul in host.iter('SelectedSoul'):
        if soul.get('Voice') not in voices:
            problems.append('%s: voice %s does not resolve' % (name, soul.get('Voice')))
    return lines, problems


def journal_audit(quest_blob, project_blob, text):
    """Quest and objective strings are present; every journal marker names a declared asset."""
    quest = host_of_blob(quest_blob)
    problems = []
    keys = [e.get('StringName') for e in quest.iter() if e.tag in ('QuestName', 'QuestDescription', 'LocalizedName', 'Log')
            if e.get('StringName')]
    for key in keys:
        if key not in text:
            problems.append('journal string %s is missing from text_ui_quest.xml' % key)
    declared = {a.get('Name') for a in host_of_blob(project_blob).iterfind('Assets/*')}
    for log in quest.iter('EnumLog'):
        if log.get('Marker') and log.get('Marker') not in declared:
            problems.append('journal marker %s is not a declared asset' % log.get('Marker'))
    if not keys:
        problems.append('the quest has no journal strings')
    return len(keys), problems


def npc_audit(level, resources, evidence, alias):
    """One entity, one soul, a scheduler row and a SoulAsset with the same GUID."""
    from campaign_entity_links import guid_value
    mission, wh, scheduler = level
    person, soul = evidence['person'], evidence['soul']
    problems = []
    entities = [e for e in mission if e.get('Name') == person]
    if len(entities) != 1:
        return ['%d entities named %s in the level' % (len(entities), person)]
    guid = entities[0].get('EntityGuid')
    souls = [s for s in wh.findall('./SoulList/Souls/Soul') if s.findtext('SharedSoulGuid') == soul]
    if len(souls) != 1:
        problems.append('%d souls with id %s in the level' % (len(souls), soul))
    elif souls[0].findtext('EntityGuid') != guid:
        problems.append('the soul of %s belongs to another entity' % person)
    rows = [r for r in scheduler.find('Schedulers') if r.get('EntityGuid') == str(guid_value(guid))]
    if not rows:
        problems.append('no scheduler row for ' + person)
    assets = [a for a in host_of_blob(resources[PROJECT]).iterfind('Assets/SoulAsset') if a.get('SharedSoulGuids') == soul]
    if not any(a.get('Name') == alias for a in assets):
        problems.append('no SoulAsset %s with the soul id of %s' % (alias, person))
    return problems


def table_rows(blobs, tag, key='name'):
    rows = {}
    for blob in blobs:
        for node in ET.fromstring(blob).iter(tag):
            if node.get(key) is not None:
                rows[node.get(key)] = dict(node.attrib)
    return rows


def string_rows(blob):
    found = {}
    for row in ET.fromstring(blob).findall('Row'):
        cells = row.findall('Cell')
        if len(cells) >= 2:
            found[cells[0].text or ''] = ''.join(cells[-1].itertext())
    return found


def package_item_patches(package):
    """Item tables staged in the package's archives (the same files container_items.item_patches reads)."""
    from upgrade_map import read
    patches = []
    for path in sorted((Path(package) / 'Data').glob('*.pak')):
        with zipfile.ZipFile(path) as archive:
            patches.extend(read(archive, n) for n in archive.namelist()
                           if re.fullmatch(r'libs/tables/item/item(?:__[^/]+)?\.xml', n, re.I))
    return patches


def package_root(path):
    path = Path(path)
    for candidate in (path, path / 'map'):
        if (candidate / TRAVEL).is_file():
            return candidate
    raise ValueError('No package (Data/gluemappertravel.pak) at ' + str(path))


def quest_checks(package, kcd1, kcd2):
    """One row per ported quest. Reads only; raises nothing for a failed check, only for unreadable inputs."""
    from campaign_sources import RetailSourceReader
    from dialogue_facials import INDEX, chunks, header_path
    from dialogue_dubbing import DEPOT
    from upgrade_map import read
    from world_item_definitions import native_items
    import quest_lowering_report as lowering
    package, kcd1, kcd2 = package_root(package), Path(kcd1), Path(kcd2)
    with zipfile.ZipFile(package / TRAVEL) as archive:
        names = archive.namelist()
        resources = {n: read(archive, n) for n in names if n.startswith('Quests/') and n.endswith('.xml')}
        tables = {n: read(archive, n) for n in names if n.startswith('Libs/Tables/') and n.endswith('.xml')}
        marker = json.loads(read(archive, MARKER)) if MARKER in names else None
    with zipfile.ZipFile(kcd2 / 'Data/Tables.pak') as archive:
        retail_tables = {n: read(archive, n) for n in archive.namelist()
                         if re.fullmatch(r'libs/tables/rpg/(?:money_change|reputation_change|factiontree)(?:__[^/]+)?\.xml', n, re.I)}
    with zipfile.ZipFile(kcd2 / 'Data/IPL_GameData.pak') as archive:
        definitions = Definitions(read(archive, DEFINITIONS))
    all_tables = list(retail_tables.values()) + [b for n, b in tables.items()
        if re.fullmatch(r'Libs/Tables/rpg/(?:money_change|reputation_change|FactionTree)(?:__[^/]+)?\.xml', n)]
    rewards = dict(money_change=table_rows(all_tables, 'money_change'),
                   reputation_change=table_rows(all_tables, 'reputation_change'),
                   factions={n for b in all_tables for n in (f.get('Name') for f in ET.fromstring(b).iter('Faction')) if n})
    with zipfile.ZipFile(package / LEVEL_PAK) as archive:
        level = (ET.fromstring(read(archive, 'objects_mission0.xml')), ET.fromstring(read(archive, 'whdata_0')),
                 ET.fromstring(read(archive, 'tables/ai/scheduler.xml')))
    text = {}
    for locale in (kcd2 / 'Localization/English_xml.pak', package / ENGLISH_XML):
        with zipfile.ZipFile(locale) as archive:
            for member in ('text_ui_items.xml', 'text_ui_quest.xml', 'text_ui_dialog.xml'):
                if member in archive.namelist():
                    text.setdefault(member, {}).update(string_rows(read(archive, member)))
    items = native_items(kcd2, package_item_patches(package))
    item_names = {k: text['text_ui_items.xml'].get(row.get('UIName') or '') for k, row in items.items()}
    with zipfile.ZipFile(package / ENGLISH) as archive:
        audio = [n for n in archive.namelist() if n.lower().startswith('dialog/') and n.lower().endswith('.ogg')]
        depot = read(archive, DEPOT)
    dubbing = {m.decode() for m in re.findall(rb'FileHash="(\d+)"', depot)}
    with zipfile.ZipFile(package / FACIALS) as archive:
        facial_paths = {header_path(r).lower() for r in chunks(read(archive, INDEX))}
    with zipfile.ZipFile(kcd2 / 'Data/Tables.pak') as archive:
        voice_blobs = [read(archive, n) for n in archive.namelist() if re.fullmatch(r'libs/tables/skald/voice(?:__[^/]+)?\.xml', n, re.I)]
    voices = {v.get('voice_technical_name') for b in voice_blobs + [b for n, b in tables.items()
              if re.fullmatch(r'Libs/Tables/skald/voice(?:__[^/]+)?\.xml', n)] for v in ET.fromstring(b).iter('voice')}
    recordings = {}
    for member in audio:
        parts = member.lower().split('/')
        recordings.setdefault(parts[-2], {})[parts[-1][:-4]] = member
    with RetailSourceReader(kcd1) as reader:
        amounts = dict(money={r['name']: r['change'] for r in lowering.source_rows(reader, kcd1, 'quest/money_change')},
                       reputation={r['name']: r['change'] for r in lowering.source_rows(reader, kcd1, 'rpg/reputation_change')})
    rows = []
    for row in QUESTS:
        name = row['quest']
        result = dict(quest=name, namespace=row['namespace'], problems=[], info=[])
        rows.append(result)
        problems = result['problems']
        entry = (marker or {}).get('quests', {}).get(name)
        if entry is None:
            problems.append('the quest is not ported: no entry in ' + MARKER)
            result['status'] = 'fail'
            continue
        if entry['selection'] != selection_digest(row):
            problems.append('the selection changed since the quest was ported')
        with RetailSourceReader(kcd1) as reader:
            model = source_model(kcd1, name, reader)
        alias = lowering.soul_alias(entry['evidence']['person'])
        quest_path = FOLDER + name + '.xml'
        dialogues = entry['dialogues']
        stubs = [FOLDER + q + '.xml' for q in sorted(row['prerequisites'])] + [FOLDER + HOST + '.xml']
        dialogue_paths = [DIALOGUE_FOLDER + d + '.xml' for d in dialogues]
        for path in (quest_path, *stubs, *dialogue_paths, ENTRY, PROJECT):
            if path not in resources:
                problems.append('missing ' + path)
        if problems:
            result['status'] = 'fail'
            continue
        owned = {name, HOST, *row['prerequisites'], *dialogues}
        owned.update(n.get('Name') for n in host_of_blob(resources[ENTRY]).iterfind('Nodes/*')
                     if any(n.get('Name', '').startswith('lowered_delivery_' + d + '_') for d in dialogues))
        result['npc'] = dict(person=entry['evidence']['person'], problems=npc_audit(level, resources, entry['evidence'], alias))
        problems.extend('npc: ' + p for p in result['npc']['problems'])
        graph = graph_audit(resources, [quest_path, *stubs, *dialogue_paths, ENTRY], owned, definitions, aliases_of(resources))
        result['graph'] = dict(nodes=graph['nodes'], edges=graph['edges'], unchecked=graph['unchecked'])
        problems.extend('graph: ' + p for p in graph['problems'])
        for path, d in zip(dialogue_paths, dialogues):
            problems.extend('graph: ' + p for p in dialogue_audit(resources[path], d))
        tracking, found = tracking_audit(resources[quest_path], model, item_names)
        result['tracking'] = tracking
        problems.extend(found)
        tracked = expected_descriptors(model)
        result['delivery'] = dict(groups=[g['name'] for d in entry['delivery'] for g in d['groups']],
                                  sites=[s for d in entry['delivery'] for s in d['sites']])
        problems.extend(delivery_audit(resources, name, model, entry['delivery'], tracked))
        used, found = reward_audit(resources[quest_path], rewards, aliases_of(resources), amounts)
        result['rewards'] = dict(elements=len(used), pending=entry['report']['pending'])
        problems.extend(found)
        if sorted(entry['report']['pending']) != sorted(row['accepted_pending']):
            problems.append('pending rewards %r differ from the accepted set' % (entry['report']['pending'],))
        lines = 0
        for path, d in zip(dialogue_paths, dialogues):
            count, found = dialogue_media_audit(resources[path], d, text['text_ui_dialog.xml'], recordings, dubbing,
                                                facial_paths, voices)
            lines += count
            problems.extend(found)
        result['dialogue'] = dict(lines=lines)
        count, found = journal_audit(resources[quest_path], resources[PROJECT], text['text_ui_quest.xml'])
        result['journal'] = dict(strings=count)
        problems.extend(found)
        for path, digest in sorted(entry.get('hashes', {}).items()):
            if path in resources and hashlib.sha256(resources[path]).hexdigest() != digest and path != ENTRY:
                result['info'].append('%s changed after the port (a later stage rewrote it)' % path)
        result['status'] = 'fail' if problems else 'pass'
    return rows


def write_checks(rows, out, package):
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    with open(out / 'quests.jsonl', 'w', encoding='utf-8') as handle:
        for row in rows:
            handle.write(json.dumps(row, default=str) + '\n')
    counts = {}
    for row in rows:
        counts[row['status']] = counts.get(row['status'], 0) + 1
    lines = ['# KCD1 quest virtual test', '', 'Package: `%s`' % package, '',
             '%d quests: %s' % (len(rows), ', '.join('%s %d' % kv for kv in sorted(counts.items()))), '',
             '| quest | NPC | graph nodes | tracked | handlers | dialogue lines | status | problems |',
             '|---|---|---|---|---|---|---|---|']
    for row in rows:
        lines.append('| %s | %s | %s | %s | %s | %s | %s | %s |' % (
            row['quest'], 'ok' if row.get('npc') and not row['npc']['problems'] else 'check',
            row.get('graph', {}).get('nodes', ''), len(row.get('tracking', ())),
            len(row.get('delivery', {}).get('groups', ())), row.get('dialogue', {}).get('lines', ''),
            row['status'], '; '.join(row['problems']).replace('|', '/')[:240]))
    (out / 'QUESTS.md').write_text('\n'.join(lines) + '\n', encoding='utf-8')
    return counts


def check_main(args):
    rows = quest_checks(args.check, args.kcd1, args.kcd2)
    counts = write_checks(rows, args.out, args.check)
    for row in rows:
        print(row['status'].upper().ljust(5), row['quest'], '; '.join(row['problems'])[:300], flush=True)
    print('done:', counts)
    return 1 if any(r['status'] != 'pass' for r in rows) or not rows else 0


# ---------------------------------------------------------------- command line

def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--kcd1', type=Path, default=Path(os.environ.get('GLUEMAPPER_KCD1', KCD1_DEFAULT)))
    parser.add_argument('--kcd2', type=Path, default=Path(os.environ.get('GLUEMAPPER_KCD2', KCD2_DEFAULT)))
    modes = parser.add_mutually_exclusive_group(required=True)
    modes.add_argument('--plan', action='store_true', help='Run the stage in memory against retail and print a summary')
    modes.add_argument('--check', type=Path, metavar='PACKAGE', help='Read-only audit of a built package or its map folder')
    modes.add_argument('--lab', type=Path, metavar='DIR', help='Write the quest_lab graph and scenarios to a fresh folder')
    parser.add_argument('--package', type=Path, help='--plan: read this package instead of a synthetic container')
    parser.add_argument('--output', type=Path, help='--plan: write the full report as JSON')
    parser.add_argument('--out', type=Path, default=Path('quest-checks'), help='--check: folder for quests.jsonl and QUESTS.md')
    args = parser.parse_args(argv)
    if args.plan:
        report = plan(args.kcd1, args.kcd2, args.package)
        if args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(json.dumps(report, indent=2, default=str), encoding='utf-8')
        print(json.dumps(summary(report), indent=2))
        for name, reason in report.get('skipped', {}).items():
            print('skipped ' + name + ': ' + reason)
        return 0
    if args.lab:
        from campaign_sources import RetailSourceReader
        for row in QUESTS:
            with RetailSourceReader(args.kcd1) as reader:
                model = source_model(args.kcd1, row['quest'], reader)
            directory = args.lab / row['quest'] if len(QUESTS) > 1 else args.lab
            blobs = None
            if args.package:
                blobs = {}
                resources = read_travel(args.package / TRAVEL if (args.package / TRAVEL).is_file()
                                        else args.package / 'map' / TRAVEL, ('Quests/GlueTravel/',))
                for path, blob in resources.items():
                    if path.startswith(FOLDER) or path == PROJECT:
                        blobs[path.removeprefix('Quests/')] = blob
            paths = write_lab(model, directory, order=row['lab_order'], blobs=blobs, prerequisites=row['prerequisites'])
            print(json.dumps([str(p) for p in paths], indent=2))
        return 0
    return check_main(args)


if __name__ == '__main__':
    raise SystemExit(main())
