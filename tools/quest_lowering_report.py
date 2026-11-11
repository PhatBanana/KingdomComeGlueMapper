"""Developer report: emitter `unsupported` records before and after the lowerings.

Reads retail KCD1 and KCD2 only; installs nothing and is never imported by
Setup. Two binding modes are reported side by side:

    native    only names that exist in retail KCD2 (plus --mod item patches)
    assumed   every source soul, faction, item and change row the quest
              references is treated as registered by the package, and each
              assumption that was used is listed under `needs_registration`

`assumed` shows what the adapters can lower once the package registers those
records. It is a projection, not a build result, and nothing is runtime-proven.

  python tools/quest_lowering_report.py --kcd1 <dir> --kcd2 <dir> --quest a_huntsman_alex
      [--with q_other ...] [--mod <mod dir>] [--output report.json]
"""
import argparse
from collections import Counter
import copy
import json
from pathlib import Path
import re
import xml.etree.ElementTree as ET
import zipfile

from campaign_quest_rewards import KCD1_VALUE_PREFIX

FACTION_LEAF = 'gluemapper_kcd1_faction_'       # character_factions.LEAF
STATS = {'prg', 'spc', 'vit', 'str', 'agi'}


def source_rows(reader, game, path):
    record = reader(game, {'t': ('Tables.pak', 'Libs/Tables/' + path + '.xml')})['t']
    return [dict(r.attrib) for r in ET.fromstring(record['data']).findall('./table/rows/row')]


def target_names(game, table, attribute='name'):
    from upgrade_map import read
    with zipfile.ZipFile(Path(game) / 'Data/Tables.pak') as archive:
        names = {n.lower(): n for n in archive.namelist()}
        data = read(archive, names['libs/tables/rpg/' + table + '.xml'])
    return {e.get(attribute) for e in ET.fromstring(data).iter(table) if e.get(attribute)}


def source_models(game, quests, reader):
    """Emitter models for the named quests, built like quest_lab.source_audit."""
    from campaign_sources import key
    from quest_import import parse_graph, resolve_null_tracking_edges
    with zipfile.ZipFile(Path(game) / 'Data/Tables.pak') as archive:
        names = [n for n in archive.namelist() if key(n).startswith('libs/tables/quest/') and key(n).endswith('.xml')]
    tables = {}
    for path in names:
        record = reader(game, {'table': ('Tables.pak', path)})['table']
        table = ET.fromstring(record['data']).find('table')
        tables[table.get('name')] = dict(rows=[dict(r.attrib) for r in table.findall('./rows/row')],
            columns=[dict(c.attrib) for c in table.findall('./header/column')], provenance=record['candidates'])
    identities = {r['quest_name']: r['quest_id'] for r in tables['quest']['rows']}
    models = []
    for name in quests:
        identity = identities[name]
        graph = parse_graph(reader(game, {'graph': ('GameData.pak', 'Libs/quests/flowgraphs/' + name + '.xml')})['graph']['data'], name)
        selected = {n: dict(rows=[copy.deepcopy(r) for r in t['rows'] if r.get('quest_id') == identity],
                            columns=t['columns'], provenance=t['provenance']) for n, t in tables.items()}
        resolve_null_tracking_edges(graph, selected)
        models.append(dict(quest=name, quest_id=identity, tables=selected, graph=graph))
    return models


def soul_alias(name):
    return 'gm_soul_' + re.sub(r'[^A-Za-z0-9_]', '_', name)


def build_bindings(models, source, target, assume, player_asset='player', policies=None):
    """Bindings for `campaign_quest_lowerings.lower` from source and target tables."""
    registered = {k: set(v) for k, v in target['registered'].items()}
    items = {k.lower(): v for k, v in target['item_map'].items()}
    registered_items = {i.lower() for i in target['registered_items']}
    bindings = dict(player_asset=player_asset, item_categories=source['item_categories'], soul_assets={},
        factions={}, money_changes={}, reputation_changes={}, exp_changes={}, exp_targets={}, perks={},
        policies=dict(policies or {}))
    for kind, names in (('reputation_changes', source['reputation']), ('exp_changes', source['exp']),
                        ('money_changes', source['money'])):
        table = dict(reputation_changes='reputation_change', exp_changes='xp_change', money_changes='money_change')[kind]
        for identity, name in names.items():
            if kind != 'exp_changes':
                # KCD1 values (Sean, 11-11): always the 'kcd1_' row, which
                # campaign_quest_rewards.kcd1_value_tables writes with KCD1's number.
                bindings[kind][identity] = KCD1_VALUE_PREFIX + name; registered[table].add(KCD1_VALUE_PREFIX + name)
            elif name in registered[table]:
                bindings[kind][identity] = name
            elif assume:
                bindings[kind][identity] = 'kcd1_' + name; registered[table].add('kcd1_' + name)
    if assume:
        for model in models:
            t = model['tables']
            for row in t.get('quest_npc', {}).get('rows', []) + t.get('quest_reward_reputation', {}).get('rows', []):
                soul = (row.get('soul_id') or '').lower()
                if soul: bindings['soul_assets'][soul] = soul_alias(source['souls'].get(soul, soul))
                if row.get('faction_id'):
                    bindings['factions'][row['faction_id']] = FACTION_LEAF + row['faction_id']
                    registered['faction'].add(FACTION_LEAF + row['faction_id'])
            for row in t.get('quest_item', {}).get('rows', []) + t.get('quest_reward_item', {}).get('rows', []):
                item = (row.get('item_id') or '').lower()
                if item and item not in items:
                    items[item] = item; registered_items.add(item)
            for row in t.get('quest_reward_exp', {}).get('rows', []):
                attr = row.get('rpg_attr', '')
                bindings['exp_targets'][attr] = ('StatReward' if attr in STATS else 'SkillReward', 'ASSUMED_' + attr)
                registered['xp_target'].add('ASSUMED_' + attr)
            for row in t.get('quest_reward_perk', {}).get('rows', []):
                bindings['perks'][row['perk_id']] = 'ASSUMED_' + row['perk_id']
                registered['perk'].add('ASSUMED_' + row['perk_id'])
    bindings.update(item_map=items, registered_items=sorted(registered_items),
                    registered={k: sorted(v) for k, v in registered.items()})
    return bindings


def needs_registration(lowerings, native):
    """Assumed names a converted record relies on that retail KCD2 does not provide."""
    needed = set()
    for record in lowerings['tracking']['converted']:
        for req in record['requirements']:
            if req['kind'] == 'npc_death': needed.add(('soul_asset', req['soul_asset'], req['source_soul']))
            elif req['target_item'] not in native['registered_items']: needed.add(('item', req['target_item'], req['source_item']))
    for group in lowerings['rewards']['converted']:
        for reward in group['rewards']:
            n, row = reward['native'], reward['source']
            if n['tag'] == 'MoneyReward' and n['Amount'] not in native['registered']['money_change']:
                needed.add(('money_change', n['Amount'], row['money_change_id']))
            if n['tag'].endswith('ReputationReward'):
                if n['ReputationChange'] not in native['registered']['reputation_change']:
                    needed.add(('reputation_change', n['ReputationChange'], row['reputation_change_id']))
                needed.add(('soul_asset', n['Target'], row['soul_id'].lower()) if n['tag'].startswith('Soul')
                           else ('faction', n['Target'], row['faction_id']))
            if n['tag'] == 'ItemReward' and n['ItemClass'] not in native['registered_items']:
                needed.add(('item', n['ItemClass'], row['item_id'].lower()))
            if n['tag'] in ('StatReward', 'SkillReward'): needed.add(('xp_target', n['Type'], row.get('rpg_attr')))
            if n['tag'] == 'PerkReward': needed.add(('perk', n['Perk'], row['perk_id']))
    return [dict(kind=k, target=t, source=s) for k, t, s in sorted(needed)]


def load_context(kcd1, kcd2, mod=None):
    from campaign_sources import RetailSourceReader
    from quest_lab.item_bindings import installed
    kcd1 = Path(kcd1)
    with RetailSourceReader(kcd1) as reader:
        source = dict(
            money={r['money_change_id']: r['name'] for r in source_rows(reader, kcd1, 'quest/money_change')},
            exp={r['exp_change_id']: r['name'] for r in source_rows(reader, kcd1, 'quest/exp_change')},
            reputation={r['reputation_change_id']: r['name'] for r in source_rows(reader, kcd1, 'rpg/reputation_change')},
            money_amounts={r['name']: r['change'] for r in source_rows(reader, kcd1, 'quest/money_change')},
            reputation_amounts={r['name']: r['change'] for r in source_rows(reader, kcd1, 'rpg/reputation_change')},
            souls={r['soul_id'].lower(): r['soul_name'] for r in source_rows(reader, kcd1, 'rpg/soul')},
            item_categories={r['item_id'].lower(): r['item_category_id'] for r in source_rows(reader, kcd1, 'item/item')})
    native_items = installed(kcd2, mod, 'player')
    target = dict(item_map=native_items['item_map'], registered_items=native_items['registered'],
        registered=dict(money_change=target_names(kcd2, 'money_change'),
                        reputation_change=target_names(kcd2, 'reputation_change'),
                        xp_change=target_names(kcd2, 'xp_change'), xp_target=set(), faction=set(), perk=set()))
    return source, target


def report(kcd1, kcd2, quests, with_quests=(), mod=None, policies=None, context=None):
    from campaign_quest_graph import emit_project
    from campaign_quest_lowerings import lower
    from campaign_sources import RetailSourceReader
    source, target = context or load_context(kcd1, kcd2, mod)
    with RetailSourceReader(Path(kcd1)) as reader:
        models = source_models(Path(kcd1), [*quests, *with_quests], reader)
    files, emitted = emit_project(models, 'QuestLoweringReport')
    native = dict(registered_items={i.lower() for i in target['registered_items']},
                  registered={k: set(v) for k, v in target['registered'].items()})
    result = dict(quests=[], compiled_with=list(with_quests), policies=dict(policies or {}),
                  installed=False, runtime_verified=False)
    runs = {assume: lower(files, emitted, models, build_bindings(models, source, target, assume, policies=policies))[1]
            for assume in (False, True)}
    for index, quest in enumerate(emitted['quests']):
        if quest['quest'] not in quests: continue
        strict, assumed = runs[False]['quests'][index], runs[True]['quests'][index]
        result['quests'].append(dict(quest=quest['quest'],
            before=dict(Counter(r['kind'] for r in quest['unsupported'])), before_total=len(quest['unsupported']),
            after_native=dict(Counter(r['kind'] for r in strict['unsupported'])), after_native_total=len(strict['unsupported']),
            after_assumed=dict(Counter(r['kind'] for r in assumed['unsupported'])), after_assumed_total=len(assumed['unsupported']),
            remaining_assumed=assumed['unsupported'], resolved_assumed=assumed['lowerings']['resolved'],
            pending_native=dict(tracking=strict['lowerings']['tracking']['pending'],
                                policy=strict['lowerings']['policy']['pending'],
                                rewards=Counter(p['reason'] for p in strict['lowerings']['rewards']['pending'])),
            presentation=assumed['lowerings']['tracking']['presentation'],
            needs_registration=needs_registration(assumed['lowerings'], native),
            source_amounts=dict(
                money={n: source['money_amounts'].get(n) for n in {source['money'].get(r['money_change_id'])
                       for r in models[index]['tables'].get('quest_reward_money', {}).get('rows', [])}},
                reputation={n: source['reputation_amounts'].get(n) for n in {source['reputation'].get(r['reputation_change_id'])
                            for r in models[index]['tables'].get('quest_reward_reputation', {}).get('rows', [])}})))
    return result


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('--kcd1', type=Path, required=True)
    p.add_argument('--kcd2', type=Path, required=True)
    p.add_argument('--quest', nargs='+', required=True)
    p.add_argument('--with', dest='with_quests', nargs='*', default=[],
                   help='Quests compiled together so cross-quest predicates can bind')
    p.add_argument('--mod', type=Path, help='Also read item definitions from this mod')
    p.add_argument('--deferred-rewards', choices=['quest_done'])
    p.add_argument('--omit-achievements', action='store_true')
    p.add_argument('--output', type=Path)
    a = p.parse_args()
    policies = {}
    if a.deferred_rewards: policies['deferred_rewards'] = a.deferred_rewards
    if a.omit_achievements: policies['achievements'] = 'omit'
    result = report(a.kcd1, a.kcd2, a.quest, a.with_quests, a.mod, policies)
    if a.output:
        a.output.parent.mkdir(parents=True, exist_ok=True)
        a.output.write_text(json.dumps(result, indent=2, default=str), encoding='utf-8')
    for q in result['quests']:
        print(json.dumps(dict(quest=q['quest'], before=q['before_total'], after_native=q['after_native_total'],
            after_assumed=q['after_assumed_total'], before_kinds=q['before'], after_native_kinds=q['after_native'],
            after_assumed_kinds=q['after_assumed'], needs_registration=len(q['needs_registration']))))
    return 0


if __name__ == '__main__': raise SystemExit(main())
