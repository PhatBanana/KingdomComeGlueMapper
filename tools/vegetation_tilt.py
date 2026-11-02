"""Bake KCD1 runtime terrain alignment into KCD2 per-instance tilt bytes.

KCD1 kept only the group coefficient (+280) and aligned instances at runtime;
most of its aligned instances carry X=Y=0 and some rock groups random X/Y.
Native KCD2 (trosecko) stores the coefficient-blended terrain tilt in the
instance X/Y bytes instead: Rz*Ry*Rx up-vectors match the terrain normal within
one byte step, and unbaked aligned instances occur only on flat ground. The yaw
byte is kept; unaligned groups are untouched. Baking is idempotent.

The conversion stages (vegetation.py, complete_instances.py) bake fresh builds,
so the finalize stage finds every scoped instance already at its target there
and reports them as already_baked; it changes bytes only on saved builds from
before recipe 59. Both finalize sequences run it after the last HLOD writer
(static gates, stocks), so its hlods_sha256 describes the shipped hlods.dat.
"""
import hashlib
import json
import math
from pathlib import Path
import struct
import zipfile

import numpy as np

from upgrade_map import read

VERSION = 1
POLICY = 'kcd2-baked-terrain-tilt-v1'
MARKER = 'terrain/gluemapper_vegetation_tilt.json'
TURN = 255  # one byte unit is 1/255 of a full turn; 255 equals 0
ALIGNMENT = 280  # float in the 360-byte vegetation group record


class HeightField:
    def __init__(self,terrain):
        self.heights=np.full((4097,4097),np.nan,dtype=np.float64)
        for node in terrain.nodes:
            if node['depth']!=6 or node['size']<2:continue
            size=node['size'];v=node['values'];x,y=round(v[2]),round(v[3])
            packed=np.frombuffer(terrain.data,'<u4',size*size,node['samples']).reshape(size,size)
            z=v[8]+(packed>>20)*v[9]
            q=np.linspace(0,size-1,65);lo=np.minimum(q.astype(int),size-2);f=q-lo
            expanded=(z[lo,:]*(1-f[:,None])+z[lo+1,:]*f[:,None])
            expanded=expanded[:,lo]*(1-f[None,:])+expanded[:,lo+1]*f[None,:]
            self.heights[x:x+65,y:y+65]=expanded
        if not np.isfinite(self.heights).all():raise ValueError('Terrain height coverage incomplete')

    def height(self,x,y):
        x=np.clip(x,0,4096);y=np.clip(y,0,4096)
        ix=np.minimum(x.astype(int),4095);iy=np.minimum(y.astype(int),4095)
        fx=x-ix;fy=y-iy;h=self.heights
        return (h[ix,iy]*(1-fx)+h[ix+1,iy]*fx)*(1-fy)+(h[ix,iy+1]*(1-fx)+h[ix+1,iy+1]*fx)*fy

    def normal(self,positions):
        x,y=positions[:,0],positions[:,1];r=.55
        h1=self.height(x-r,y-r);h2=self.height(x-r,y+r)
        h3=self.height(x+r,y-r);h4=self.height(x+r,y+r)
        a=np.stack((np.full(len(x),2*r),np.full(len(x),-2*r),h3-h2),axis=1)
        b=np.stack((np.full(len(x),2*r),np.full(len(x),2*r),h4-h1),axis=1)
        normal=np.cross(a,b);return normal/np.linalg.norm(normal,axis=1)[:,None]


def group_alignment(record):
    if len(record) != 360:
        raise ValueError('Expected 360-byte vegetation group')
    value = struct.unpack_from('<f', record, ALIGNMENT)[0]
    if not math.isfinite(value) or not 0 <= value <= 1:
        raise ValueError('Invalid vegetation terrain alignment')
    return value


def alignments(terrain):
    table = terrain.tables['vegetation']
    return np.array([group_alignment(terrain.data[table['offset']+i*360:table['offset']+(i+1)*360])
                     for i in range(len(table['paths']))], dtype=np.float64)


def up_vectors(yaw, x, y):
    """Third column of Rz(yaw)*Ry(y)*Rx(x); arguments are stored bytes."""
    z, x, y = (np.asarray(v, dtype=np.float64) * (2*np.pi/TURN) for v in (yaw, x, y))
    return np.stack((np.cos(x)*np.sin(y)*np.cos(z)+np.sin(x)*np.sin(z),
                     np.cos(x)*np.sin(y)*np.sin(z)-np.sin(x)*np.cos(z),
                     np.cos(x)*np.cos(y)), axis=-1)


def target_up(normals, alignment):
    normals = np.asarray(normals, dtype=np.float64).reshape(-1, 3)
    alignment = np.broadcast_to(np.asarray(alignment, dtype=np.float64), (len(normals),))[:, None]
    if not np.isfinite(normals).all() or np.any(normals[:, 2] <= 0) or np.any((alignment < 0) | (alignment > 1)):
        raise ValueError('Invalid terrain normal or alignment')
    up = normals/np.linalg.norm(normals, axis=1)[:, None]*alignment + np.array([0, 0, 1.])*(1-alignment)
    return up/np.linalg.norm(up, axis=1)[:, None]


def tilt_bytes(normals, alignment, yaw):
    """X/Y bytes whose Rz*Ry*Rx up-vector is the blended normal at this yaw."""
    up = target_up(normals, alignment)
    z = np.asarray(yaw, dtype=np.float64).reshape(-1) * (2*np.pi/TURN)
    local_x = np.cos(z)*up[:, 0] + np.sin(z)*up[:, 1]
    local_y = -np.sin(z)*up[:, 0] + np.cos(z)*up[:, 1]
    x = np.arcsin(np.clip(-local_y, -1, 1))
    y = np.arctan2(local_x, up[:, 2])
    encode = lambda angle: (np.rint(angle*TURN/(2*np.pi)).astype(np.int64) % TURN).astype(np.uint8)
    return encode(x), encode(y)


def source_tilts(source, records, heights):
    """{source record offset: (x, y)} for aligned KCD1 groups; others are absent."""
    coefficient = alignments(source)
    chosen = [r for r in records if coefficient[r['group']] > 0]
    if not chosen:
        return {}
    positions = np.array([r['pos'] for r in chosen], dtype=np.float64)
    yaw = np.array([source.data[r['offset']+57] for r in chosen])
    x, y = tilt_bytes(heights.normal(positions), coefficient[[r['group'] for r in chosen]], yaw)
    return {r['offset']: (int(a), int(b)) for r, a, b in zip(chosen, x, y)}


def bake(terrain_blob, hlod_blob, scope=lambda path: True, heights=None):
    """Rewrite X/Y bytes of HLOD vegetation records in aligned, scoped groups."""
    from compiled_terrain import parse
    from lod_ratio_metadata import record_offsets
    terrain = parse(terrain_blob)
    if terrain.version != 29:
        raise ValueError('Expected converted KCD2 terrain')
    paths = terrain.tables['vegetation']['paths']
    coefficient = alignments(terrain)
    eligible = np.array([coefficient[i] > 0 and scope(p) for i, p in enumerate(paths)], dtype=bool)
    offsets = []
    for offset, kind in record_offsets(hlod_blob):
        if kind != 2:
            continue
        group = struct.unpack_from('<H', hlod_blob, offset+40)[0]
        if group >= len(paths):
            raise ValueError('Invalid HLOD vegetation group')
        if eligible[group]:
            offsets.append(offset)
    report = dict(version=VERSION, policy=POLICY, aligned_groups=int(eligible.sum()), scoped=len(offsets),
                  changed=0, already_baked=0, replaced_off_normal=0, runtime_verified=False)
    if not offsets:
        return bytes(hlod_blob), report
    if heights is None:
        heights = HeightField(terrain)
    result = bytearray(hlod_blob)
    rows = np.frombuffer(hlod_blob, np.uint8)[np.array(offsets, np.int64)[:, None]+np.arange(64)]
    groups = rows[:, 40:42].copy().view('<u2')[:, 0]
    positions = rows[:, 44:56].copy().view('<f4').astype(np.float64)
    if not np.isfinite(positions).all():
        raise ValueError('Invalid HLOD vegetation position')
    normals = heights.normal(positions)
    x, y = tilt_bytes(normals, coefficient[groups], rows[:, 61])
    target = target_up(normals, coefficient[groups])
    previous = up_vectors(rows[:, 61], rows[:, 62], rows[:, 63])
    changed = (rows[:, 62] != x) | (rows[:, 63] != y)
    off = np.degrees(np.arccos(np.clip((previous*target).sum(1), -1, 1))) > 30
    view = np.frombuffer(result, np.uint8)
    for column, values in ((62, x), (63, y)):
        view[np.array(offsets, np.int64)+column] = values
    report.update(changed=int(changed.sum()), already_baked=int((~changed).sum()),
                  replaced_off_normal=int((changed & off).sum()))
    return bytes(result), report


def upgrade_package(package, level='kcd1_travel'):
    """Shared fresh-build and saved-build stage; refreshes a valid LOD receipt."""
    from lod_ratio_metadata import MARKER as LOD_MARKER, imported, marker_for, validate_marker
    from setup_campaign import digest
    from setup_package_upgrade import rewrite
    package = Path(package)
    relative = f'Data/Levels/{level}'
    with zipfile.ZipFile(package/relative/'level.pak') as archive:
        names = archive.namelist()
        if 'terrain/hlods.dat' not in names:
            return {}, dict(version=VERSION, policy=POLICY, applicable=False, runtime_verified=False)
        hlod = read(archive, 'terrain/hlods.dat')
        marker = json.loads(read(archive, MARKER)) if MARKER in names else None
        lod_marker = json.loads(read(archive, LOD_MARKER)) if LOD_MARKER in names else None
    if (marker and marker.get('version') == VERSION and marker.get('policy') == POLICY
            and marker.get('hlods_sha256') == hashlib.sha256(hlod).hexdigest()):
        return {}, dict(marker, already_current=True)
    with zipfile.ZipFile(package/relative/'terrain.pak') as archive:
        terrain = read(archive, 'terrain/terrain.dat')
    baked, report = bake(terrain, hlod, imported)
    if not report['scoped']:
        return {}, report
    report = dict(report, hlods_sha256=hashlib.sha256(baked).hexdigest())
    replacements = {MARKER: json.dumps(report, indent=2).encode()}
    if baked != hlod:
        replacements['terrain/hlods.dat'] = baked
        if lod_marker is not None:
            validate_marker(terrain, hlod, lod_marker)
            refreshed = marker_for(terrain, baked, lod_marker)
            validate_marker(terrain, baked, refreshed)
            replacements[LOD_MARKER] = json.dumps(refreshed, indent=2).encode()
    name = relative+'/level.pak'
    rewrite(package, name, replacements)
    return {name: digest(package/name)}, report
