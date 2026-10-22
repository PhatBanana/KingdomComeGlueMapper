"""Recover one finalized LOD section from hash-verified saved build evidence.

Never infer encoding from the numeric range of an existing ratio. A reference
must match the old marker exactly. Registered geometry edits may be replayed on
that reference, but every non-LOD byte must then match the current section.
"""
import hashlib
import struct
import zipfile
from pathlib import Path

from lod_ratio_metadata import VERSION, group_fingerprint, imported, record_offsets
from compiled_terrain import parse
from upgrade_map import read


def mark_geometry_edit(terrain, before, after, metadata, marker, edits):
    """Keep validation current when an owned geometry-only overlay is applied."""
    from lod_ratio_metadata import validate_marker, marker_for
    from world_brush_edits import edit
    validate_marker(terrain, before, marker)
    expected, _ = edit(before, metadata, edits)
    if after != expected:
        raise ValueError('Geometry overlay changed bytes outside its registered edits')
    return marker_for(terrain, after, marker)


def references(roots, level):
    """Bounded search in caller-selected build workspaces, never game folders."""
    if not level or not level.replace('_', '').isalnum():
        raise ValueError('Invalid repair level')
    seen = set()
    suffix = f'Data/Levels/{level}/level.pak'
    for root in roots:
        root = Path(root).resolve()
        for layout in ('', '*/', '*/package/', '*/package/map/'):
            for path in sorted(root.glob(layout + suffix)):
                resolved = path.resolve()
                if resolved in seen or not resolved.is_relative_to(root) or path.is_symlink():
                    continue
                seen.add(resolved)
                yield path


def restore_ratios(terrain, current, expected):
    """Copy proven imported ratios only; reject every other unexpected change."""
    if len(current) != len(expected):
        return None
    result = bytearray(current)
    changed = 0
    for offset, kind in record_offsets(expected):
        paths = terrain.tables['vegetation' if kind == 2 else 'meshes']['paths']
        index = struct.unpack_from('<H', expected, offset + 40)[0]
        if index >= len(paths):
            raise ValueError('Invalid recovery resource index')
        if imported(paths[index]):
            changed += result[offset + 43] != expected[offset + 43]
            result[offset + 43] = expected[offset + 43]
    return (bytes(result), changed) if result == expected else None


def recover(terrain_blob, current, marker, roots, level):
    terrain = parse(terrain_blob)
    if (marker.get('version') != VERSION or
            marker.get('target_encoding') != 'kcd2-piecewise-1-to-20'):
        raise ValueError('LOD recovery requires a supported encoding marker')
    for path in references(roots, level):
        try:
            with zipfile.ZipFile(path) as archive:
                expected = read(archive, 'terrain/hlods.dat')
                if hashlib.sha256(expected).hexdigest() != marker.get('hlods_sha256'):
                    continue
                # Numeric indices are only meaningful with the same resource tables.
                with zipfile.ZipFile(path.with_name('terrain.pak')) as source:
                    baseline = parse(read(source, 'terrain/terrain.dat'))
                if any(baseline.tables[key]['paths'] != terrain.tables[key]['paths']
                       for key in ('meshes', 'vegetation')):
                    continue
                if group_fingerprint(baseline) != marker['groups_sha256']:
                    continue
                repaired_terrain = bytearray(terrain_blob)
                groups = 0
                for i, name in enumerate(terrain.tables['vegetation']['paths']):
                    if not imported(name):
                        continue
                    offset = terrain.tables['vegetation']['offset'] + i * 360 + 324
                    original_offset = baseline.tables['vegetation']['offset'] + i * 360 + 324
                    value = baseline.data[original_offset:original_offset + 4]
                    groups += repaired_terrain[offset:offset + 4] != value
                    repaired_terrain[offset:offset + 4] = value
                result = restore_ratios(terrain, current, expected)
                replay = []
                if result is None:
                    # This registered overlay predates LOD marker maintenance.
                    # Replay its actual implementation, not approximate coordinates.
                    from forge_loft import BRUSH_EDITS
                    from world_brush_edits import edit
                    expected, _ = edit(expected, read(archive, 'terrain/hlods.xml'), BRUSH_EDITS)
                    result = restore_ratios(terrain, current, expected)
                    replay = ['forge_loft.brush_edits']
                if result is not None:
                    payload, changed = result
                    return bytes(repaired_terrain), payload, dict(section='lod_ratios', reference=str(path),
                        reference_hlods_sha256=marker['hlods_sha256'],
                        previous_hlods_sha256=hashlib.sha256(current).hexdigest(),
                        replayed_overlays=replay, repaired_ratio_bytes=changed,
                        repaired_group_ratios=groups,
                        geometry_preserved=True, runtime_verified=False)
        except (OSError, KeyError, ValueError, zipfile.BadZipFile):
            # A stale/incomplete saved build is not recovery evidence.
            continue
    raise ValueError('LOD encoding marker does not match world data; no verified saved '
                     'LOD section matches this geometry. Keep the source build/cache to repair this section.')
