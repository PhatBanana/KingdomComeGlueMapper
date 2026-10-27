"""Clearance, duplicate, boundary-closure and road-crossing checks.

Every number below is an assumption, not a native value; all are recorded in
the report. Findings are ``inspect`` unless the overlap is deep (see DEEP) or
the volume origin coincides with the interaction origin.
"""
from collections import Counter, defaultdict
import math

from . import geometry as g
from .source import blocks

ASSUMPTIONS = dict(
    player_radius=0.4,          # m; generic humanoid capsule radius (not read from KCD2)
    body_z=(-0.3, 1.8),         # m relative to interaction Pos; body/capsule height band
    door_box=((-1.25, -1.0, 0.0), (1.25, 1.0, 2.2)),  # m, door-local; covers left/right hinge + swing
    ladder_default_height=3.0,  # m when Properties/height is absent
    ladder_step=0.25,           # m sampling along the ladder axis
    deep=0.5,                   # m penetration that is called a defect
    coincident=0.002,           # m; origin match used by designer_collision_repair
    duplicate_tolerance=0.002,  # m on origin and full world bounds
    contact=0.05,               # m; barrier ends closer than this are closed
    gap_defect=2.0,             # m; wider ring gaps are defects, narrower ones inspect
    player_gap=0.8,             # m; capsule diameter (passable by the player)
    horse_gap=1.2,              # m; assumed horse body width (passable by a horse)
    road_edge_margin=15.0,      # m from the terrain edge counts as "reaches map edge"
)
MAP_EXIT_MONOLOG = 'HRAC_NEMUZE_Z_MAPY'  # native metarole on the outer level barrier surfaces

NOT_MODELLED = [
    'Physics traversal: capsule sweep, steps, slopes and terrain height are not simulated.',
    'Barrier top versus terrain height is not checked (panels are treated as infinitely tall in plan).',
    'Barrier slowdown, warning distance and monologue are native behaviour; only reported.',
    'Native door, smart-object and ladder helper geometry is not read; clearance shapes are fixed boxes/discs (see assumptions).',
    'Only designer collision volumes (proxy materials) are obstacles; buildings, props, entities, vegetation and navmesh are not.',
    'player_only/horse_only filtering semantics come from SurfaceTypes.xml flags and are not runtime-verified (in game, horse-only door blockers were reported blocking Henry, ef8f35a).',
    'Terrain extent edge is treated as closed; walking past the heightmap edge is not modelled.',
    'Road corridors use the paired edge points of KCD2 road records; road surface triangles are not used.',
]


def volume_shape(v):
    poly, zr = g.footprint(v['matrix'], v['local_min'], v['local_max'])
    return poly, zr


def prepare(world):
    surfaces = world['surfaces']
    vols = []
    for v in world['volumes'] + world.get('source_volumes', []):
        s = surfaces.get(v['surface'])
        agents = blocks(s)
        poly, zr = volume_shape(v)
        vols.append(dict(v, poly=poly, z=zr, blocks=agents, barrier=(s or {}).get('barrier'),
                         origin_xyz=(v['matrix'][3], v['matrix'][7], v['matrix'][11])))
    return vols


def finding(category, severity, xyz, **kw):
    return dict(category=category, severity=severity, x=round(xyz[0], 2), y=round(xyz[1], 2),
                z=round(xyz[2], 2) if len(xyz) > 2 and xyz[2] is not None else None, **kw)


def interaction_shapes(it, a):
    """Return list of (kind, shape, zrange) for one interaction."""
    p = it['pos']; z = (p[2] + a['body_z'][0], p[2] + a['body_z'][1])
    if it['kind'] == 'door':
        lo, hi = a['door_box']
        poly, zr = g.footprint(it['matrix'], lo, hi)
        return [('box', poly, zr)]
    if it['kind'] == 'ladder':
        m = it['matrix']; h = it.get('height') or a['ladder_default_height']
        axis = (m[2], m[6], m[10]); n = max(1, int(h / a['ladder_step']))
        pts = [(p[0]+axis[0]*h*k/n, p[1]+axis[1]*h*k/n, p[2]+axis[2]*h*k/n) for k in range(n+1)]
        return [('disc', q, (q[2]+a['body_z'][0], q[2]+a['body_z'][1])) for q in pts]
    return [('disc', p, z)]


def check_interactions(world, vols, a):
    grid = g.Grid(32.0)
    for v in vols:
        if v['blocks']: grid.add(g.bbox2(v['poly']), v)
    findings = []; r = a['player_radius']; modelled = Counter()
    for it in world['interactions']:
        modelled[it['cls']] += 1
        shapes = interaction_shapes(it, a)
        box = None
        for kind, shape, _ in shapes:
            b = g.bbox2(shape) if kind == 'box' else (shape[0]-r, shape[1]-r, shape[0]+r, shape[1]+r)
            box = b if box is None else (min(box[0], b[0]), min(box[1], b[1]), max(box[2], b[2]), max(box[3], b[3]))
        for v in grid.query(box):
            best = None
            for kind, shape, zr in shapes:
                if g.z_overlap(zr, v['z']) <= 0: continue
                if kind == 'box':
                    pen = g.penetration(shape, v['poly']); inside = g.inside(it['pos'][:2], v['poly'])
                else:
                    sd = g.signed_distance(shape[:2], v['poly']); pen = r - sd; inside = sd < 0
                if pen > 1e-6 and (best is None or pen > best[0]): best = (pen, inside)
            if best is None: continue
            coincident = math.dist(v['origin_xyz'], it['pos']) < a['coincident']
            enclosed = best[1] and v['z'][0] <= it['pos'][2] <= v['z'][1]
            deep = best[0] >= a['deep'] or coincident
            findings.append(finding(
                'interaction_overlap', 'defect' if deep else 'inspect', it['pos'],
                interaction=it['name'], entity_id=it['id'], entity_class=it['cls'], shape=it['kind'],
                volume=v['id'], volume_origin=v['origin'], surface=v['surface'], blocks=v['blocks'],
                penetration_m=round(best[0], 3), use_point_enclosed=enclosed,
                origin_coincident=coincident, mesh=v['mesh']))
    return findings, dict(modelled_interactions=dict(sorted(modelled.items())))


def check_duplicates(vols, a):
    tol = a['duplicate_tolerance']; buckets = defaultdict(list); findings = []
    for v in vols: buckets[tuple(math.floor(c / 0.5) for c in v['origin_xyz'])].append(v)
    seen = set()
    for v in vols:
        key = tuple(math.floor(c / 0.5) for c in v['origin_xyz'])
        near = [w for dx in (-1, 0, 1) for dy in (-1, 0, 1) for dz in (-1, 0, 1)
                for w in buckets.get((key[0]+dx, key[1]+dy, key[2]+dz), ())]
        for w in near:
            if w is v or (w['id'], v['id']) in seen or w['origin'] != v['origin']: continue
            if (math.dist(v['origin_xyz'], w['origin_xyz']) < tol and
                    max(abs(p - q) for p, q in zip(v['world_aabb'], w['world_aabb'])) < tol):
                seen.add((v['id'], w['id']))
                same = v['surface'] == w['surface']
                findings.append(finding('duplicate_volume', 'defect' if same else 'inspect', v['origin_xyz'],
                                        volumes=[v['id'], w['id']], surfaces=[v['surface'], w['surface']],
                                        meshes=[v['mesh'], w['mesh']], volume_origin=v['origin']))
    return findings


def _panel_axis(v, a):
    """Long plan axis of a panel: start point, unit direction, length, end segments, expanded rectangle."""
    lo, hi = v['local_min'], v['local_max']; m = v['matrix']
    sx = math.hypot(m[0], m[4]) * (hi[0]-lo[0]); sy = math.hypot(m[1], m[5]) * (hi[1]-lo[1])
    zm = (lo[2]+hi[2]) / 2; c = a['contact']
    def w(x, y): return g.transform(m, (x, y, zm))[:2]
    if sx >= sy:
        ends = [(w(lo[0], lo[1]), w(lo[0], hi[1])), (w(hi[0], lo[1]), w(hi[0], hi[1]))]
    else:
        ends = [(w(lo[0], lo[1]), w(hi[0], lo[1])), (w(lo[0], hi[1]), w(hi[0], hi[1]))]
    s0 = ((ends[0][0][0]+ends[0][1][0])/2, (ends[0][0][1]+ends[0][1][1])/2)
    s1 = ((ends[1][0][0]+ends[1][1][0])/2, (ends[1][0][1]+ends[1][1][1])/2)
    length = math.dist(s0, s1); d = ((s1[0]-s0[0])/length, (s1[1]-s0[1])/length) if length > 1e-9 else (1.0, 0.0)
    n = (-d[1], d[0])
    half = max(g.point_segment_distance(p, s0, s1)[0] for p in v['poly']) + c
    rect = g.convex_hull([(s0[0]-d[0]*c + n[0]*k*half, s0[1]-d[1]*c + n[1]*k*half) for k in (-1, 1)] +
                         [(s1[0]+d[0]*c + n[0]*k*half, s1[1]+d[1]*c + n[1]*k*half) for k in (-1, 1)])
    return s0, d, length, ends, rect


def _ends(v):
    return _panel_axis(v, ASSUMPTIONS)[3]


def _edge_distance(seg, extent):
    x0, y0, x1, y1 = extent
    rect = [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]
    if not (g.inside(seg[0], rect) and g.inside(seg[1], rect)): return 0.0
    return min(g.segment_distance(seg[0], seg[1], c, d) for c, d in g.edges(rect))


def ring_volumes(vols):
    return [v for v in vols if v['origin'] == 'package' and v['barrier'] and v['barrier'].get('monolog') == MAP_EXIT_MONOLOG]


def check_boundary(world, vols, a):
    ring = ring_volumes(vols); extent = world['extent']; findings = []
    if not ring:
        return [finding('boundary_missing', 'defect', (extent[2]/2, extent[3]/2, None),
                        detail='No outer level-barrier volumes in the package')], dict(panels=0, components=0)
    parent = list(range(len(ring)))
    def root(i):
        while parent[i] != i: parent[i] = parent[parent[i]]; i = parent[i]
        return i
    for i in range(len(ring)):
        for j in range(i+1, len(ring)):
            if g.polygon_distance(ring[i]['poly'], ring[j]['poly']) <= a['contact']: parent[root(i)] = root(j)
    gaps = []
    for i, v in enumerate(ring):
        s0, d, length, ends, rect = _panel_axis(v, a)
        # Attachment: where along the panel does each touching barrier make contact?
        attached = [False, False]
        for j, w in enumerate(ring):
            if j == i or g.polygon_distance(v['poly'], w['poly']) > a['contact']: continue
            region = g.clip(w['poly'], rect)
            ts = [(p[0]-s0[0])*d[0] + (p[1]-s0[1])*d[1] for p in region] or [length / 2]
            if min(ts) <= length / 2: attached[0] = True
            if max(ts) >= length / 2: attached[1] = True
        for k, seg in enumerate(ends):
            d_edge = _edge_distance(seg, extent)
            if attached[k] or d_edge <= a['contact']: continue
            others = [(g.segment_polygon_distance(seg[0], seg[1], w['poly']), w) for j, w in enumerate(ring) if j != i]
            d_vol, near = min(others, key=lambda t: t[0]) if others else (math.inf, None)
            gap = min(d_vol, d_edge)
            mid = ((seg[0][0]+seg[1][0])/2, (seg[0][1]+seg[1][1])/2, None)
            gaps.append(finding('boundary_gap', 'defect' if gap >= a['gap_defect'] else 'inspect', mid,
                                gap_m=round(gap, 2), panel=v['id'], nearest_panel=near['id'] if near else None,
                                to_terrain_edge_m=round(d_edge, 2), passable_player=gap > a['player_gap'],
                                passable_horse=gap > a['horse_gap'], mesh=v['mesh']))
    # Both ends of one gap usually report it; keep the first of any pair within gap+1 m.
    for f in sorted(gaps, key=lambda f: -f['gap_m']):
        if not any(math.hypot(f['x']-h['x'], f['y']-h['y']) <= f['gap_m'] + 1.0 for h in findings): findings.append(f)
    components = len({root(i) for i in range(len(ring))})
    if components > 1 and not findings:
        findings.append(finding('boundary_disconnected', 'inspect', (extent[2]/2, extent[3]/2, None),
                                components=components))
    return findings, dict(panels=len(ring), components=components,
                          surfaces=dict(Counter(v['surface'] for v in ring)))


def check_roads(world, vols, a):
    findings = []; extent = world['extent']
    grid = g.Grid(32.0)
    for v in vols:
        if v['origin'] == 'package' and v['blocks']: grid.add(g.bbox2(v['poly']), v)
    ring_ids = {v['id'] for v in ring_volumes(vols)}
    for road in world['roads']:
        c = road['center']; reported = set()
        for k in range(len(c) - 1):
            p, q = c[k][:2], c[k+1][:2]; half = max(road['widths'][k], road['widths'][k+1]) / 2
            box = (min(p[0], q[0])-half, min(p[1], q[1])-half, max(p[0], q[0])+half, max(p[1], q[1])+half)
            for v in grid.query(box):
                if v['id'] in reported: continue
                d = g.segment_polygon_distance(p, q, v['poly'])
                if d >= half: continue
                reported.add(v['id'])
                at = ((p[0]+q[0])/2, (p[1]+q[1])/2, (c[k][2]+c[k+1][2])/2)
                if v['id'] in ring_ids:
                    findings.append(finding('road_crosses_barrier', 'inspect', at, road=road['id'],
                                            volume=v['id'], surface=v['surface'], centerline_hits=d == 0,
                                            road_width_m=round(2*half, 2),
                                            note='Road runs into the outer level barrier; barrier/monologue behaviour is native'))
                else:
                    pen = half - d
                    findings.append(finding('road_blocked', 'defect' if d == 0 and pen >= a['deep'] else 'inspect', at,
                                            road=road['id'], volume=v['id'], surface=v['surface'], blocks=v['blocks'],
                                            penetration_m=round(pen, 2), road_width_m=round(2*half, 2)))
        for pt in (c[0], c[-1]):
            de = min(pt[0]-extent[0], pt[1]-extent[1], extent[2]-pt[0], extent[3]-pt[1])
            if de <= a['road_edge_margin']:
                findings.append(finding('road_reaches_map_edge', 'inspect', pt, road=road['id'],
                                        distance_to_edge_m=round(de, 2)))
    return findings


def sites(findings, radius=40.0):
    """Group findings of one category within ``radius`` m (single linkage) for checklists."""
    out = []
    for f in sorted(findings, key=lambda f: (f['category'], f['x'], f['y'])):
        hit = [s for s in out if s['category'] == f['category'] and
               any(math.hypot(f['x']-m[0], f['y']-m[1]) <= radius for m in s['_pts'])]
        if hit:
            s = hit[0]
            for other in hit[1:]: s['_pts'] += other['_pts']; s['_f'] += other['_f']; out.remove(other)
        else:
            s = dict(category=f['category'], _pts=[], _f=[]); out.append(s)
        s['_pts'].append((f['x'], f['y'])); s['_f'].append(f)
    result = []
    for s in out:
        xs = [p[0] for p in s['_pts']]; ys = [p[1] for p in s['_pts']]
        result.append(dict(category=s['category'], x=round(sum(xs)/len(xs), 1), y=round(sum(ys)/len(ys), 1),
                           findings=len(s['_f']), severity='defect' if any(f['severity'] == 'defect' for f in s['_f']) else 'inspect',
                           roads=len({f.get('road') for f in s['_f'] if f.get('road')}),
                           volumes=sorted({f['volume'] for f in s['_f'] if f.get('volume')})))
    return sorted(result, key=lambda s: (s['category'], s['x']))


def status_of(findings, unsupported=False):
    if unsupported: return 'UNSUPPORTED'
    if any(f['severity'] == 'defect' for f in findings): return 'FAIL'
    if findings: return 'REVIEW'
    return 'PASS'


def audit(world, assumptions=None):
    a = dict(ASSUMPTIONS, **(assumptions or {}))
    vols = prepare(world)
    unresolved = world.get('unsupported', [])
    # Source-reconstruction gaps never decide the package verdict.
    pkg_unresolved = [u for u in unresolved if not str(u.get('item', '')).startswith('kcd1_source')]
    vol_unsupported = [u for u in pkg_unresolved if not str(u.get('item', '')).startswith('road')]
    road_unsupported = [u for u in pkg_unresolved if str(u.get('item', '')).startswith('road')]
    unknown_surface = sorted({v['surface'] for v in vols if v['blocks'] is None and v['origin'] == 'package'})
    unknown_source_surface = sorted({v['surface'] for v in vols if v['blocks'] is None and v['origin'] != 'package'})
    pkg = [v for v in vols if v['origin'] == 'package']; src = [v for v in vols if v['origin'] != 'package']
    checks = []
    inter, extra = check_interactions(dict(world, interactions=world['interactions']), [v for v in pkg if v['blocks'] is not None], a)
    checks.append(dict(name='interaction_clearance', status=status_of(inter, bool(vol_unsupported or unknown_surface)),
                       findings=inter, **extra))
    dup = check_duplicates(pkg, a)
    checks.append(dict(name='duplicate_volumes', status=status_of(dup, bool(vol_unsupported)), findings=dup))
    bound, info = check_boundary(world, pkg, a)
    checks.append(dict(name='boundary_closure', status=status_of(bound, bool(vol_unsupported)), findings=bound, **info))
    roads = check_roads(world, pkg, a)
    no_roads = not world['roads']
    checks.append(dict(name='road_crossings', status=status_of(roads, bool(road_unsupported) or no_roads),
                       findings=roads, roads=len(world['roads']), sites=sites(roads),
                       **({'unsupported_reason': 'no road records read'} if no_roads else {})))
    if src:
        sf, _ = check_interactions(world, [v for v in src if v['blocks'] is not None], a)
        sd = check_duplicates(src, a)
        checks.append(dict(name='source_reconstruction', status='INFO', findings=sf + sd,
                           note='Every KCD1 designer collision volume placed (pre-policy reconstruction); regression evidence only, '
                                'never part of the package verdict.',
                           unknown_surfaces=unknown_source_surface,
                           unresolved=len(unresolved) - len(pkg_unresolved),
                           summary=_summary(sf + sd)))
    verdict = [c['status'] for c in checks if c['status'] != 'INFO']
    overall = ('UNSUPPORTED' if 'UNSUPPORTED' in verdict else 'FAIL' if 'FAIL' in verdict
               else 'REVIEW' if 'REVIEW' in verdict else 'PASS')
    return dict(schema=1, native_runtime_verified=False, status=overall, source=world.get('source'),
                assumptions=a, not_modelled=NOT_MODELLED, unsupported=unresolved,
                unknown_surfaces=unknown_surface, extent=world['extent'],
                surface_table=world.get('surface_table'), hashes=world.get('hashes', {}),
                inventory=inventory(world, vols), checks=checks)


def _summary(findings):
    c = Counter((f['category'], f['severity'], f.get('surface'), f.get('entity_class')) for f in findings)
    return [dict(category=k[0], severity=k[1], surface=k[2], entity_class=k[3], count=n) for k, n in sorted(c.items(), key=str)]


def inventory(world, vols=None):
    vols = prepare(world) if vols is None else vols
    pkg = [v for v in vols if v['origin'] == 'package']
    return dict(
        extent=world['extent'], placed_brushes=world.get('placed_brushes'),
        designer_volumes=len(pkg),
        by_surface=dict(Counter(v['surface'] for v in pkg)),
        by_layer=dict(Counter(str(v['layer']) for v in pkg)),
        blocking_agents=dict(Counter(','.join(v['blocks'] or ['UNKNOWN']) for v in pkg)),
        bounds_source=dict(Counter(v['bounds_source'] for v in pkg)),
        source_volumes=len(vols) - len(pkg),
        source_by_surface=dict(Counter(v['surface'] for v in vols if v['origin'] != 'package')),
        interactions=dict(Counter(i['cls'] for i in world['interactions'])),
        roads=len(world['roads']), entity_classes=world.get('entity_classes', {}),
        unsupported=len(world.get('unsupported', [])))
