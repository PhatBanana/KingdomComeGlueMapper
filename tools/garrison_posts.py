"""Give each selected KCD1 garrison guard the post KCD1's allocator gives it.

KCD1 picks a guard's post at runtime (sa_garrison.xml: first free workplace in
list order, important first, to the nearest available guard). garrison_census
replays that rule and freezes one day per guard (tools/garrison_selection.py).
Here, after the person is captured from the source world, the guard is checked
against the census (soul, faction, garrison Work link, work clock, post TagPoint
GUID, name and world position) and the post is added as a garrison_forcedWorkplace
link: the same override KCD1's own authored guards carry, so the existing
forced-workplace path (character_schedule_world, character_schedule_jobs) converts it.
Any mismatch refuses the guard; nothing is guessed.
"""
import copy
import math
import xml.etree.ElementTree as ET
import zipfile

from upgrade_map import read

FORCED = 'garrison_forcedWorkplace'
PATROLS = ('patrolWalls', 'patrolStreets')
POSITION_TOLERANCE = 0.01


def clock(minute):
    minute %= 1440
    return f'{minute // 60:02d}:{minute % 60:02d}'


def _minute(text):
    h, m = map(int, text.split(':'))
    return h * 60 + m


def _spans(start, end):
    """[start, end) minutes as pieces within one day: 20:28-08:58 is (1228, 1440) and (0, 538)."""
    return [(start, end)] if end > start else [(start, 1440), (0, end)] if end else [(start, 1440)]


def post_windows(segments):
    """Minute windows of one day in which the guard stands at its post.

    KCD1's garrison gives a post one worker: a guard arriving before the post
    is free waits (guardIdle) until the holder leaves. The census writes that
    as an 'idle' segment; only the post segments are post time.
    """
    pieces = sorted(p for a, b, post in segments if post != 'idle' for p in _spans(_minute(a), _minute(b)))
    merged = []
    for a, b in pieces:
        if merged and a <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], b))
        else:
            merged.append((a, b))
    return merged


def trim_links(scheduler, target_guid, windows):
    """Cut every scheduler activity link to target_guid down to the given windows (split or drop as needed)."""
    parents = {child: parent for parent in scheduler.iter() for child in parent}
    for link in [l for l in scheduler.iter('S_ActivityLink') if l.get('TargetGuid') == target_guid]:
        params = link.find('Parameters')
        a, b = int(params.get('TimeOfDayStart')), int(params.get('TimeOfDayEnd'))
        pieces = [(max(s, x), min(e, y)) for s, e in _spans(a, b) for x, y in windows if min(e, y) > max(s, x)]
        parent = parents[link]
        at = list(parent).index(link)
        parent.remove(link)
        for offset, (s, e) in enumerate(pieces):
            piece = copy.deepcopy(link)
            piece.find('Parameters').set('TimeOfDayStart', str(s))
            piece.find('Parameters').set('TimeOfDayEnd', str(e))
            parent.insert(at + offset, piece)


def work_intervals(schedule):
    """[start, end] clock pairs of the soul's 'work' daycycle rows (the census's intervals())."""
    rows = sorted(schedule, key=lambda r: r['start_minute'])
    result = []
    for index, row in enumerate(rows):
        if row['activity'] == 'work':
            result.append([clock(row['start_minute']), clock(rows[(index + 1) % len(rows)]['start_minute'])])
    return result


def source_mission(source, source_level='rataje'):
    """objects_mission0 entities by EntityId and by EntityGuid (upper case)."""
    with zipfile.ZipFile(source/'Data/Levels'/source_level/'level.pak') as archive:
        mission = ET.fromstring(read(archive, 'objects_mission0.xml'))
    by_id, by_guid = {}, {}
    for entity in mission.iter('Entity'):
        if entity.get('EntityId'):
            by_id[entity.get('EntityId')] = entity
        if entity.get('EntityGuid'):
            by_guid.setdefault(entity.get('EntityGuid').upper(), []).append(entity)
    return by_id, by_guid


def work_links(links):
    return [l for l in links if (l['label'] or '').split('[')[0].split(',')[0].strip() in ('Work', 'futureWork')]


def check(person, record, by_id, by_guid):
    """(problems, post TagPoint) for a captured guard against its census record."""
    from entity_visuals import world_transform
    problems = []
    ai = person['ai']
    if person['soul'].get('soul_id') != record['soul_id']:
        problems.append(f"soul id {person['soul'].get('soul_id')} != census {record['soul_id']}")
    faction = str(ai['faction_graph']['faction'].get('faction_id'))
    if faction != str(record['faction_id']):
        problems.append(f'faction {faction} != census {record["faction_id"]}')
    work = work_links(ai['links'])
    if [l['target'].get('Name') for l in work] != [record['garrison']] or \
            (work[0]['target'].get('EntityGuid') or '').upper() != record['garrison_guid'].upper():
        problems.append('Work link does not target garrison ' + record['garrison'])
    if work_intervals(ai['schedule']) != record['work']:
        problems.append(f"work clock {work_intervals(ai['schedule'])} != census {record['work']}")
    if any(l['label'] == FORCED for l in ai['links']):
        problems.append('already has an authored ' + FORCED)
    if record['role'] != 'posted':
        return problems, None
    matches = by_guid.get((record['post_guid'] or '').upper(), [])
    if len(matches) != 1:
        problems.append(f"post {record['post']} GUID {record['post_guid']} matches {len(matches)} source entities")
        return problems, None
    point = matches[0]
    if point.get('Name') != record['post'] or point.get('EntityClass') != 'TagPoint':
        problems.append(f"post GUID names {point.get('EntityClass')} {point.get('Name')}, census {record['post']}")
    position, _, _ = world_transform(point, by_id)
    if math.dist(position, record['post_pos']) > POSITION_TOLERANCE:
        problems.append(f"post {record['post']} at {position}, census {record['post_pos']}")
    return problems, point


def apply(people, source, guards, source_level='rataje', mission=None):
    """Add each posted guard's census post as its forced workplace. Returns one report row per guard.

    Raises ValueError when any selected guard disagrees with the census: the
    allocation is a whole-garrison result, so one changed guard invalidates it.
    """
    by_id, by_guid = mission if mission is not None else source_mission(source, source_level)
    report, refused = [], []
    for name in sorted(set(people) & set(guards)):
        person, record = people[name], guards[name]
        problems, point = check(person, record, by_id, by_guid)
        if problems:
            refused.append(f'{name}: ' + '; '.join(problems))
            continue
        row = dict(person=name, soul_id=record['soul_id'], faction_id=record['faction_id'],
                   garrison=record['garrison'], state=record['state'], method=record['method'],
                   shift=record['shift'], work=record['work'], segments=record['segments'], role=record['role'],
                   post=record['post'], post_kind=record['post_kind'], kcd1_order=record['kcd1_order'],
                   important=record['important'], equipment=record['equipment'],
                   patrol_points=len(record['patrol']['points']) if record['patrol'] else 0,
                   home=record['home'], bed=record['bed'], pending=[])
        if point is not None:
            person['ai']['links'].append(dict(label=FORCED, target=dict(point.attrib),
                source_xml=ET.tostring(point, encoding='unicode'), status='pending',
                origin='garrison_census', garrison=dict(post=record['post'], post_kind=record['post_kind'],
                    garrison=record['garrison'], segments=record['segments'], patrol=record['patrol'])))
            if record['post_kind'] in PATROLS:
                row['pending'].append('patrol route: holds the patrol start point')
        else:
            row['pending'].append('reserve: KCD1 keeps this guard idle at the garrison benches')
        report.append(row)
    if refused:
        raise ValueError('Garrison guards disagree with the garrison census (rerun garrison_census): '
                         + ' | '.join(refused))
    return report
