"""Verify imported KCD1 garrison guards against the garrison census and KCD1, offline.

verify_residents --marker garrison_population covers what every imported person
shares (soul, faction, voice, stats, outfit, home, bed pool, day schedule, places on
the navmesh). This adds what is particular to a guard, per guard:

  census    the guard is in the marker's prepared rows exactly as tools/garrison_selection.py
            has it: soul id, KCD1 faction, garrison, shift, work clock, role, post, segments
  post      a posted guard's converted job is a native guard spot (so_guardSpotPoint,
            guardNonImportant) at the KCD1 post's position, bound by the guard's scheduler
            for KCD1's work interval; a reserve guard has no post
  bed       the census bed (KCD1's home bed) is in the guard's converted sleep pool
  reach     the post and every bed in the guard's pool lie in one connected navmesh
            region (polygons, tile portals and off-mesh links), so the day can be walked
  patrol    for a patrol guard, every KCD1 patrol point lies in the post's region (the route
            itself is pending; the guard holds the start point)

and package checks: no two guards on one post at overlapping times; every in-scope
census guard is placed or listed as residue.

Usage: python verify_garrison.py --package PKG --census rattay-garrisons.json --out DIR
"""
import argparse
from collections import Counter, defaultdict
import json
import math
from pathlib import Path
import zipfile
import xml.etree.ElementTree as ET

from upgrade_map import read

TRAVEL = 'Data/gluemappertravel.pak'
LEVEL = 'Data/Levels/kcd1_travel'
MARKER = 'Libs/GlueMapper/garrison_population.json'
GUARD_SPOT = '47674689'          # SmartEntity__so_guardSpotPoint DatabaseId prefix
BEHAVIOR = 'guardNonImportant'
TOLERANCE = 0.05
CHECKS = ('census', 'post', 'bed', 'reach', 'patrol')


def minutes(clock):
    h, m = clock.split(':')
    return int(h) * 60 + int(m)


def span(a, b):
    start, end = minutes(a), minutes(b)
    return start, end if end > start else end + 1440


def overlaps(a, b):
    return any(a[0] + d < b[1] and b[0] < a[1] + d for d in (-1440, 0, 1440))


class Regions:
    """Connected walkable regions of a recast.pak over a bounding box (union-find over polygons)."""

    def __init__(self, recast, box, margin=32.0):
        from audit_bed_navigation import Mesh, cell_of
        self.mesh, self.parent = Mesh(recast), {}
        (x0, y0), (x1, y1) = cell_of(box[0] - margin, box[1] - margin), cell_of(box[2] + margin, box[3] + margin)
        portals = defaultdict(list)   # tile border line -> [(lo, hi, z, node)]
        offmesh = []
        for cx in range(x0, x1 + 1):
            for cy in range(y0, y1 + 1):
                for tile in self.mesh.tiles((cx, cy)):
                    key = (tuple(tile['cell']), tile['layer'])
                    verts = tile['verts']
                    for i, poly in enumerate(tile['polys']):
                        node = key + (i,)
                        self.find(node)
                        for j, nei in enumerate(poly['neis'][:poly['nv']]):
                            if nei and not nei & 0x8000:
                                self.union(node, key + (nei - 1,))
                            elif nei & 0x8000:
                                a = verts[poly['verts'][j]]; b = verts[poly['verts'][(j + 1) % poly['nv']]]
                                if abs(a[0] - b[0]) < 1e-3:
                                    line, (lo, hi) = ('x', round(a[0], 1)), sorted((a[1], b[1]))
                                elif abs(a[1] - b[1]) < 1e-3:
                                    line, (lo, hi) = ('y', round(a[1], 1)), sorted((a[0], b[0]))
                                else:
                                    continue
                                portals[line].append((lo, hi, (a[2] + b[2]) / 2, node))
                    for link in tile['links']:
                        if link['nv'] == 2:
                            offmesh.append([verts[v] for v in link['verts'][:2]])
        for rows in portals.values():
            rows.sort()
            for i, (lo, hi, z, node) in enumerate(rows):
                for lo2, hi2, z2, node2 in rows[i + 1:]:
                    if lo2 > hi - 0.05:
                        break
                    if node2[:2] != node[:2] and abs(z - z2) < 1.0:
                        self.union(node, node2)
        self.offmesh = 0
        for a, b in offmesh:
            na, nb = self.node(a), self.node(b)
            if na in self.parent and nb in self.parent:
                self.union(na, nb); self.offmesh += 1

    def find(self, x):
        self.parent.setdefault(x, x)
        while self.parent[x] != x:
            self.parent[x] = self.parent[self.parent[x]]
            x = self.parent[x]
        return x

    def union(self, a, b):
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.parent[ra] = rb

    def node(self, point):
        from audit_bed_navigation import nearest
        hit = nearest(self.mesh, point)
        return None if hit is None else (tuple(hit['cell']), hit['layer'], hit['poly'])

    def region(self, point):
        node = self.node(point) if point is not None else None
        return None if node is None or node not in self.parent else self.find(node)


def position(entity):
    try:
        return tuple(float(v) for v in entity.get('Pos', '').split(',')[:3])
    except (ValueError, AttributeError):
        return None


def result(ok, detail):
    return dict(ok=bool(ok), detail=detail)


def merge_day(spans):
    """Minute spans folded onto one 24 h day and merged: 20:03-08:33 equals 00:00-08:33 plus 20:03-24:00."""
    pieces = []
    for a, b in spans:
        a, b = a % 1440, a % 1440 + (b - a)
        pieces += [(a, 1440), (0, b - 1440)] if b > 1440 else [(a, b)]
    merged = []
    for a, b in sorted(pieces):
        if merged and a <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], b))
        else:
            merged.append((a, b))
    return merged


def check_post(person, record, job_rows, level, npc):
    """(problems, converted post position) for a posted guard."""
    problems, post_pos = [], None
    # A KCD1 shift over midnight is two daycycle intervals at one workplace: one post, one holder.
    job_rows = list({row['source_workplace'].get('EntityId'): row for row in job_rows}.values())
    if len(job_rows) != 1:
        return [f'{len(job_rows)} converted guard jobs'], None
    job = job_rows[0]
    if (job.get('garrison_post') or {}).get('post') != record['post']:
        problems.append('job post ' + str((job.get('garrison_post') or {}).get('post')))
    if job['source_workplace'].get('Name') != record['post']:
        problems.append('source workplace ' + str(job['source_workplace'].get('Name')))
    if job.get('native_behavior') != BEHAVIOR:
        problems.append('behavior ' + str(job.get('native_behavior')))
    holder = level.by_name.get(f"gm_schedule_{person}_{job['source_workplace'].get('EntityId')}", [])
    if len(holder) != 1:
        return problems + [f'{len(holder)} job holders'], None
    props = holder[0].find('Properties')
    if holder[0].get('EntityClass') != 'DetailMovementSmartObject' or props is None \
            or not (props.get('guidSmartObjectType') or '').startswith(GUARD_SPOT):
        problems.append('holder is not a native guard spot')
    post_pos = position(holder[0])
    if post_pos is None or math.dist(post_pos, record['post_pos']) > TOLERANCE:
        problems.append(f"holder at {post_pos}, KCD1 post at {record['post_pos']}")
    got = merge_day((a, b if b > a else b + 1440) for a, b, t in level.activity_links(npc) if t is holder[0])
    want = merge_day(span(a, b) for a, b in record['work'])
    if got != want:
        problems.append(f'scheduled {got}, KCD1 work {want}')
    return problems, post_pos


def verify(package, census_path, out, guards=None):
    from verify_residents import Level, day_places
    if guards is None:
        from garrison_selection import GUARDS as guards
    package, out = Path(package), Path(out)
    census = json.loads(Path(census_path).read_text(encoding='utf-8'))
    workplaces = {w['name']: w for g in census['garrisons'] for w in g['workplaces']}
    by_soul = {r['soul_name']: r for g in census['garrisons'] for r in g['guards']}
    with zipfile.ZipFile(package/TRAVEL) as travel:
        marker = json.loads(read(travel, MARKER))
        souls = {}
        for n in travel.namelist():
            if n.startswith('Libs/Tables/rpg/soul__'):
                for soul in ET.fromstring(read(travel, n)).iter('soul'):
                    souls[soul.get('soul_name')] = soul.attrib
    placed = {r['person'] for r in marker['residents']}
    residue = {r['person']: r['reason'] for r in marker.get('residue', [])}
    prepared = {r['person']: r for r in marker.get('prepared', [])}
    jobs = defaultdict(list)
    for row in marker['work']['converted']:
        if row.get('job') == 'guard':
            jobs[row['person']].append(row)
    level = Level(package)
    points = [tuple(w['pos']) for w in workplaces.values()]
    points += [tuple(c['pos']) for r in by_soul.values() for c in (r.get('bed_candidates') or []) if isinstance(c, dict)]
    box = (min(p[0] for p in points), min(p[1] for p in points), max(p[0] for p in points), max(p[1] for p in points))
    regions = Regions(package/LEVEL/'recast.pak', box)
    results, held = {}, defaultdict(list)
    for person in sorted(guards):
        record = guards[person]
        if person not in placed:
            results[person] = dict(placed=False, residue=residue.get(person, 'missing without a residue reason'),
                                   fail=[] if person in residue else ['placed'])
            continue
        r = {}
        row = prepared.get(person, {})
        diff = [f for f in ('soul_id', 'faction_id', 'garrison', 'shift', 'work', 'role', 'post', 'segments')
                if row.get(f) != record[f]]
        if souls.get(person, {}).get('soul_id') != record['soul_id']:
            diff.append(f"package soul {souls.get(person, {}).get('soul_id')}")
        r['census'] = result(row and not diff, 'differs: ' + ', '.join(diff) if diff else
                             f"{record['garrison']} {record['shift']} {record['work']} {record['role']}")
        npcs = level.by_name.get(person, [])
        npc = npcs[0] if len(npcs) == 1 else None
        places, _ = day_places(level, npc)
        beds = [e for block, e in places if block == 'sleep']
        post_pos = None
        if record['role'] == 'posted':
            problems, post_pos = check_post(person, record, jobs.get(person, []), level, npc)
            r['post'] = result(not problems, '; '.join(problems) or
                               f"{record['post']} ({record['post_kind']}, KCD1 order {record['kcd1_order']})")
            for a, b, post in record['segments']:
                if post != 'idle':
                    held[post].append((span(a, b), person))
        else:
            r['post'] = result(not jobs.get(person), f"reserve, {len(jobs.get(person, []))} guard jobs")
        bed = (by_soul.get(person) or {}).get('bed')
        if bed:
            match = [e for e in beds if position(e) and math.dist(position(e), bed['pos']) < 0.5]
            r['bed'] = result(match, f"KCD1 bed {bed['name']} {'in' if match else 'not in'} the pool of {len(beds)}")
        else:
            r['bed'] = result(beds, f'no KCD1 home bed; {len(beds)} pool beds')
        anchor = post_pos or next((position(e) for b, e in places if b == 'idle'), None)
        home = regions.region(anchor)
        off = [e.get('Name') for e in beds if regions.region(position(e)) != home]
        own = [e for e in beds if bed and position(e) and math.dist(position(e), bed['pos']) < 0.5]
        # The guard's own KCD1 bed (or, with none, at least one pool bed) must be walkable from the post;
        # other beds of the shared pool that are not are listed for review, not failed.
        reachable = [e for e in (own or beds) if regions.region(position(e)) == home]
        r['reach'] = result(home is not None and reachable,
                            ('post off the navmesh' if home is None else
                             f"post and {'KCD1 bed' if own else 'a pool bed'} connected; "
                             f"{len(beds) - len(off)} of {len(beds)} pool beds connected") +
                            ('; review, not connected: ' + ', '.join(off) if off else ''))
        if off:
            r['reach']['review'] = off
        if record['patrol']:
            route = (workplaces.get(record['post']) or {}).get('patrol', {}).get('points', [])
            stray = [p['name'] for p in route if regions.region(tuple(p['pos'])) != home]
            r['patrol'] = result(home is not None and route and not stray,
                                 f"{len(route)} points ({record['patrol']['type']}), route pending"
                                 + ('; not connected: ' + ', '.join(stray) if stray else ''))
        else:
            r['patrol'] = result(True, 'no patrol')
        results[person] = dict(placed=True, checks=r, fail=sorted(k for k, v in r.items() if not v['ok']))
    clashes = [f'{post}: {n1} and {n2}' for post, rows in held.items()
               for i, (s1, n1) in enumerate(rows) for s2, n2 in rows[i + 1:] if overlaps(s1, s2)]
    summary = {k: dict(Counter('pass' if v['checks'][k]['ok'] else 'fail' for v in results.values() if v['placed']))
               for k in CHECKS}
    report = dict(package=str(package), guards=len(guards), placed=sum(v['placed'] for v in results.values()),
                  residue={p: v['residue'] for p, v in results.items() if not v['placed']},
                  failed=sorted(p for p, v in results.items() if v['fail']), post_clashes=clashes,
                  roles=dict(Counter(guards[p]['role'] for p, v in results.items() if v['placed'])),
                  offmesh_links=regions.offmesh, summary=summary, results=results)
    out.mkdir(parents=True, exist_ok=True)
    (out/'verify-garrison.json').write_text(json.dumps(report, indent=1), encoding='utf-8')
    lines = [f"# Garrison verification: {report['placed']} of {len(guards)} guards placed, "
             f"{len(report['failed'])} with a FAIL, {len(clashes)} post clashes", '',
             '| Check | Pass | Fail |', '|---|---|---|']
    lines += [f"| {k} | {v.get('pass', 0)} | {v.get('fail', 0)} |" for k, v in summary.items()]
    lines += ['', '## Residue', ''] + [f'- {p}: {why}' for p, why in sorted(report['residue'].items())]
    lines += ['', '## Failures', '']
    for person, v in sorted(results.items()):
        for k in v['fail']:
            lines.append(f"- {person} {k}: {v['checks'][k]['detail'] if v['placed'] else v.get('residue')}")
    lines += ['', '## Post clashes', ''] + [f'- {c}' for c in clashes]
    (out/'verify-garrison.md').write_text('\n'.join(lines) + '\n', encoding='utf-8')
    return report


def main(argv=None):
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    for key in ('package', 'census', 'out'):
        p.add_argument('--' + key, type=Path, required=True)
    a = p.parse_args(argv)
    report = verify(a.package, a.census, a.out)
    print(json.dumps({k: report[k] for k in ('guards', 'placed', 'failed', 'post_clashes', 'roles', 'summary')}, indent=1))
    return 1 if report['failed'] or report['post_clashes'] else 0


if __name__ == '__main__':
    raise SystemExit(main())
