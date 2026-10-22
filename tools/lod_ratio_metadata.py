"""Preserve KCD1's per-object LOD meaning in KCD2's nonlinear byte encoding.

The intermediate map builders copy KCD1 render records, including their linear
0..255 percentage bytes. Finalize those records once, after all world overlays.
KCD2 decodes 0..100 as 0..1, but 100..255 as 1..20. This is a format conversion,
not a distance preset. Native resources and all other record bytes stay intact.
"""
import hashlib
import json
import math
from pathlib import Path
import struct
import zipfile

from compiled_terrain import parse
from mesh_lod_metadata import PREFIXES
from upgrade_map import read

VERSION = 1
MARKER = 'terrain/gluemapper_lod_ratios.json'


def encode_source_ratio(value):
    if not isinstance(value, int) or not 0 <= value <= 255:
        raise ValueError('Expected a KCD1 LOD ratio byte')
    # Nearest representable KCD2 ratio, with ties rounded upwards. Integer
    # arithmetic avoids platform-dependent rounding at the encoding boundary.
    return value if value <= 100 else 100 + ((value - 100) * 155 + 950) // 1900


def decode_target_ratio(value):
    if not isinstance(value, int) or not 0 <= value <= 255:
        raise ValueError('Expected a KCD2 LOD ratio byte')
    return value / 100 if value <= 100 else 1 + (value - 100) * 19 / 155


def f32(value):
    return struct.unpack('<f', struct.pack('<f', value))[0]


def group_byte(value):
    if not math.isfinite(value) or value < 0:
        raise ValueError('Invalid vegetation group LOD ratio')
    return 255 if value >= 2.55 else int(f32(f32(value) * 100))


def group_ratio(value):
    result = f32(value / 100)
    # The native reader multiplies in float32 then truncates. Pick a float that
    # round-trips even at values such as 105 (1.05f * 100f is below 105).
    if group_byte(result) != value:
        bits = struct.unpack('<I', struct.pack('<f', result))[0]
        result = struct.unpack('<f', struct.pack('<I', bits + 1))[0]
    if group_byte(result) != value:
        raise ValueError('Vegetation LOD ratio cannot round-trip')
    return result


def imported(path):
    return path.replace('\\', '/').lower().startswith(PREFIXES)


def record_offsets(data):
    if len(data) < 4 or struct.unpack_from('<I', data)[0] != 2:
        raise ValueError('Unsupported HLOD container for LOD conversion')
    cursor = 4
    while cursor < len(data):
        if cursor + 4 > len(data):
            raise ValueError('Truncated HLOD block header')
        size = struct.unpack_from('<I', data, cursor)[0]
        cursor += 4
        end = cursor + size
        if end > len(data):
            raise ValueError('HLOD block exceeds data')
        while cursor < end:
            if cursor + 4 > end:
                raise ValueError('Truncated HLOD record')
            kind = struct.unpack_from('<I', data, cursor)[0]
            stride = {1: 104, 2: 64}.get(kind)
            if stride is None or cursor + stride > end:
                raise ValueError('Invalid HLOD render record')
            yield cursor, kind
            cursor += stride


def group_fingerprint(terrain):
    table = terrain.tables['vegetation']
    digest = hashlib.sha256()
    for i, path in enumerate(table['paths']):
        if imported(path):
            digest.update(path.encode() + b'\0')
            start = table['offset'] + i * 360 + 324
            digest.update(terrain.data[start:start + 4])
    return digest.hexdigest()


def convert(terrain_blob, hlod_blob):
    """Convert unfinalized imported records; callers must enforce the marker."""
    terrain = parse(terrain_blob)
    if terrain.version != 29:
        raise ValueError('Expected intermediate KCD2 terrain')
    changed_terrain, changed_hlod = bytearray(terrain_blob), bytearray(hlod_blob)
    counts = dict(vegetation=0, brushes=0, groups=0)
    scoped = dict(vegetation=0, brushes=0, groups=0)
    transitions = {}
    table = terrain.tables['vegetation']
    for i, path in enumerate(table['paths']):
        if not imported(path):
            continue
        scoped['groups'] += 1
        offset = table['offset'] + i * 360 + 324
        old = struct.unpack_from('<f', terrain_blob, offset)[0]
        new = group_ratio(encode_source_ratio(group_byte(old)))
        if new != old:
            struct.pack_into('<f', changed_terrain, offset, new)
            counts['groups'] += 1
    for offset, kind in record_offsets(hlod_blob):
        key = 'vegetation' if kind == 2 else 'brushes'
        paths = terrain.tables['vegetation' if kind == 2 else 'meshes']['paths']
        index = struct.unpack_from('<H', hlod_blob, offset + 40)[0]
        if index >= len(paths):
            raise ValueError('Invalid HLOD resource index during LOD conversion')
        if not imported(paths[index]):
            continue
        scoped[key] += 1
        old = hlod_blob[offset + 43]
        new = encode_source_ratio(old)
        if new != old:
            changed_hlod[offset + 43] = new
            counts[key] += 1
            pair = f'{old}->{new}'
            transitions[pair] = transitions.get(pair, 0) + 1
    return bytes(changed_terrain), bytes(changed_hlod), dict(
        version=VERSION, scoped=scoped, changed=counts, transitions=transitions,
        source_encoding='kcd1-linear-percent', target_encoding='kcd2-piecewise-1-to-20',
        runtime_verified=False)


def marker_for(terrain_blob, hlod_blob, report):
    return dict(report, hlods_sha256=hashlib.sha256(hlod_blob).hexdigest(),
                groups_sha256=group_fingerprint(parse(terrain_blob)))


def validate_marker(terrain_blob, hlod_blob, marker):
    if (marker.get('version') != VERSION or
            marker.get('target_encoding') != 'kcd2-piecewise-1-to-20' or
            marker.get('hlods_sha256') != hashlib.sha256(hlod_blob).hexdigest() or
            marker.get('groups_sha256') != group_fingerprint(parse(terrain_blob))):
        raise ValueError('LOD encoding marker does not match world data; rebuild the changed source stage')


def upgrade_package(package, level='kcd1_travel', *, validate_only=False, repair_roots=()):
    """Shared fresh-build and transactional migration stage; never double-encode.

    The marker is inside level.pak, so resume cannot confuse a completed
    conversion with an older copied record. Its hashes reject stale mixed data.
    Only the final imported namespace is eligible; native references are kept.
    """
    from setup_campaign import digest
    from setup_package_upgrade import rewrite

    package = Path(package)
    relative = f'Data/Levels/{level}'
    with zipfile.ZipFile(package / relative / 'level.pak') as archive:
        if 'terrain/hlods.dat' not in archive.namelist():
            return {}, dict(version=VERSION, applicable=False, runtime_verified=False)
        old_hlod = read(archive, 'terrain/hlods.dat')
        marker = json.loads(read(archive, MARKER)) if MARKER in archive.namelist() else None
    with zipfile.ZipFile(package / relative / 'terrain.pak') as archive:
        old_terrain = read(archive, 'terrain/terrain.dat')
    if marker:
        try:
            validate_marker(old_terrain, old_hlod, marker)
        except ValueError:
            if validate_only or not repair_roots:
                raise
            from lod_ratio_repair import recover
            terrain, hlod, recovery = recover(old_terrain, old_hlod, marker, repair_roots, level)
            report = dict(marker, recovery=recovery)
            report.pop('already_current', None)
        else:
            return {}, dict(marker, already_current=True)
    else:
        terrain, hlod, report = convert(old_terrain, old_hlod)
    if not any(report['scoped'].values()):
        return {}, report
    if validate_only:
        raise ValueError('Imported world is missing its KCD2 LOD encoding stage')
    marker = marker_for(terrain, hlod, report)
    validate_marker(terrain, hlod, marker)
    files = {}
    if terrain != old_terrain:
        name = relative + '/terrain.pak'
        rewrite(package, name, {'terrain/terrain.dat': terrain})
        files[name] = digest(package / name)
    name = relative + '/level.pak'
    replacements = {MARKER: json.dumps(marker, indent=2).encode()}
    if hlod != old_hlod:
        replacements['terrain/hlods.dat'] = hlod
    rewrite(package, name, replacements)
    files[name] = digest(package / name)
    return files, marker
