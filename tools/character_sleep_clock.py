"""Source sleep clocks and deterministic, job-based missing-daycycle completion."""
import hashlib
import math
from statistics import mean, pstdev

from character_schedule import day_intervals

VERSION = 1
GUARDS = {'guard', 'guardLeader', 'watchman', 'soldier', 'security', 'catchpole'}


def source_entries(row):
    entries = []
    for i in range(9):
        activity, clock = row.get(f'activity_{i}'), row.get(f'time_{i}')
        if not activity and not clock:
            continue
        try:
            hour, minute = map(int, clock.split(':'))
            if not activity or not 0 <= hour < 24 or not 0 <= minute < 60:
                return []
        except (AttributeError, ValueError):
            return []
        entries.append(dict(activity=activity, start_minute=hour*60+minute))
    if len({e['start_minute'] for e in entries}) != len(entries):
        return []
    return entries


def episodes(entries):
    ordered = sorted(entries, key=lambda e: e['start_minute'])
    result = []
    for i, entry in enumerate(ordered):
        if entry['activity'].casefold() != 'sleep':
            continue
        end = ordered[(i+1) % len(ordered)]['start_minute']
        duration = (end-entry['start_minute']) % 1440
        if duration:
            result.append((entry['start_minute'], duration))
    return result


def statistics(rows, brain_ids):
    """Exclude animals, malformed clocks and outlier/non-night-rest schedules."""
    groups = {}
    for row in rows:
        if row.get('brain_id') not in brain_ids:
            continue
        for start, duration in episodes(source_entries(row)):
            if 240 <= duration <= 720:
                groups.setdefault(row['social_class_id'], []).append((start, duration))
    return groups


def summarize(samples):
    # Circular averaging keeps 23:50 and 00:10 near midnight, not midday.
    x = mean(math.cos(s*math.tau/1440) for s, _ in samples)
    y = mean(math.sin(s*math.tau/1440) for s, _ in samples)
    center = math.atan2(y, x)*1440/math.tau % 1440
    offsets = [(s-center+720) % 1440-720 for s, _ in samples]
    return dict(start_minute=round(center) % 1440,
                duration_minutes=round(mean(d for _, d in samples)),
                variation_minutes=min(45, max(10, round(pstdev(offsets)))), samples=len(samples))


def plan_clocks(people, groups):
    """Only fill missing all-day work routines. Existing multi-activity clocks win.

    Guards in one authored workplace alternate observed daytime/nighttime rest
    cohorts. This is a generated daily rota, not a claim of source quest parity.
    """
    result = {}; guard_groups = {}
    for name, person in people.items():
        ai = person['ai']; entries = ai['schedule']
        authored = [e for e in day_intervals(entries) if e['activity'].casefold() == 'sleep']
        if authored:
            result[name] = dict(mode='source', intervals=[(e['start_minute'], e['end_minute']) for e in authored])
            continue
        if len(entries) != 1 or entries[0]['activity'].casefold() != 'work':
            continue
        social = ai['source_social_class']
        if social['social_class_name'] in GUARDS:
            destinations = sorted(l['target']['EntityGuid'] for l in ai['links']
                                  if l['label'].lower().startswith('work'))
            # Neighbouring unassigned guards still share a deterministic rota.
            pos = tuple(float(v) for v in person['actor'].get('Pos').split(','))
            key = tuple(destinations) or (int(pos[0]//500), int(pos[1]//500))
            guard_groups.setdefault(key, []).append(name)
        result[name] = dict(mode='generated_job_average')
    guard_cohorts = {}
    for names in guard_groups.values():
        for i, name in enumerate(sorted(names, key=lambda n: people[n]['soul']['soul_id'])):
            guard_cohorts[name] = i % 2
    common = [s for values in groups.values() for s in values if s[0] >= 1080 or s[0] < 240]
    guard_samples = [s for name in guard_cohorts for s in groups.get(people[name]['soul']['social_class_id'], [])]
    for name, clock in list(result.items()):
        if clock['mode'] == 'source':
            continue
        person = people[name]; samples = groups.get(person['soul']['social_class_id'], [])
        if name in guard_cohorts:
            daytime = guard_cohorts[name] == 1
            samples = [s for s in (samples or guard_samples) if (360 <= s[0] < 1080) == daytime]
            if not samples:
                samples = [s for s in guard_samples if (360 <= s[0] < 1080) == daytime]
            clock['shift'] = 'night_duty' if daytime else 'day_duty'
        else:
            samples = [s for s in samples if s[0] >= 1080 or s[0] < 240]
        if not samples:
            if name in guard_cohorts:
                del result[name]  # Never silently collapse both guard shifts.
                continue
            samples = common
            clock['average_fallback'] = 'human_night_sleep'
        if not samples:
            del result[name]
            continue
        stats = summarize(samples)
        seed = int.from_bytes(hashlib.sha256(('sleep/'+person['soul']['soul_id']).encode()).digest()[:8], 'little')
        variation = stats['variation_minutes']; offset = seed % (variation*2+1)-variation
        start = (stats['start_minute']+offset) % 1440
        end = (start+stats['duration_minutes']) % 1440
        intervals = [(start, end)] if end > start else [(0, end), (start, 1440)]
        clock.update(average=stats, offset_minutes=offset,
                     intervals=[(a, b) for a, b in intervals if a < b])
    return result
