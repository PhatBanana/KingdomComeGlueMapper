"""Draw imported KCD1 puddle quads in KCD2's deferred-decal stage (issue #18).

KCD1 authored its shallow puddles as flat brush quads with a %DECAL material
(for example decal_puddle_4, CustomSortPriority 40) laid over hand-placed
deferred soil/road decals with lower sort priorities. KCD2 draws mesh decals
in the GBuffer overlay pass and runs CDeferredDecalsStage afterwards
(WHGame.dll: GBuffer stage execute precedes the DEFERRED_DECALS stage), so an
overlapping deferred decal now paints over the whole puddle whatever its
material sort priority is. Native KCD2 places most puddles as deferred decals
(kind 7) instead, including 48 that reuse the two-slot mesh puddle material
objects/natural/terrain_deco/decal_puddle_b.

This module only builds additional kind 7 records that reproduce an existing
puddle quad. The brush stays in place for its mud collision proxy. The decal
loses the mesh path's POM and detail map, as native deferred puddles do.
"""
import math
import struct
import xml.etree.ElementTree as ET

import numpy as np

from puddle_materials import puddle_decal_slots

DECAL_KIND = 7
DECAL_SIZE = 120
NATIVE_VIEW_RATIO = 100  # 3244 of the native trosecko puddle decals
NATIVE_LOD_RATIO = 100


def planar_quad(triangles, uv, tolerance=1e-3):
    """Return (origin, u_axis, v_axis, face_normal) for one flat UV square.

    P(u, v) = origin + u*u_axis + v*v_axis must reproduce every vertex, the
    UVs must span exactly [0, 1]^2 and the triangles must cover that square
    once. Anything else (tiled, sculpted or multi-part puddles) is rejected.
    """
    tri = np.asarray(triangles, dtype=np.float64)
    tex = np.asarray(uv, dtype=np.float64)
    if tri.ndim != 3 or tri.shape[1:] != (3, 3) or tex.shape != tri.shape[:2] + (2,) or not len(tri):
        return None
    if not np.isfinite(tri).all() or not np.isfinite(tex).all():
        return None
    points, coords = tri.reshape(-1, 3), tex.reshape(-1, 2)
    if (abs(coords.min(0)) > tolerance).any() or (abs(coords.max(0) - 1) > tolerance).any():
        return None
    basis = np.column_stack((coords, np.ones(len(coords))))
    solution, _, rank, _ = np.linalg.lstsq(basis, points, rcond=None)
    if rank != 3:
        return None
    u_axis, v_axis, origin = solution
    size = max(np.linalg.norm(u_axis), np.linalg.norm(v_axis))
    if size <= 0 or np.abs(basis @ solution - points).max() > tolerance * max(size, 1):
        return None
    cross = np.cross(u_axis, v_axis)
    area = np.linalg.norm(cross)
    if area <= 1e-9:
        return None
    covered = 0.5 * np.linalg.norm(np.cross(tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0]), axis=1).sum()
    if abs(covered - area) > 0.02 * area:
        return None
    # Wound face normal, so a mirrored UV layout cannot flip the projection.
    faces = np.cross(tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0]).sum(0)
    normal = faces / np.linalg.norm(faces)
    return origin, u_axis, v_axis, normal


def decal_record(matrix, quad, material_index, sort_priority,
                 view_ratio=NATIVE_VIEW_RATIO, lod_ratio=NATIVE_LOD_RATIO):
    """Build a native-layout KCD2 deferred planar decal covering a brush quad.

    Layout (matches native trosecko puddle decals): kind, AABB, zeros, view
    and LOD bytes at 42/43, projection type 0 (planar) and deferred=1 at
    44..46, position, unit normal, row-major 3x3 whose columns are right, up
    and front scaled by the radius, radius, material index, sort priority.
    The AABB extends half the front column, as in native records.
    """
    m = np.asarray(matrix, dtype=np.float64).reshape(3, 4)
    origin, u_axis, v_axis, normal = (np.asarray(x, dtype=np.float64) for x in quad)
    rotation, translation = m[:, :3], m[:, 3]
    centre = rotation @ (origin + 0.5 * u_axis + 0.5 * v_axis) + translation
    right = rotation @ (0.5 * u_axis)
    up = rotation @ (0.5 * v_axis)
    face = rotation @ normal  # only the direction is used
    if np.linalg.det(rotation) < 0:
        face = -face
    radius = max(np.linalg.norm(right), np.linalg.norm(up))
    if not math.isfinite(radius) or radius <= 0:
        raise ValueError('Degenerate puddle quad')
    front = np.cross(right, up)
    front /= np.linalg.norm(front)
    if front @ face < 0:
        # Keep a right-handed right x up = front frame facing the visible side.
        up = -up
        front = -front
    columns = np.column_stack((right, up, front * radius))
    half = np.abs(columns[:, 0]) + np.abs(columns[:, 1]) + 0.5 * np.abs(columns[:, 2])
    if not 0 <= view_ratio <= 255 or not 0 <= lod_ratio <= 255:
        raise ValueError('View/LOD ratio bytes out of range')
    record = bytearray(DECAL_SIZE)
    struct.pack_into('<I6f', record, 0, DECAL_KIND, *(centre - half), *(centre + half))
    record[42], record[43] = view_ratio, lod_ratio
    record[46] = 1  # deferred; projection type (44..45) stays planar
    struct.pack_into('<3f', record, 48, *centre)
    struct.pack_into('<3f', record, 60, *front)
    struct.pack_into('<9f', record, 72, *columns.reshape(-1))
    struct.pack_into('<fii', record, 108, radius, material_index, sort_priority)
    return bytes(record)


def sort_priority(material):
    """KCD1 mesh-decal ordering of the visible puddle slot (engine default 0)."""
    slots = puddle_decal_slots(material)
    if not slots:
        raise ValueError('Not a dedicated puddle decal material')
    values = {int(s.get('CustomSortPriority', '0')) for s in slots}
    if len(values) != 1:
        raise ValueError('Ambiguous puddle sort priority')
    value = values.pop()
    if not 0 <= value <= 255:
        raise ValueError('Puddle sort priority out of range')
    return value


def is_puddle_material(blob):
    return bool(puddle_decal_slots(ET.fromstring(blob)))
