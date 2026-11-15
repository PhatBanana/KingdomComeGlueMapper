"""Census of KCD1 town garrisons (sa_garrison smart areas) and their static guard allocation.

KCD1 has no garrison table: Scripts.pak Libs/AI/final/sa_garrison.xml gives the
first free workplace in list order (important first) to the nearest available
guard, who holds it for the work interval. This census replays that rule over
the guards' daycycles and freezes one KCD1 day per guard: the post (or patrol
start) and the segments. The guard stage (setup_garrison_population) turns each
post into the guard's garrison_forcedWorkplace, KCD1's own override link.
Design and evidence: issues/npcs/GARRISON-DESIGN.md.

  python garrison_census.py --source KCD1 --town rattay --out rattay-garrisons.json
                            [--module tools/garrison_selection.py] [--fresh]

Stages (resumable; each prints progress and is cached under <out stem>.progress/):
  1 garrisons.json  smart areas, workplaces, patrol graphs, idle spots
  2 guards.jsonl    one row per NPC whose Work link targets a garrison
  3 beds.json       home bed candidates per guard (repo sleep catalog)
  4 allocation      simulated from 1-3 on every run (cheap), then the JSON is written

What the bytes prove and what is inferred is listed under "assumptions" in the output.
"""
import argparse, json, math, re, sys, zipfile
from collections import Counter, defaultdict
from pathlib import Path
import xml.etree.ElementTree as E

GARRISON_TEMPLATE = 'sa_garrison'
TREE = ('final/sa_garrison.xml', 'Guard')
# preprocessWorkplaces: default equipment per workplace behaviour when the point sets none.
DEFAULT_EQUIPMENT = {'patrolWalls': 'bow_and_sword', 'guardPlace': 'halberd', 'patrolStreets': 'sword_and_shield'}
# Quest messages that flip a named workplace (Scripts.pak Libs/AI/quests/*.xml, garrison:setWorkplaceState).
QUEST_STATES = {
    'post_q_awakeningInRattay': {'garrison': 'sa_pirk_garrison', 'enable': ['pirkGate1', 'pirkGate2'],
        'evidence': "Libs/AI/quests/q_awakeningInRattay.xml: InstantSendMessageToNPC target=garrisonPirk "
                    "type=garrison:setWorkplaceState values=name('pirkGate1'|'pirkGate2'), enabled(true) after cutscene meet_radzig"},
}
SIM_DAYS = 40
ASSUMPTIONS = [
    "ORDER (inferred): GraphSearch over the area's guardPlace links returns them in the order the links are "
    "stored on the SmartAreaShape entity in objects_mission0.xml. preprocessWorkplaces then PushFront()s important "
    "points and PushBack()s the rest, so kcd1_order = reversed(important in link order) + others in link order. "
    "Test without a rebuild, in KCD1 itself: around 23:00 tp_rat_garrison2_guardplace (2579.6,648.8) is manned and both "
    "sa_rat_garrison2 wall walks have a walker; around 12:00 all three are empty. Ordering by entity id instead would "
    "leave the guardplace empty at night. A KCD1 save also stores t_garrisonWorkplaces (isPersistent=1).",
    "NEAREST (proved rule, approximated inputs): the allocator gives the first free workplace to the nearest "
    "available guard (RangeSorter Ascending on the workplace point). Guard positions at that moment are runtime "
    "state; the simulation uses the primary bed (or home) for a guard whose previous daycycle activity was sleep or "
    "morning, and the garrison idle spot for everyone else.",
    "IDLE (approximated): guardIdle sends a guard without a halberd to a random idleBench; the simulation puts idle "
    "guards at the centroid of the idle benches (else the first 'inside' point, else the area origin).",
    "EVENTS: a guard is available from the minute its daycycle enters work until it leaves; at the same minute ends "
    "are processed before starts; distance ties break on soul name. Daycycle TimeVariation, travel time, combat, "
    "death, crime response and quest injectBehavior/boost are not simulated.",
    "PERIODIC: where the exact simulation repeats daily it is used as is (method exact_periodic). Where it does not "
    "(more guards than posts with unequal shifts: the posts left empty at night rotate from day to day in KCD1), "
    "method night_homes_by_priority pins each night guard to the post the allocator gives it on a cold start and "
    "simulates everyone else exactly. KCD1 has no stable guard-to-post mapping there; this is one self-consistent day.",
    "BEDS: KCD1 reserves a bed at runtime (sa_home Sleeper, quality-sorted, preferedSleeper first). The primary bed "
    "here is the best repo sleep candidate not taken by a guard whose sleep hours overlap.",
]


def tokens(label):
    """Split a KCD1 link name into (tag, data) pairs: "guardPlace[('patrolWalls')],ignorePatrol"."""
    out, depth, cur = [], 0, ''
    for ch in label or '':
        if ch == '[': depth += 1
        if ch == ']': depth -= 1
        if ch == ',' and depth == 0:
            out.append(cur); cur = ''
        else:
            cur += ch
    out.append(cur)
    result = []
    for tok in out:
        tok = tok.strip()
        if not tok: continue
        m = re.fullmatch(r'([^\[]+)\[(.*)\]', tok)
        result.append((m.group(1).strip(), m.group(2).strip(" ()'\"")) if m else (tok, None))
    return result


def misc(entity):
    script = entity.find('Properties/Script')
    text = script.get('Misc', '') if script is not None else ''
    return dict(p.split(':', 1) for p in text.split('|') if ':' in p)


def truth(value):
    return str(value).lower() == 'true'


def minutes(m):
    m %= 1440
    return f'{m // 60:02d}:{m % 60:02d}'


def stage_source(args, cache):
    """Stages 1-3: everything that needs the KCD1 archives."""
    from campaign_sources import RetailSourceReader
    from campaign_dependency_adapters import SourceTables
    from build_profile_systems import source_world
    from campaign_profile_actors import select
    from character_person_ai import capture_person_ai, index_person_links
    from character_schedule import plan
    from entity_visuals import world_transform
    from resident_census import town_of
    from upgrade_map import read
    garrisons_path, guards_path, beds_path = cache/'garrisons.json', cache/'guards.jsonl', cache/'beds.json'
    print('[load] opening KCD1 level (objects_mission0 + layers, about 3 minutes)', flush=True)
    with RetailSourceReader(args.source) as reader:
        tables = SourceTables(args.source, reader)
        with zipfile.ZipFile(args.source/'Data/Levels/rataje/level.pak') as z:
            documents, entities = source_world(z)
            souls = E.fromstring(read(z, 'whdata_0')); profiles = E.fromstring(read(z, 'whdata_1'))
            mission = {e.get('EntityId'): e for e in E.fromstring(documents['objects_mission0.xml']).iter('Entity')}
            print(f'[load] {len(documents)} documents, {len(entities)} entities, {len(mission)} in objects_mission0', flush=True)
            template = [r for r in tables.get('ai/sa_smart_area')['rows'] if r['sa_smart_area_name'] == GARRISON_TEMPLATE]
            if len(template) != 1: raise ValueError('sa_garrison template row')
            template_id = template[0]['sa_smart_area_id']

            def pose(e):
                pos, rot, _ = world_transform(e, mission)
                return dict(name=e.get('Name'), entity_id=e.get('EntityId'), entity_guid=e.get('EntityGuid'),
                            entity_class=e.get('EntityClass'), pos=[round(v, 4) for v in pos],
                            rotate=[round(v, 6) for v in rot])

            def target(link):
                t = mission.get(link.get('TargetId'))
                if t is None: raise ValueError('garrison link leaves objects_mission0: ' + repr(link.attrib))
                return t

            def category(e):
                p = e.find('Properties')
                return p.get('sWH_AI_EntityCategory', '') if p is not None else ''

            # ---- stage 1
            if garrisons_path.exists():
                garrisons = json.loads(garrisons_path.read_text(encoding='utf-8'))
                print(f'[1/3] garrisons: cached ({len(garrisons)})', flush=True)
            else:
                garrisons = []
                areas = [e for e in mission.values() if e.get('EntityClass') == 'SmartAreaShape' and e.find('Properties') is not None
                         and e.find('Properties').get('guidSmartAreaTemplate') == template_id]
                mission_guids = {e.get('EntityGuid') for e in mission.values()}
                layer_areas = sorted({e.get('Name') for e in entities if e.get('EntityClass') == 'SmartAreaShape'
                               and e.find('Properties') is not None and e.get('EntityGuid') not in mission_guids
                               and e.find('Properties').get('guidSmartAreaTemplate') == template_id})
                print(f'[1/3] {len(areas)} sa_garrison areas in objects_mission0, {len(layer_areas)} only in layers {layer_areas}', flush=True)
                for area in sorted(areas, key=lambda e: e.get('Name')):
                    info = pose(area)
                    if town_of(tuple(info['pos'][:2])) not in args.town: continue
                    props = misc(area)
                    g = dict(info, town=town_of(tuple(info['pos'][:2])), script=props, enable_frisk=truth(props.get('enableFrisk')),
                             equipment_set=props.get('equipment', ''), workplaces=[], inside=[], outside=[], idle_benches=[],
                             armory=dict(stashes=[], item_slots=0), other_links=[])
                    for index, link in enumerate(area.findall('EntityLinks/Link')):
                        t = target(link); tags = dict(tokens(link.get('Name')))
                        if 'guardPlace' in tags:
                            g['workplaces'].append(workplace(index, link, t, tags, pose, target, category))
                        elif 'inside' in tags: g['inside'].append(pose(t))
                        elif 'outside' in tags: g['outside'].append(pose(t))
                        elif 'idleBench' in tags:
                            g['idle_benches'].append(dict(pose(t), tags=sorted(tags), category=category(t)))
                        elif t.get('EntityClass') == 'ItemSlot': g['armory']['item_slots'] += 1
                        elif t.get('EntityClass') == 'Stash': g['armory']['stashes'].append(dict(pose(t), category=category(t)))
                        else: g['other_links'].append(dict(pose(t), label=link.get('Name'), category=category(t)))
                    # preprocessWorkplaces: important -> PushFront, else PushBack
                    order = []
                    for w in g['workplaces']:
                        order.insert(0, w) if w['important'] else order.append(w)
                    for rank, w in enumerate(order): w['kcd1_order'] = rank
                    garrisons.append(g)
                    print(f"[1/3] {g['name']}: {len(g['workplaces'])} workplaces "
                          f"{dict(Counter(w['kind'] for w in g['workplaces']))}, {len(g['idle_benches'])} idle benches", flush=True)
                garrisons_path.write_text(json.dumps(garrisons, indent=1), encoding='utf-8')

            # ---- stage 2
            done = {}
            if guards_path.exists():
                for line in guards_path.read_text(encoding='utf-8').splitlines():
                    row = json.loads(line); done[row['soul_name']] = row
            area_ids = {g['entity_id']: g['name'] for g in garrisons}
            soul_names = {int(s.findtext('EntityGuid')): s.findtext('Name')
                          for s in souls.findall('SoulList/Souls/Soul') if s.findtext('EntityGuid')}
            members = {}
            for e in entities:
                if e.get('EntityClass') not in ('NPC', 'NPC_Female') or not e.get('EntityGuid'): continue
                for link in e.findall('EntityLinks/Link'):
                    if link.get('TargetId') in area_ids and any(t in ('Work', 'futureWork') for t, _ in tokens(link.get('Name'))):
                        name = soul_names.get(int(e.get('EntityGuid'), 16))
                        if name is None: raise ValueError('garrison NPC without a soul: ' + e.get('Name', '?'))
                        members[name] = (area_ids[link.get('TargetId')], link.get('Name'))
            todo = sorted(n for n in members if n not in done)
            print(f'[2/3] {len(members)} NPCs link Work to a garrison; {len(todo)} to capture', flush=True)
            by_guid = {e.get('EntityGuid'): e for e in entities if e.get('EntityGuid')}
            instances = {s.findtext('Guid'): s for s in souls.findall('SoulList/Souls/Soul')}
            links = index_person_links(entities)
            people = {}
            with guards_path.open('a', encoding='utf-8') as out:
                for index, name in enumerate(sorted(members), 1):
                    record = select(profiles, souls, documents, [name])[0]
                    soul = tables.row('rpg/soul', 'soul_id', record['soul_id'])
                    person = dict(name=name, soul=soul, actor=by_guid[record['entity_guid']],
                                  instance=instances[record['instance_id']], source_level='rataje')
                    person['ai'] = ai = capture_person_ai(tables, soul, person['actor'], person['instance'], entities, links)
                    people[name] = person
                    if name in done: continue
                    schedule = plan(person, tables)
                    work = [dict(start=e['start_minute'], end=e['end_minute'], area=e['area']['Name'],
                                 tree=e['behavior']['tree_file'].replace('\\', '/').lower() + ':' + e['behavior']['tree_name'])
                            for e in schedule['resolved']]
                    home = [l for l in ai['links'] if (l['label'] or '').split(',')[0].strip() == 'Home']
                    faction = ai['faction_graph']['faction']
                    row = dict(soul_name=name, soul_id=record['soul_id'], entity_guid=record['entity_guid'],
                        layer=record['layer'], pos=[float(v) for v in person['actor'].get('Pos').split(',')],
                        garrison=members[name][0], work_link=members[name][1],
                        faction=dict(id=faction['faction_id'], name=faction['faction_name']),
                        social_class=ai['source_social_class']['social_class_name'], brain=ai['source_brain']['brain_name'],
                        daycycle=[dict(activity=s['activity'], start=s['start_minute']) for s in ai['schedule']],
                        resolved_work=work, pending=[p.get('activity') for p in schedule['pending']],
                        forced_workplace=[l['target'].get('Name') for l in ai['links'] if l['label'] == 'garrison_forcedWorkplace'],
                        links=[dict(label=l['label'], name=l['target'].get('Name'), entity_class=l['target'].get('EntityClass'),
                                    entity_id=l['target'].get('EntityId'), pos=l['target'].get('Pos')) for l in ai['links']],
                        home=dict(label=home[0]['label'], name=home[0]['target'].get('Name'), entity_id=home[0]['target'].get('EntityId'),
                                  pos=[float(v) for v in home[0]['target'].get('Pos').split(',')]) if len(home) == 1 else None)
                    out.write(json.dumps(row) + '\n'); out.flush(); done[name] = row
                    print(f'[2/3] {index}/{len(members)} {name}', flush=True)
            # ---- stage 3
            if beds_path.exists():
                print('[3/3] beds: cached', flush=True)
            else:
                from character_sleep_beds import catalog, candidates
                print('[3/3] scanning source beds (repo sleep catalog)', flush=True)
                records = catalog(z, tables, notify=lambda m: print('[3/3] ' + m, flush=True))
                beds = {}
                for name, person in sorted(people.items()):
                    try:
                        beds[name] = [dict(source_id=c['source_id'], name=records[c['source_id']]['entity'].get('Name'),
                                           kind=c['kind'], rank=c['rank'], pos=[round(v, 4) for v in c['position']],
                                           quality=records[c['source_id']]['quality'])
                                      for c in candidates(person, records)]
                    except ValueError as error:
                        beds[name] = dict(error=str(error))
                beds_path.write_text(json.dumps(beds, indent=1), encoding='utf-8')
                print(f'[3/3] bed candidates for {len(beds)} guards', flush=True)
    return template_id


def workplace(index, link, t, tags, pose, target, category):
    props = misc(t); kind = tags['guardPlace']
    w = dict(pose(t), link_index=index, link_label=link.get('Name'), kind=kind, tags=sorted(k for k in tags if k != 'guardPlace'),
             script=props, workplace_name=props.get('name', 'unnamed'), important=truth(props.get('important')),
             disabled=truth(props.get('disabled')), instant=truth(props.get('instant')),
             equipment=props.get('equipment') or DEFAULT_EQUIPMENT.get(kind, 'sword_and_shield'),
             equipment_authored='equipment' in props, disable_frisk=truth(props.get('disableFrisk')),
             angryness=float(props.get('angryness', -1)), is_gate=truth(props.get('isgate')))
    children = [(dict(tokens(l.get('Name'))), target(l)) for l in t.findall('EntityLinks/Link')]
    if kind == 'guardPlace':
        for key in ('secondary', 'rain', 'fortLook', 'area', 'gate'):
            found = [pose(c) for ctags, c in children if key in ctags]
            if len(found) > 1: raise ValueError('ambiguous ' + key + ' on ' + t.get('Name'))
            w[key] = found[0] if found else None
        seats = [dict(pose(c), category=category(c)) for ctags, c in children if 'Seat' in category(c).split(',')]
        w['bench'] = seats[0] if seats else None
        w['patrol'] = None
    elif kind == 'patrolWalls':
        # preprocessWorkplaces: TagPoints reachable within depth 15; every authored TagPoint edge becomes next/prev.
        seen, order, edges, queue = {t.get('EntityId')}, [t], [], [(t, 0)]
        while queue:
            node, depth = queue.pop(0)
            for l in node.findall('EntityLinks/Link'):
                c = target(l); ctags = dict(tokens(l.get('Name')))
                if c.get('EntityClass') != 'TagPoint' or 'prev' in ctags: continue
                edges.append(dict(src=node.get('Name'), dst=c.get('Name'), no_back_path='noBackPath' in ctags))
                if c.get('EntityId') not in seen and depth < 15:
                    seen.add(c.get('EntityId')); order.append(c); queue.append((c, depth + 1))
        fan = Counter(e['src'] for e in edges)
        w['patrol'] = dict(type='ping_pong_chain' if all(v == 1 for v in fan.values()) and not any(e['no_back_path'] for e in edges)
                           else 'branching', points=[pose(p) for p in order], edges=edges,
                           rule='walk next links to the end, then prev links back; RandomItem only where a point has several')
    elif kind == 'patrolStreets':
        pool = [pose(c) for ctags, c in children if c.get('EntityClass') == 'TagPoint' and 'forceNext' not in ctags]
        forced = [pose(c) for ctags, c in children if 'forceNext' in ctags]
        w['patrol'] = dict(type='nearest4_random_pool', points=[pose(t)] + pool, force_next=forced,
                           rule='from the start point: random among the 4 pool points nearest the guard, excluding the last 3 visited')
    else:
        w['patrol'] = None
    return w


def intervals(daycycle, activity):
    rows = sorted(daycycle, key=lambda r: r['start'])
    out = []
    for i, row in enumerate(rows):
        if row['activity'] == activity:
            end = rows[(i + 1) % len(rows)]['start']
            out.append((row['start'], end if end > row['start'] else end + 1440, rows[i - 1]['activity']))
    return out


def overlap(a, b):
    return any(a[0] + s < b[1] and b[0] < a[1] + s for s in (-1440, 0, 1440))


def choose_beds(guards, beds):
    taken = defaultdict(list); result = {}
    for g in sorted(guards, key=lambda r: r['soul_name']):
        options = beds.get(g['soul_name'])
        sleep = [(a, b) for a, b, _ in intervals(g['daycycle'], 'sleep')]
        choice = None
        if isinstance(options, list):
            for c in options:
                if c['kind'] == 'public_fallback': continue
                if not any(overlap(s, o) for s in sleep for o in taken[c['source_id']]):
                    choice = dict(c); taken[c['source_id']].extend(sleep); break
        result[g['soul_name']] = choice
    return result


def simulate(garrison, guards, bed_choice, enabled_names=()):
    """Run the allocator until the day repeats. 'nearest_then_sticky' keeps the proved nearest-guard rule and
    breaks distance ties (idle guards share one modelled position) toward the guard who last held that post;
    'sticky_then_nearest' is the fallback when the first mode never settles into a one-day cycle."""
    exact = simulate_mode(garrison, guards, bed_choice, enabled_names, 'nearest_then_sticky', {})
    if exact['period_days'] == 1:
        return dict(exact, method='exact_periodic')
    # KCD1's own mapping never repeats here (the posts left empty at night rotate). Freeze the night shift on
    # the allocator's cold-start result (first free post in list order to each guard as it comes on duty) and let
    # everyone else follow the exact rules around it.
    posts = sorted((w for w in garrison['workplaces'] if not w['disabled'] or w['workplace_name'] in enabled_names),
                   key=lambda w: w['kcd1_order'])
    night = sorted((g for g in guards if any(b > 1440 for a, b, _ in intervals(g['daycycle'], 'work'))),
                   key=lambda g: (min(a for a, b, _ in intervals(g['daycycle'], 'work') if b > 1440), g['soul_name']))
    homes = {g['soul_name']: w['name'] for g, w in zip(night, posts)}
    fixed = simulate_mode(garrison, guards, bed_choice, enabled_names, 'nearest_then_sticky', homes)
    return dict(fixed, method='night_homes_by_priority', night_homes=homes, exact_period_days=exact['period_days'])


def simulate_mode(garrison, guards, bed_choice, enabled_names, mode, homes):
    posts = sorted(garrison['workplaces'], key=lambda w: w['kcd1_order'])
    enabled = [w for w in posts if not w['disabled'] or w['workplace_name'] in enabled_names]
    spots = garrison['idle_benches'] or garrison['inside'][:1]
    idle = ([sum(s['pos'][i] for s in spots) / len(spots) for i in range(3)] if spots else garrison['pos'])
    home = {}
    for g in guards:
        bed = bed_choice.get(g['soul_name'])
        home[g['soul_name']] = bed['pos'] if bed else (g['home']['pos'] if g['home'] else g['pos'])
    events = []
    for g in guards:
        for start, end, previous in intervals(g['daycycle'], 'work'):
            for day in range(SIM_DAYS):
                events.append((start + day * 1440, 1, g['soul_name'], previous))
                events.append((end + day * 1440, 0, g['soul_name'], previous))
    events.sort()
    worker, available, where, since, segments, last_post = {}, set(), {}, {}, defaultdict(list), {}

    def rank(n, w):
        distance, fresh = round(math.dist(where[n], w['pos'])), last_post.get(n) != w['name']
        return (distance, fresh, n) if mode == 'nearest_then_sticky' else (fresh, distance, n)

    def allocate(now):
        while True:
            pick = None
            for w in enabled:
                if w['name'] in worker: continue
                owners = [n for n in available if homes.get(n) == w['name']]
                roamers = [n for n in available if n not in homes]
                if owners or roamers:
                    pick = (w, min(owners or roamers, key=lambda n: rank(n, w))); break
            if pick is None: return
            w, g = pick
            available.discard(g); worker[w['name']] = g; last_post[g] = w['name']
            if since[g] != now: segments[g].append([since[g], now, None])
            since[g] = now; where[g] = w['pos']
            segments[g].append([now, None, w['name']])

    i = 0
    while i < len(events):
        now = events[i][0]
        batch = []
        while i < len(events) and events[i][0] == now:
            batch.append(events[i]); i += 1
        for _, kind, name, previous in batch:
            if kind == 0 and name in since:
                held = [w for w, n in worker.items() if n == name]
                for w in held: del worker[w]
                if held: segments[name][-1][1] = now
                elif since[name] != now: segments[name].append([since[name], now, None])
                since.pop(name); available.discard(name)
        for _, kind, name, previous in batch:
            if kind == 1:
                available.add(name); since[name] = now
                where[name] = home[name] if previous in ('sleep', 'morning') else idle
        allocate(now)
        for name in available: where[name] = idle   # still waiting after this pass: at the idle spot

    def window(day):
        lo, hi = day * 1440, (day + 1) * 1440
        out = {}
        for name, rows in segments.items():
            cut = [(max(a, lo) - lo, min(b, hi) - lo, post) for a, b, post in rows if b is not None and a < hi and b > lo and a != b]
            out[name] = sorted(cut)
        return out
    final = window(SIM_DAYS - 2)
    period = next((k for k in range(1, SIM_DAYS // 2) if window(SIM_DAYS - 2 - k) == final), None)
    per_guard = {}
    for g in guards:
        merged = []
        for a, b, post in final.get(g['soul_name'], []):
            if merged and merged[-1]['post'] == post and merged[-1]['end_minute'] == a: merged[-1]['end_minute'] = b
            else: merged.append(dict(start_minute=a, end_minute=b, post=post))
        # join a segment cut by midnight
        if len(merged) > 1 and merged[0]['start_minute'] == 0 and merged[-1]['end_minute'] == 1440 and merged[0]['post'] == merged[-1]['post']:
            merged[-1]['end_minute'] = 1440 + merged[0]['end_minute']; merged.pop(0)
        for m in merged:
            m['start'], m['end'] = minutes(m['start_minute']), minutes(m['end_minute'])
        posted = [m for m in merged if m['post']]
        main = max(posted, key=lambda m: m['end_minute'] - m['start_minute'])['post'] if posted else None
        per_guard[g['soul_name']] = dict(segments=merged, primary_post=main,
            posted_minutes=sum(m['end_minute'] - m['start_minute'] for m in posted),
            idle_minutes=sum(m['end_minute'] - m['start_minute'] for m in merged if not m['post']))
    per_post = {}
    for w in posts:
        rows = sorted((m['start_minute'], m['end_minute'], n) for n, a in per_guard.items() for m in a['segments'] if m['post'] == w['name'])
        per_post[w['name']] = dict(kcd1_order=w['kcd1_order'], enabled=w in enabled,
            manned_minutes=sum(b - a for a, b, _ in rows),
            holders=[dict(start=minutes(a), end=minutes(b), soul=n) for a, b, n in rows])
    return dict(converged=period == 1, period_days=period, tie_break=mode, simulated_days=SIM_DAYS,
                per_guard=per_guard, per_post=per_post, idle_position=[round(v, 3) for v in idle])


# Garrison members another route already imports (12c base quest people). They
# stay in the simulation so the posts they hold in KCD1 are not given to others.
OTHER_ROUTES = frozenset({'rat_guardJanek', 'rat_guardJaroslav'})


def in_scope(row):
    """A garrison member the guard stage imports: no authored post, not imported by another route."""
    from resident_census import QUEST_PEOPLE, RESERVED
    return not row['forced_workplace'] and row['soul_name'] not in QUEST_PEOPLE | RESERVED | OTHER_ROUTES


def selection_module(result):
    """Source of tools/garrison_selection.py: one record per in-scope guard."""
    workplaces = {w['name']: w for g in result['garrisons'] for w in g['workplaces']}
    garrisons = {g['name']: g for g in result['garrisons']}
    guards = {}
    for row in result['static_allocation']:
        if not row['in_scope']:
            continue
        w = workplaces.get(row['post'])
        guards[row['soul']] = dict(
            garrison=row['garrison'], garrison_guid=garrisons[row['garrison']]['entity_guid'],
            state=row['state'], method=row['method'], soul_id=row['soul_id'],
            faction_id=row['faction_id'], shift=row['shift'], work=row['work'], segments=row['segments'],
            role=row['role'], post=row['post'], post_guid=w['entity_guid'] if w else None,
            post_pos=w['pos'] if w else None, post_kind=row['post_kind'],
            kcd1_order=w['kcd1_order'] if w else None, important=w['important'] if w else None,
            equipment=w['equipment'] if w else None,
            patrol=dict(type=w['patrol']['type'], points=[p['entity_guid'] for p in w['patrol']['points']])
                if w and w['patrol'] else None,
            home=row['home'], bed=row['bed'])
    reserved = sorted((r['soul'], r['post']) for r in result['static_allocation'] if not r['in_scope'] and r['post'])
    lines = ['"""Generated by garrison_census.py; do not edit by hand. Rerun the census to change it.', '',
             "KCD1 garrison guards the guard stage imports, each with the post KCD1's allocator",
             'gives it on the frozen day (see garrison_census). Posts held by people other routes import:']
    lines += [f'  {s} -> {p}' for s, p in reserved]
    lines += ['"""', '', 'GUARDS = {']
    for name in sorted(guards):
        lines.append(f'    {name!r}: {guards[name]!r},')
    lines.append('}')
    return '\n'.join(lines) + '\n'


def main(argv=None):
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('--source', type=Path, required=True)
    p.add_argument('--town', action='append', required=True)
    p.add_argument('--out', type=Path, required=True, help='full JSON report: garrisons, guards, allocation')
    p.add_argument('--module', type=Path, help='also write the generated selection (tools/garrison_selection.py)')
    p.add_argument('--fresh', action='store_true', help='discard cached stages')
    args = p.parse_args(argv)
    cache = args.out.with_suffix('.progress'); cache.mkdir(parents=True, exist_ok=True)
    if args.fresh:
        for f in cache.iterdir(): f.unlink()
    complete = cache/'complete.json'
    if complete.exists():
        template_id = json.loads(complete.read_text())['template_id']
        print('[load] all source stages cached; simulating only (use --fresh to re-extract)', flush=True)
    else:
        template_id = stage_source(args, cache)
        complete.write_text(json.dumps(dict(template_id=template_id)))
    garrisons = json.loads((cache/'garrisons.json').read_text(encoding='utf-8'))
    guards = [json.loads(l) for l in (cache/'guards.jsonl').read_text(encoding='utf-8').splitlines()]
    beds = json.loads((cache/'beds.json').read_text(encoding='utf-8'))
    bed_choice = choose_beds(guards, beds)
    totals = Counter()
    empty = [g for g in garrisons if not g['workplaces'] and not any(r['garrison'] == g['name'] for r in guards)]
    garrisons = [g for g in garrisons if g not in empty]
    for g in garrisons:
        for w in g['workplaces']:
            if w['kind'] == 'patrolWalls':
                seen = set()
                for e in w['patrol']['edges']:
                    seen.add(e['src'])
                    if e['dst'] in seen: w['patrol']['type'] = 'loop_or_branching'
        mine = [r for r in guards if r['garrison'] == g['name']]
        for r in mine:
            bad = [w for w in r['resolved_work'] if w['tree'] != ':'.join(TREE) or w['area'] != g['name']]
            if bad or not r['resolved_work']: raise ValueError('guard work does not resolve to its garrison: ' + r['soul_name'])
            work = intervals(r['daycycle'], 'work')
            r['work_intervals'] = [dict(start=minutes(a), end=minutes(b), start_minute=a, end_minute=b) for a, b, _ in work]
            r['shift'] = 'night' if any(b > 1440 for a, b, _ in work) else 'day'
            r['in_scope'] = in_scope(r)
            options = beds.get(r['soul_name'])
            if isinstance(options, list):   # every home bed, and the three nearest public fallbacks
                options = [c for c in options if c['kind'] != 'public_fallback'] + [c for c in options if c['kind'] == 'public_fallback'][:3]
            r['bed_candidates'] = options
            r['bed'] = bed_choice.get(r['soul_name'])
        g['guards'] = sorted(mine, key=lambda r: r['soul_name'])
        g['allocation'] = {'authored': simulate(g, mine, bed_choice)}
        for state, rule in QUEST_STATES.items():
            if rule['garrison'] == g['name']:
                g['allocation'][state] = dict(simulate(g, mine, bed_choice, rule['enable']), evidence=rule['evidence'])
        g['default_state'] = next((s for s in g['allocation'] if s != 'authored'), 'authored')
        alloc = g['allocation'][g['default_state']]
        for r in g['guards']:
            a = alloc['per_guard'][r['soul_name']]
            r['static'] = dict(state=g['default_state'], post=a['primary_post'], segments=a['segments'],
                               bed=r['bed']['name'] if r['bed'] else None)
        kinds = Counter(w['kind'] for w in g['workplaces'])
        g['summary'] = dict(workplaces=len(g['workplaces']), posts=kinds.get('guardPlace', 0),
            patrols=kinds.get('patrolWalls', 0) + kinds.get('patrolStreets', 0), patrol_walls=kinds.get('patrolWalls', 0),
            patrol_streets=kinds.get('patrolStreets', 0), important=sum(w['important'] for w in g['workplaces']),
            disabled=sum(w['disabled'] for w in g['workplaces']), guards=len(mine),
            guards_in_scope=sum(r['in_scope'] for r in mine), day=sum(r['shift'] == 'day' for r in mine),
            night=sum(r['shift'] == 'night' for r in mine),
            beds=len({r['bed']['source_id'] for r in mine if r['bed']}), guards_with_bed=sum(bool(r['bed']) for r in mine),
            guards_with_post=sum(bool(alloc['per_guard'][r['soul_name']]['primary_post']) for r in mine),
            in_scope_with_post=sum(bool(alloc['per_guard'][r['soul_name']]['primary_post']) for r in mine if r['in_scope']),
            never_manned=[n for n, v in alloc['per_post'].items() if v['enabled'] and not v['manned_minutes']],
            converged=all(a['converged'] for a in g['allocation'].values()),
            method={s: a['method'] for s, a in g['allocation'].items()},
            tie_break={s: a['tie_break'] for s, a in g['allocation'].items()},
            period_days={s: a['period_days'] for s, a in g['allocation'].items()})
        for k in ('workplaces', 'posts', 'patrols', 'guards', 'guards_in_scope', 'beds', 'guards_with_bed',
                  'guards_with_post', 'in_scope_with_post'):
            totals[k] += g['summary'][k]
        print(f"[4] {g['name']}: {g['summary']}", flush=True)
    kind_of = {w['name']: w['kind'] for g in garrisons for w in g['workplaces']}
    table = [dict(soul=r['soul_name'], soul_id=r['soul_id'], in_scope=r['in_scope'], garrison=g['name'], state=g['default_state'],
                  method=g['allocation'][g['default_state']]['method'], faction=r['faction']['name'], faction_id=r['faction']['id'],
                  shift=r['shift'], work=[[w['start'], w['end']] for w in r['work_intervals']], post=r['static']['post'],
                  post_kind=kind_of.get(r['static']['post']), role='posted' if r['static']['post'] else 'reserve',
                  segments=[[m['start'], m['end'], m['post'] or 'idle'] for m in r['static']['segments']],
                  home=r['home']['name'] if r['home'] else None, bed=r['static']['bed'])
             for g in garrisons for r in g['guards']]
    result = dict(schema=1, generator='garrison_census.py', town=args.town,
        source=dict(level='Data/Levels/rataje/level.pak', members=['objects_mission0.xml', 'layers/*.xml', 'whdata_0', 'whdata_1'],
                    tables=['rpg/soul', 'ai/sa_smart_area', 'ai/sa_smart_area2sa_behaviour_tag', 'ai/sa_behaviour_tag'],
                    behavior='Scripts.pak Libs/AI/final/sa_garrison.xml', smart_area_template=dict(name=GARRISON_TEMPLATE, id=template_id)),
        assumptions=ASSUMPTIONS, quest_states=QUEST_STATES, totals=dict(totals, garrisons=len(garrisons)),
        empty_areas=[dict(name=g['name'], pos=g['pos'], entity_id=g['entity_id']) for g in empty],
        static_allocation=table, garrisons=garrisons)
    args.out.write_text(json.dumps(result, indent=1), encoding='utf-8')
    if args.module is not None:
        args.module.write_text(selection_module(result), encoding='utf-8')
    print(f'[done] {args.out} totals={dict(totals)} garrisons={len(garrisons)}', flush=True)


if __name__ == '__main__':
    main()
