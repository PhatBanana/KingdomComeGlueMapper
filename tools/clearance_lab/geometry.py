"""Small exact 2D/3D helpers (standard library only).

Volumes are oriented boxes: a 3x4 row-major brush matrix applied to a mesh's
local AABB. Plan-view checks use the convex hull of the eight projected corners,
which is exact for z-axis rotations and conservative (larger) otherwise.
"""
import math

EPS = 1e-9


def quat_matrix(w, x, y, z, position=(0.0, 0.0, 0.0)):
    """CryEngine XML Rotate is w,x,y,z. Returns a 3x4 row-major matrix."""
    n = math.sqrt(w*w + x*x + y*y + z*z)
    if n < EPS: raise ValueError('Zero rotation quaternion')
    w, x, y, z = w/n, x/n, y/n, z/n
    return (1-2*(y*y+z*z), 2*(x*y-z*w), 2*(x*z+y*w), position[0],
            2*(x*y+z*w), 1-2*(x*x+z*z), 2*(y*z-x*w), position[1],
            2*(x*z-y*w), 2*(y*z+x*w), 1-2*(x*x+y*y), position[2])


def transform(m, p):
    return (m[0]*p[0]+m[1]*p[1]+m[2]*p[2]+m[3],
            m[4]*p[0]+m[5]*p[1]+m[6]*p[2]+m[7],
            m[8]*p[0]+m[9]*p[1]+m[10]*p[2]+m[11])


def box_corners(m, lo, hi):
    return [transform(m, (x, y, z)) for x in (lo[0], hi[0]) for y in (lo[1], hi[1]) for z in (lo[2], hi[2])]


def convex_hull(points):
    pts = sorted(set((round(p[0], 6), round(p[1], 6)) for p in points))
    if len(pts) <= 2: return pts
    def cross(o, a, b): return (a[0]-o[0])*(b[1]-o[1]) - (a[1]-o[1])*(b[0]-o[0])
    lower, upper = [], []
    for p in pts:
        while len(lower) >= 2 and cross(lower[-2], lower[-1], p) <= 0: lower.pop()
        lower.append(p)
    for p in reversed(pts):
        while len(upper) >= 2 and cross(upper[-2], upper[-1], p) <= 0: upper.pop()
        upper.append(p)
    return lower[:-1] + upper[:-1]


def footprint(m, lo, hi):
    """(plan polygon CCW, (zmin, zmax)) of an oriented box."""
    c = box_corners(m, lo, hi)
    return convex_hull(c), (min(p[2] for p in c), max(p[2] for p in c))


def edges(poly):
    return [(poly[i], poly[(i+1) % len(poly)]) for i in range(len(poly))]


def point_segment_distance(p, a, b):
    dx, dy = b[0]-a[0], b[1]-a[1]
    L = dx*dx + dy*dy
    t = 0.0 if L < EPS else max(0.0, min(1.0, ((p[0]-a[0])*dx + (p[1]-a[1])*dy) / L))
    q = (a[0]+t*dx, a[1]+t*dy)
    return math.hypot(p[0]-q[0], p[1]-q[1]), q


def inside(p, poly):
    if len(poly) < 3: return False
    for a, b in edges(poly):
        if (b[0]-a[0])*(p[1]-a[1]) - (b[1]-a[1])*(p[0]-a[0]) < -1e-9: return False
    return True


def signed_distance(p, poly):
    """Plan distance from a point to a convex polygon; negative inside."""
    d = min(point_segment_distance(p, a, b)[0] for a, b in edges(poly)) if len(poly) > 1 else math.dist(p, poly[0])
    return -d if inside(p, poly) else d


def _orient(a, b, c):
    v = (b[0]-a[0])*(c[1]-a[1]) - (b[1]-a[1])*(c[0]-a[0])
    return 0 if abs(v) < 1e-12 else (1 if v > 0 else -1)


def segments_intersect(a, b, c, d):
    o1, o2, o3, o4 = _orient(a, b, c), _orient(a, b, d), _orient(c, d, a), _orient(c, d, b)
    if o1 != o2 and o3 != o4: return True
    def on(p, q, r): return min(p[0], r[0])-1e-12 <= q[0] <= max(p[0], r[0])+1e-12 and min(p[1], r[1])-1e-12 <= q[1] <= max(p[1], r[1])+1e-12
    return ((o1 == 0 and on(a, c, b)) or (o2 == 0 and on(a, d, b)) or
            (o3 == 0 and on(c, a, d)) or (o4 == 0 and on(c, b, d)))


def segment_distance(a, b, c, d):
    if segments_intersect(a, b, c, d): return 0.0
    return min(point_segment_distance(a, c, d)[0], point_segment_distance(b, c, d)[0],
               point_segment_distance(c, a, b)[0], point_segment_distance(d, a, b)[0])


def segment_polygon_distance(a, b, poly):
    if inside(a, poly) or inside(b, poly): return 0.0
    return min(segment_distance(a, b, c, d) for c, d in edges(poly))


def polygon_distance(p, q):
    if inside(p[0], q) or inside(q[0], p): return 0.0
    return min(segment_distance(a, b, c, d) for a, b in edges(p) for c, d in edges(q))


def penetration(p, q):
    """SAT minimum overlap of two convex polygons (0 when separated)."""
    best = math.inf
    for poly in (p, q):
        for a, b in edges(poly):
            nx, ny = b[1]-a[1], -(b[0]-a[0])
            L = math.hypot(nx, ny)
            if L < EPS: continue
            nx, ny = nx/L, ny/L
            pa = [v[0]*nx + v[1]*ny for v in p]; qa = [v[0]*nx + v[1]*ny for v in q]
            overlap = min(max(pa), max(qa)) - max(min(pa), min(qa))
            if overlap <= 0: return 0.0
            best = min(best, overlap)
    return 0.0 if best is math.inf else best


def clip(subject, clipper):
    """Sutherland-Hodgman: subject polygon clipped by a convex CCW clipper."""
    out = list(subject)
    for a, b in edges(clipper):
        if not out: break
        src, out = out, []
        def side(p): return (b[0]-a[0])*(p[1]-a[1]) - (b[1]-a[1])*(p[0]-a[0])
        for i, cur in enumerate(src):
            prev = src[i-1]; sc, sp = side(cur), side(prev)
            if sc >= 0:
                if sp < 0: out.append(_cut(prev, cur, sp, sc))
                out.append(cur)
            elif sp >= 0: out.append(_cut(prev, cur, sp, sc))
    return out


def _cut(p, q, sp, sq):
    t = sp / (sp - sq)
    return (p[0] + t*(q[0]-p[0]), p[1] + t*(q[1]-p[1]))


def z_overlap(a, b):
    return min(a[1], b[1]) - max(a[0], b[0])


def bbox2(poly):
    xs = [v[0] for v in poly]; ys = [v[1] for v in poly]
    return min(xs), min(ys), max(xs), max(ys)


class Grid:
    """Uniform plan hash for candidate pairs; never decides an outcome."""
    def __init__(self, cell=32.0):
        self.cell = cell; self.cells = {}

    def keys(self, box):
        c = self.cell
        for i in range(math.floor(box[0]/c), math.floor(box[2]/c)+1):
            for j in range(math.floor(box[1]/c), math.floor(box[3]/c)+1):
                yield i, j

    def add(self, box, item):
        for k in self.keys(box): self.cells.setdefault(k, []).append(item)

    def query(self, box):
        seen = set(); out = []
        for k in self.keys(box):
            for item in self.cells.get(k, ()):
                if id(item) not in seen: seen.add(id(item)); out.append(item)
        return out
