"""Intersect native clip volumes with measured building-shell half-spaces.

The rendered stencil and the CPU containment BSP must describe the same solid.
Changing only its bounds, probe box, or BSP leaves one of those paths wrong.
All planes use n.dot(position) + d <= 0 for the retained interior.
"""
from collections import Counter
import struct

import numpy as np

from clothing_regions import read_chunks, write_chunks
from lighting_clips import clip_geometry


def normalized_plane(plane):
    plane = np.asarray(plane, dtype=np.float64)
    if plane.shape != (4,) or not np.isfinite(plane).all():
        raise ValueError('Expected a finite plane')
    length = np.linalg.norm(plane[:3])
    if length < 1e-12:
        raise ValueError('Zero plane normal')
    return plane / length


def clip_polygon(polygon, plane, epsilon=1e-9):
    """Clip a convex polygon, preserving its winding."""
    result = []
    for a, b in zip(polygon, np.roll(polygon, -1, axis=0)):
        da, db = np.dot(a, plane[:3])+plane[3], np.dot(b, plane[:3])+plane[3]
        if da <= epsilon:
            result.append(a)
        if (da < -epsilon and db > epsilon) or (da > epsilon and db < -epsilon):
            result.append(a + (b-a)*(da/(da-db)))
    return np.asarray(result, dtype=np.float64).reshape(-1, 3)


def _area(triangle):
    return np.linalg.norm(np.cross(triangle[1]-triangle[0], triangle[2]-triangle[0]))*.5


def _cap(loop, normal):
    """Ear-clip a simple cap; refuse holes/self-intersections instead of filling them."""
    axis = np.eye(3)[np.argmin(np.abs(normal))]
    u = np.cross(axis, normal)
    u /= np.linalg.norm(u)
    v = np.cross(normal, u)
    points = np.asarray(loop)
    xy = np.column_stack((points @ u, points @ v))
    cross = lambda a, b: a[0]*b[1]-a[1]*b[0]
    signed = sum(cross(a, b) for a, b in zip(xy, np.roll(xy, -1, axis=0)))
    if signed < 0:
        points, xy = points[::-1], xy[::-1]
    indices, triangles = list(range(len(points))), []
    while len(indices) > 3:
        for k in range(len(indices)):
            ia, ib, ic = indices[k-1], indices[k], indices[(k+1) % len(indices)]
            a, b, c = xy[[ia, ib, ic]]
            if cross(b-a, c-b) <= 1e-10:
                continue
            blocked = False
            for j in indices:
                if j in (ia, ib, ic):
                    continue
                p = xy[j]
                if min(cross(b-a, p-a), cross(c-b, p-b), cross(a-c, p-c)) >= -1e-10:
                    blocked = True
                    break
            if not blocked:
                triangles.append(points[[ia, ib, ic]])
                indices.pop(k)
                break
        else:
            raise ValueError('Cannot triangulate clip cap')
    triangles.append(points[indices])
    return triangles


def intersect_triangles(triangles, plane, weld=0.0002):
    """Cut and cap a closed triangle shell, welding submillimetre export seams."""
    triangles = np.asarray(triangles, dtype=np.float64)
    plane = normalized_plane(plane)
    if triangles.ndim != 3 or triangles.shape[1:] != (3, 3) or not np.isfinite(triangles).all():
        raise ValueError('Invalid clip triangles')
    # Original brush exports have duplicated vertices differing by <0.1 mm.
    # Weld them before intersecting, so adjacent cuts produce the same contour.
    representatives = {}
    def vertex(p):
        cell = tuple(np.floor(p/weld).astype(int))
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                for dz in (-1, 0, 1):
                    for old in representatives.get((cell[0]+dx, cell[1]+dy, cell[2]+dz), ()):
                        if np.linalg.norm(p-old) <= weld:
                            return old
        representatives.setdefault(cell, []).append(p)
        return p
    def finish(faces):
        # A cut can create an intersection within the export seam tolerance
        # of an existing vertex. Weld the kept faces and cap together as well,
        # then discard collapsed slivers before checking the closed surface.
        representatives.clear()
        result = np.array([[vertex(p) for p in tri] for tri in faces])
        result = np.array([tri for tri in result if _area(tri) > 1e-10])
        if not len(result):
            raise ValueError('Plane removes the entire volume')
        edges = Counter((tuple(a), tuple(b)) for tri in result for a, b in zip(tri, np.roll(tri, -1, axis=0)))
        if any(count != 1 or edges[(b, a)] != 1 for (a, b), count in edges.items()):
            raise ValueError('Fitted clip is not a closed consistently wound surface')
        return result
    triangles = np.array([[vertex(p) for p in tri] for tri in triangles])
    kept, segments = [], []
    for tri in triangles:
        poly = clip_polygon(tri, plane)
        for i in range(1, len(poly)-1):
            face = poly[[0, i, i+1]]
            if _area(face) > 1e-10:
                kept.append(face)
        distances = tri @ plane[:3]+plane[3]
        if distances.min() < -1e-9 and distances.max() > 1e-9:
            cut = [p for p in poly if abs(np.dot(p, plane[:3])+plane[3]) < 1e-7]
            if len(cut) != 2:
                raise ValueError('Ambiguous clip-plane intersection')
            segments.append(cut)
    if not segments:
        if not kept:
            raise ValueError('Plane removes the entire volume')
        return finish(kept)
    # A single simple cap is sufficient for a convex roof cut. Refuse multiple
    # contours: nested contours would require explicit polygon-hole handling.
    nodes, edges = [], []
    def key(p):
        for i, q in enumerate(nodes):
            if np.linalg.norm(p-q) <= weld:
                return i
        nodes.append(p)
        return len(nodes)-1
    for a, b in segments:
        ia, ib = key(a), key(b)
        if ia != ib:
            edges.append((ia, ib))
    adjacent = {i: [] for i in range(len(nodes))}
    for a, b in edges:
        adjacent[a].append(b)
        adjacent[b].append(a)
    if any(len(neighbors) != 2 for neighbors in adjacent.values()):
        raise ValueError('Open/nonmanifold clip cut')
    loop, previous, current = [], -1, 0
    while current not in loop:
        loop.append(current)
        following = next(i for i in adjacent[current] if i != previous)
        previous, current = current, following
    if current != 0 or len(loop) != len(nodes):
        raise ValueError('Multiple or self-intersecting clip contours')
    # Collinear cut vertices must remain in the cap to avoid T-junctions.
    kept.extend(_cap([nodes[i] for i in loop], plane[:3]))
    return finish(kept)


def read_clip_mesh(blob):
    chunks = read_chunks(blob)
    lookup = {c.id: c for c in chunks}
    meshes = [c for c in chunks if c.kind == 0x1000]
    if len(meshes) != 1 or meshes[0].version != 0x801 or len(meshes[0].data) != 264:
        raise ValueError('Expected one native clip mesh')
    mesh = meshes[0]
    flags, _, nv, ni, ns, sid = struct.unpack_from('<6I', mesh.data)
    if ns != 1 or flags & 1 or ni % 3:
        raise ValueError('Unsupported clip mesh layout')
    ids = struct.unpack_from('<16I', mesh.data, 28)
    streams = {}
    for kind, identity in enumerate(ids):
        if not identity:
            continue
        c = lookup[identity]
        _, k, count, width = struct.unpack_from('<4I', c.data)
        if c.kind != 0x1016 or c.version != 0x800 or k != kind or len(c.data) != 24+count*width:
            raise ValueError('Invalid clip stream')
        if count != (ni if kind == 5 else nv):
            raise ValueError('Clip stream count mismatch')
        streams[kind] = (c, width)
    if streams[0][1] != 12 or streams[5][1] not in (2, 4):
        raise ValueError('Unsupported clip positions/indices')
    positions = np.frombuffer(streams[0][0].data, '<f4', offset=24).reshape(-1, 3)
    indices = np.frombuffer(streams[5][0].data, '<u2' if streams[5][1] == 2 else '<u4', offset=24)
    if not len(indices) or indices.max() >= nv:
        raise ValueError('Invalid clip index')
    nodes = [c for c in chunks if c.kind == 0x100b]
    if len(nodes) != 1 or nodes[0].version != 0x824:
        raise ValueError('Unsupported clip node')
    tm = np.array(struct.unpack_from('<16f', nodes[0].data, 84)).reshape(4, 4)
    if not np.allclose(tm[:3, :3], np.eye(3)) or np.any(tm[:3, 3]) or np.any(tm[3, :3]):
        raise ValueError('Clip requires a verified local node transform')
    return positions[indices.reshape(-1, 3)].astype(float), chunks, mesh, lookup[sid], streams


def intersect_clip(blob, plane):
    """Update render mesh, bounds, and BSP atomically for one clipping plane."""
    plane = normalized_plane(plane)
    triangles, chunks, mesh, subset, streams = read_clip_mesh(blob)
    _, bsp = clip_geometry(blob)
    result = intersect_triangles(triangles, plane)
    positions = result.reshape(-1, 3)
    nv = len(positions)
    if nv >= 65536 or not len(result):
        raise ValueError('Clip mesh exceeds bounded 16-bit output')
    normals = np.cross(result[:, 1]-result[:, 0], result[:, 2]-result[:, 0])
    normals /= np.linalg.norm(normals, axis=1)[:, None]
    payloads = {0: positions.astype('<f4').tobytes(),
                1: np.repeat(normals, 3, axis=0).astype('<f4').tobytes(),
                2: bytes(nv*8), 5: np.arange(nv, dtype='<u2').tobytes(), 6: bytes(nv*16)}
    widths = {0: 12, 1: 12, 2: 8, 5: 2, 6: 16}
    replacements = {}
    for kind, (chunk, width) in streams.items():
        if kind not in payloads:
            raise ValueError('Unexpected clip stream requiring conversion')
        header = bytearray(chunk.data[:24])
        struct.pack_into('<2I', header, 8, nv, widths[kind])
        replacements[chunk.id] = bytes(header)+payloads[kind]
    lo, hi = positions.min(axis=0), positions.max(axis=0)
    md = bytearray(mesh.data)
    struct.pack_into('<2I', md, 8, nv, nv)
    struct.pack_into('<6f', md, 108, *lo, *hi)
    replacements[mesh.id] = bytes(md)
    if subset.version != 0x800 or len(subset.data) != 52:
        raise ValueError('Unsupported clip subset')
    sd = bytearray(subset.data)
    struct.pack_into('<4I', sd, 16, 0, nv, 0, nv)
    center = (lo+hi)/2
    struct.pack_into('<4f', sd, 36, float(np.linalg.norm(positions-center, axis=1).max()), *center)
    replacements[subset.id] = bytes(sd)
    bc = next(c for c in chunks if c.kind == 0x3009)
    # New root: positive side terminates outside; negative side enters the
    # unchanged source BSP. Existing child references shift by one node.
    data = bytearray(struct.pack('<I4fii', len(bsp)+1, *plane, -1, 1))
    for node in bsp:
        data.extend(struct.pack('<4fii', *node[:4], *(i+1 if i >= 0 else -1 for i in node[4:])))
    replacements[bc.id] = bytes(data)
    return write_chunks(chunks, replacements)
