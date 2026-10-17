"""Give converted building blend materials non-overlapping secondary UV charts.

Only render vertices are duplicated at chart seams. Physics chunks, node
transforms, primary UVs, positions, normals and tangents retain their values.
"""
import struct

import numpy as np

from clothing_regions import read_chunks, write_chunks


def render_material_ids(blob):
    """Return slots actually drawn by this mesh, excluding physics proxies."""
    chunks = read_chunks(blob)
    lookup = {c.id:c for c in chunks}
    result = set()
    for mesh in chunks:
        if mesh.kind != 0x1000 or mesh.version not in (0x800, 0x801):
            continue
        flags, _, nv, _, ns, sid = struct.unpack_from('<6I', mesh.data)
        if not nv or flags & 1: continue
        subset = lookup[sid]
        if subset.version != 0x800 or len(subset.data) < 16+ns*36:
            raise ValueError('Unsupported building subsets')
        for i in range(ns):
            _, count, _, _, material = struct.unpack_from('<5I', subset.data, 16+i*36)
            if count: result.add(material)
    return result


def _overlaps(a, b, eps=1e-7):
    """True when two 2D triangles overlap with positive area (shared edges/vertices only touch)."""
    for t in (a, b):
        e = np.roll(t, -1, 0)-t
        for axis in np.stack([-e[:, 1], e[:, 0]], 1):
            length = np.hypot(*axis)
            if length < 1e-12:
                continue
            pa, pb = a @ axis/length, b @ axis/length
            if min(pa.max(), pb.max())-max(pa.min(), pb.min()) <= eps:
                return False
    return True


def secondary_charts(positions, faces, uv0, uv2, limit=np.inf):
    """Assign faces to charts that are continuous in position, UV0 and UV2 and never overlap in UV2.

    Render vertices are duplicated wherever any attribute is discontinuous, so
    edges are matched by attribute values rather than indices. A face joins a
    neighbour's chart only if its UV2 triangle overlaps none already there:
    authored UV2 layouts reuse texture space, which the bake must separate.
    Charts grow breadth-first and stop at a 3D bounding diagonal of `limit`,
    so long strips cannot dictate the packing scale.
    """
    from collections import deque
    def key(v):
        return (tuple(np.round(positions[v], 4)), tuple(np.round(uv0[v], 5)), tuple(np.round(uv2[v], 5)))
    corner = [[key(v) for v in face] for face in faces]
    edges = {}
    for f, keys in enumerate(corner):
        for i in range(3):
            edges.setdefault(frozenset((keys[i], keys[(i+1) % 3])), []).append(f)
    neighbours = [[] for _ in faces]
    for shared in edges.values():
        for f in shared:
            neighbours[f].extend(g for g in shared if g != f)
    tri2 = uv2[faces].astype(np.float64)
    tri3 = positions[faces].astype(np.float64)
    chart = np.full(len(faces), -1, np.int64)
    # Typical-triangle grid cells, but never more than 1024 across the layout,
    # so one very large face cannot occupy an unbounded number of cells.
    cell = max(float(np.median(np.ptp(tri2, axis=1).max(1))), float(np.ptp(tri2.reshape(-1, 2), axis=0).max())/1024, 1e-6)
    count = 0
    for seed in range(len(faces)):
        if chart[seed] >= 0:
            continue
        grid, queue = {}, deque([seed])
        box_lo, box_hi = tri3[seed].min(0), tri3[seed].max(0)
        def cells(f):
            lo, hi = np.floor(tri2[f].min(0)/cell).astype(int), np.floor(tri2[f].max(0)/cell).astype(int)
            return [(x, y) for x in range(lo[0], hi[0]+1) for y in range(lo[1], hi[1]+1)]
        while queue:
            f = queue.popleft()
            if chart[f] >= 0:
                continue
            lo, hi = np.minimum(box_lo, tri3[f].min(0)), np.maximum(box_hi, tri3[f].max(0))
            if f != seed and np.linalg.norm(hi-lo) > limit:
                continue
            near = {g for c in cells(f) for g in grid.get(c, ())}
            if f != seed and any(_overlaps(tri2[f], tri2[g]) for g in near):
                continue
            box_lo, box_hi = lo, hi
            chart[f] = count
            for c in cells(f):
                grid.setdefault(c, []).append(f)
            queue.extend(g for g in neighbours[f] if chart[g] < 0)
        count += 1
    return chart


def _orientation(points):
    """Rotation giving a chart its minimum-area bounding rectangle, turned landscape."""
    pts = np.unique(np.round(points, 9), axis=0)
    if len(pts) < 3:
        return np.eye(2)
    pts = pts[np.lexsort((pts[:, 1], pts[:, 0]))]
    def half(seq):
        hull = []
        for p in seq:
            while len(hull) >= 2 and ((hull[-1][0]-hull[-2][0])*(p[1]-hull[-2][1])
                                      - (hull[-1][1]-hull[-2][1])*(p[0]-hull[-2][0])) <= 0:
                hull.pop()
            hull.append(p)
        return hull[:-1]
    hull = np.array(half(pts)+half(pts[::-1]))
    best, rotation = np.inf, np.eye(2)
    for edge in np.roll(hull, -1, 0)-hull:
        angle = np.arctan2(edge[1], edge[0])
        c, s = np.cos(angle), np.sin(angle)
        r = np.array([[c, s], [-s, c]])
        extent = np.ptp(hull @ r.T, axis=0)
        if extent[0]*extent[1] < best:
            best, rotation = extent[0]*extent[1], r if extent[0] >= extent[1] else np.array([[0, 1], [-1, 0]]) @ r
    return rotation


def _pack_charts(layout, owner, resolution, chart_scale=None, padding=8):
    """Place rigid charts on shelves, at the largest uniform scale fitting resolution.

    Each chart may first be scaled (chart_scale, for uniform world-space
    texel density) and is rotated to its minimum bounding rectangle; the bake
    maps every triangle independently, so neither changes what it samples.
    Returns texel coordinates per vertex and the used atlas width/height.
    Every chart keeps `padding` texels of clearance for bilinear sampling.
    """
    count = int(owner.max())+1
    layout = layout.copy()
    for c in range(count):
        members = owner == c
        points = layout[members]
        points = (points-points.mean(0))*(chart_scale[c] if chart_scale is not None else 1)
        layout[members] = points @ _orientation(points).T
    low = np.full((count, 2), np.inf); high = np.full_like(low, -np.inf)
    np.minimum.at(low, owner, layout); np.maximum.at(high, owner, layout)
    extent = high-low
    order = np.argsort(-extent[:, 1], kind='stable')

    def shelves(scale):
        cells = np.ceil(extent*scale)+2*padding
        if cells.max() > resolution:
            return None
        offset = np.zeros((count, 2)); x = y = row = used = 0.0
        for c in order:
            w, h = cells[c]
            if x+w > resolution:
                x, y, row = 0.0, y+row, 0.0
            offset[c] = x, y
            x += w; row = max(row, h); used = max(used, x)
        return (offset, used, y+row) if y+row <= resolution else None

    span = float(extent.max())
    if span <= 0:
        scale = 1.0
    else:
        lo, hi = 0.0, (resolution-2*padding)/span
        for _ in range(40):
            mid = (lo+hi)/2
            lo, hi = (mid, hi) if shelves(mid) is not None else (lo, mid)
        scale = lo
    placed = shelves(scale)
    if placed is None:
        raise ValueError('Building blend charts do not fit the atlas resolution')
    offset, width, height = placed
    texels = (layout-low[owner])*scale+offset[owner]+padding
    return texels, int(np.ceil(width)), int(np.ceil(height)), scale, extent*scale


def _split_long_charts(chart, long, tri2):
    """Cut each listed chart in two across its longest UV2 direction (at the median face).

    Halves of an overlap-free, seam-free chart stay overlap-free and seam-free;
    the cut edge's sides sit in separate padded charts after packing.
    """
    chart = chart.copy()
    centre = tri2.mean(1)
    for c in long:
        members = np.flatnonzero(chart == c)
        if len(members) < 2:
            continue
        points = centre[members]-centre[members].mean(0)
        axis = np.linalg.svd(points, full_matrices=False)[2][0]
        projection = points @ axis
        half = members[projection > np.median(projection)]
        if 0 < len(half) < len(members):
            chart[half] = chart.max()+1
    return chart


def reatlas(blob, material_id, resolution=2048):
    chunks = read_chunks(blob)
    lookup = {c.id: c for c in chunks}
    replacements = {}
    matches = []
    for mesh in chunks:
        if mesh.kind != 0x1000 or mesh.version not in (0x800, 0x801):
            continue
        flags, _, nv, ni, ns, sid = struct.unpack_from('<6I', mesh.data)
        if not nv or flags & 1:
            continue
        ids = struct.unpack_from('<16I', mesh.data, 28)
        subset = lookup[sid]
        if subset.version != 0x800 or len(subset.data) < 16 + ns * 36:
            raise ValueError('Unsupported building subsets')
        ranges = []
        for i in range(ns):
            first, count, _, _, mat = struct.unpack_from('<5I', subset.data, 16+i*36)
            if mat == material_id:
                ranges.append((i, first, count))
        if ranges:
            matches.append((mesh, nv, ni, ids, subset, ranges))
    if len(matches) != 1:
        raise ValueError('Blend atlas requires exactly one render mesh per material')
    mesh, nv, ni, ids, subset, ranges = matches[0]
    streams = {}
    for kind, ident in enumerate(ids):
        if not ident:
            continue
        c = lookup[ident]
        _, stream_kind, count, width = struct.unpack_from('<4I', c.data)
        if c.kind != 0x1016 or c.version != 0x800 or stream_kind != kind or len(c.data) != 24+count*width:
            raise ValueError('Unsupported building vertex stream')
        if count != (ni if kind == 5 else nv):
            raise ValueError('Building stream count mismatch')
        streams[kind] = (c, width)
    if 8 not in streams or streams[8][1] != 8 or streams[2][1] != 8:
        raise ValueError('Blend atlas requires float primary and secondary UV streams')
    pos, width = streams[0]
    if width not in (8, 12):
        raise ValueError('Unsupported position stream')
    positions = np.frombuffer(pos.data, '<f2' if width == 8 else '<f4', offset=24).reshape(nv, width//(2 if width == 8 else 4))[:, :3].astype(np.float32)
    index_chunk, width = streams[5]
    if width not in (2, 4):
        raise ValueError('Unsupported building indices')
    indices = np.frombuffer(index_chunk.data, '<u2' if width == 2 else '<u4', offset=24).astype(np.uint32)
    selected = np.concatenate([np.arange(first, first+count) for _, first, count in ranges])
    faces = indices[selected].reshape(-1, 3)
    if indices.max() >= nv:
        raise ValueError('Invalid building index')
    uv0 = np.frombuffer(streams[2][0].data, '<f4', offset=24).reshape(-1, 2)
    uv2 = np.frombuffer(streams[8][0].data, '<f4', offset=24).reshape(-1, 2)
    # Charts must be seam-free and overlap-free in the source UV2, and must
    # keep their exact shape so the bake samples the authored texels. xatlas
    # merges faces across seams, drops slivers and reshapes or splits UV
    # charts, so charts are built and packed here. Each chart gets its own
    # copy of its vertices; faces keep their order and corner identity.
    # Zero-area UV2 faces (needles; some source panels were never unwrapped
    # and span thousands of units) carry no bakeable texels but would set the
    # packing scale. Give each its own chart collapsed to a point: it bakes
    # nothing and renders without the secondary layer.
    tri2 = uv2[faces].astype(np.float64)
    e1, e2 = tri2[:, 1]-tri2[:, 0], tri2[:, 2]-tri2[:, 0]
    area = np.abs(e1[:, 0]*e2[:, 1]-e1[:, 1]*e2[:, 0])/2
    needle = area <= 1e-6*np.ptp(tri2, axis=1).max(1)**2
    chart = np.empty(len(faces), np.int64)
    kept = np.flatnonzero(~needle)
    tri3 = positions[faces].astype(np.float64)
    area3 = np.linalg.norm(np.cross(tri3[:, 1]-tri3[:, 0], tri3[:, 2]-tri3[:, 0]), axis=1)/2
    limit = max(np.sqrt(area3[kept].sum())/2, 1e-6) if len(kept) else np.inf
    chart[kept] = secondary_charts(positions, faces[kept], uv0, uv2, limit) if len(kept) else []
    chart[needle] = (chart[kept].max()+1 if len(kept) else 0)+np.arange(int(needle.sum()))
    best = None
    shrink = {}
    for _ in range(8):
        pairs = np.stack([np.repeat(chart, 3), faces.reshape(-1)], 1)
        unique, inverse = np.unique(pairs, axis=0, return_inverse=True)
        layout = uv2[unique[:, 1]].astype(np.float64)
        layout[np.isin(unique[:, 0], chart[needle])] = 0
        # Scale charts to uniform world-space texel density. Authored UV2 scale
        # varies wildly (faces tiling a texture hundreds of times), and keeping
        # it would let a few such charts shrink every other chart to nothing.
        sum3 = np.bincount(chart, np.where(needle, 0, area3), chart.max()+1)
        sum2 = np.bincount(chart, np.where(needle, 0, area), chart.max()+1)
        chart_scale = np.where((sum2 > 0) & (sum3 > 0), np.sqrt(sum3/np.maximum(sum2, 1e-300)), 1.0)
        # Near-degenerate UV2 charts (tiny UV2 area, real 3D area) would be
        # enlarged without bound and dictate the packing scale. Cap enlargement
        # at 4x the area-weighted median chart scale; shrinking stays unbounded.
        if (sum3 > 0).any():
            ordered = np.argsort(chart_scale)
            weight = np.cumsum(sum3[ordered])
            typical = chart_scale[ordered][np.searchsorted(weight, weight[-1]/2)]
            chart_scale = np.minimum(chart_scale, 4*typical)
        for c, factor in shrink.items():
            chart_scale[c] *= factor
        texels, width, height, scale, spans = _pack_charts(layout, unique[:, 0], resolution, chart_scale)
        if best is None or scale > best[0]:
            best = (scale, unique, inverse, texels, width, height)
        # One long chart can fix the scale while most of the atlas stays empty
        # (a 2048x512 result). Cut such charts and repack; keep the densest.
        long = np.flatnonzero(spans.max(1) > resolution/4)
        if width*height >= resolution*resolution/2 or not len(long):
            break
        # Multi-face charts are cut; a single long face (a beam or strip) is
        # instead given lower density, so it no longer sets the whole atlas.
        faces_per_chart = np.bincount(chart, minlength=len(spans))
        for c in long[faces_per_chart[long] < 2]:
            shrink[c] = shrink.get(c, 1.0)*(resolution/4)/spans[c].max()
        chart = _split_long_charts(chart, long[faces_per_chart[long] >= 2], tri2)
    _, unique, inverse, texels, width, height = best
    mapping = unique[:, 1].astype(np.uint32)
    new_faces = inverse.reshape(-1, 3).astype(np.uint32)
    size = tuple(1 << (int(v)-1).bit_length() for v in (width, height))
    uv = (texels/np.array(size)).astype(np.float32)
    if not np.array_equal(mapping[new_faces], faces):
        raise ValueError('Atlas changed building triangle correspondence')
    triangles = list(zip(uv0[faces], uv2[faces], uv[new_faces]))
    for kind, (chunk, width) in streams.items():
        if kind == 5:
            continue
        source = np.frombuffer(chunk.data, 'u1', offset=24).reshape(nv, width)
        extra = uv.astype('<f4').view('u1').reshape(-1, 8) if kind == 8 else source[mapping]
        header = bytearray(chunk.data[:24])
        struct.pack_into('<I', header, 8, nv+len(mapping))
        replacements[chunk.id] = bytes(header)+source.tobytes()+extra.tobytes()
    indices[selected] = nv+new_faces.reshape(-1)
    index_header = bytearray(index_chunk.data[:24])
    width = 2 if indices.max() < 65536 else 4
    struct.pack_into('<I', index_header, 12, width)
    replacements[index_chunk.id] = bytes(index_header)+indices.astype('<u2' if width == 2 else '<u4').tobytes()
    subset_data = bytearray(subset.data)
    for i, first, count in ranges:
        used = indices[first:first+count]
        struct.pack_into('<2I', subset_data, 16+i*36+8, int(used.min()), int(used.max()-used.min()+1))
    replacements[subset.id] = bytes(subset_data)
    mesh_data = bytearray(mesh.data)
    struct.pack_into('<I', mesh_data, 8, nv+len(mapping))
    replacements[mesh.id] = bytes(mesh_data)
    return write_chunks(chunks, replacements), triangles, size
