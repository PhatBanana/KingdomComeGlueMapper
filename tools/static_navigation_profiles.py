"""Materialize authored navigation variants for an already flattened static world.

This is not a navmesh generator. Recast v14 cells contain complete replacement
tile stacks, including door off-mesh connections. Copying profile archives
without activating their profiles leaves the base world's routes in use.
Only explicitly selected, ungrouped, always-resident profiles are supported.
Dynamic campaign profiles must continue to use their native profile lifecycle.
"""
import hashlib
import math
from pathlib import Path
import struct
import xml.etree.ElementTree as ET
import zipfile

from campaign_entity_links import guid_value, native_guid
from region_travel_navigation import validate_mesh
from upgrade_map import read

BASE = 'recast/rdnavmesh_1'
VERSION = 1


def digest(data):
    return hashlib.sha256(data).hexdigest()


def connections(tile):
    """Read the shipped v14 compact tile, not upstream Detour's struct layout.

    Both supplied games store 4-byte compact surface vertices, 12-byte link
    vertices, 28-byte polygons, and 52-byte off-mesh connections. The connection
    entity is a uint64 at +32; its category is at +40 (8 for doors).
    """
    if len(tile) < 112:
        raise ValueError('Truncated compact navigation tile')
    fields = struct.unpack_from('<17I11f', tile)
    if fields[:2] != (0x444e4156, 14):
        raise ValueError('Unsupported compact navigation tile format')
    polygons, vertices, links, first_link = fields[6], fields[7], fields[15], fields[16]
    if vertices < links * 2 or first_link + links != polygons:
        raise ValueError('Invalid navigation connection counts')
    if len(tile) != 112 + vertices * 4 + polygons * 28 + links * 68:
        raise ValueError('Navigation tile payload layout differs from native v14')
    bounds = fields[21:27]
    if not all(map(math.isfinite, fields[17:])) or any(bounds[i] > bounds[i+3] for i in range(3)):
        raise ValueError('Invalid navigation tile bounds')
    result = []
    for index in range(links):
        offset = len(tile) - links * 52 + index * 52
        points = struct.unpack_from('<7f', tile, offset)
        poly = struct.unpack_from('<H', tile, offset + 28)[0]
        if poly != first_link + index or not all(map(math.isfinite, points)) or points[6] <= 0:
            raise ValueError('Invalid navigation connection geometry or polygon')
        entity, category = struct.unpack_from('<QI', tile, offset + 32)
        result.append(dict(entity=entity, category=category, start=points[:3], end=points[3:6]))
    return result


def decode(header, mesh, settings, version):
    validate_mesh(header, mesh, settings, version)
    cells = {}
    pos = 0
    while pos < len(header):
        x, y, offset, count = struct.unpack_from('<4I', header, pos)
        sizes = struct.unpack_from('<' + 'I' * count, header, pos + 16)
        pos += 16 + count * 4
        if (x, y) in cells:
            raise ValueError('Duplicate navigation cell')
        tiles, layers = [], set()
        for size in sizes:
            tile = mesh[offset:offset+size]
            connections(tile)
            layer = struct.unpack_from('<I', tile, 16)[0]
            if layer in layers:
                raise ValueError('Duplicate navigation height layer')
            layers.add(layer)
            tiles.append(tile)
            offset += size
        cells[x, y] = tuple(tiles)
    return cells


def encode(cells, settings):
    header = bytearray()
    mesh = bytearray(settings + struct.pack('<I', sum(map(len, cells.values()))))
    for (x, y), tiles in cells.items():
        header.extend(struct.pack('<4I', x, y, len(mesh), len(tiles)))
        header.extend(struct.pack('<' + 'I' * len(tiles), *(len(t) for t in tiles)))
        for tile in tiles:
            mesh.extend(tile)
    return bytes(header), bytes(mesh)


def door_links(cells):
    return {c['entity'] for tiles in cells.values() for tile in tiles
            for c in connections(tile) if c['category'] == 8}


def compose(entries, profiles, selected, native_mesh, mission):
    """Explicit build selection is policy; this function contains no quest names."""
    if not selected or len({n.lower() for n in selected}) != len(selected):
        raise ValueError('Select unique static navigation profiles explicitly')
    names = {n.lower(): n for n in entries}
    if len(names) != len(entries):
        raise ValueError('Ambiguous navigation archive paths')
    if len(native_mesh) < 172:
        raise ValueError('Missing native compact navigation reference')
    settings, version = native_mesh[:56], struct.unpack_from('<I', native_mesh, 64)[0]
    # Also validate a real native tile through decode at the package boundary.
    def pair(stem):
        try:
            return decode(*(entries[names[stem + ext]] for ext in ('.hdr', '.nav')), settings, version)
        except KeyError as error:
            raise ValueError('Missing navigation pair: ' + stem) from error
    records = {}
    ids = set()
    for profile in profiles.iter('GameProfile'):
        name, number = profile.findtext('Name'), profile.findtext('Id')
        if not name or name.lower() in records or number in ids:
            raise ValueError('Duplicate or missing source profile identity')
        records[name.lower()] = profile
        ids.add(number)
    grouped = {n.text for n in profiles.findall('.//GameProfileGroups/Groups/Group/Profiles/Profile')}
    base = pair(BASE)
    doors = {}
    for entity in mission.iter('Entity'):
        if entity.get('EntityClass') == 'AnimDoor':
            key = guid_value(entity.get('EntityGuid'))
            if key in doors:
                raise ValueError('Duplicate converted door GUID')
            doors[key] = entity
    replacements, owners, evidence = {}, {}, []
    for name in selected:
        profile = records.get(name.lower())
        if profile is None or profile.findtext('HasNavigation') != '1':
            raise ValueError('Selected profile has no authored navigation: ' + name)
        if profile.findtext('Id') in grouped:
            raise ValueError('Navigation group combinations need their complete selection: ' + name)
        cells = pair('recast/rdnavmesh_' + name.lower() + '_1')
        # Every door baked into this layout must already exist in the converted
        # world. A filename alone is not proof that its dependencies were built.
        missing = door_links(cells) - doors.keys()
        if missing:
            raise ValueError('Selected navigation references unconverted doors: ' + ', '.join(native_guid(g) for g in sorted(missing)))
        for key, tiles in cells.items():
            if key in replacements and replacements[key] != tiles:
                raise ValueError('Conflicting static navigation profiles at ' + str(key) + ': ' + owners[key] + ', ' + name)
            replacements[key], owners[key] = tiles, name
        evidence.append(dict(profile=name, source_id=profile.findtext('Id'), cells=len(cells),
            tiles=sum(map(len, cells.values())), door_connections=len(door_links(cells)),
            header_sha256=digest(entries[names['recast/rdnavmesh_'+name.lower()+'_1.hdr']]),
            mesh_sha256=digest(entries[names['recast/rdnavmesh_'+name.lower()+'_1.nav']])))
    result = dict(base)
    result.update(replacements)
    header, mesh = encode(result, settings)
    if decode(header, mesh, settings, version) != result:
        raise ValueError('Navigation composition did not round-trip')
    added = door_links(result) - door_links(base)
    removed = door_links(base) - door_links(result)
    # A resident door cannot silently lose its route when a layout is selected.
    if removed & doors.keys():
        raise ValueError('Static navigation selection removes converted door links: ' + ', '.join(native_guid(g) for g in sorted(removed & doors.keys())))
    changed = sum(base.get(k) != v for k, v in replacements.items())
    return {names[BASE+'.hdr']: header, names[BASE+'.nav']: mesh}, dict(version=VERSION,
        mode='materialized_static_profiles', profiles=evidence, changed_cells=changed,
        base_tiles_before=sum(map(len, base.values())), base_tiles_after=sum(map(len, result.values())),
        added_door_links=[native_guid(g) for g in sorted(added)],
        missing_installed_door_links=[native_guid(g) for g in sorted(doors.keys()-door_links(result))],
        untouched_cells_preserved=all(result[k] == v for k, v in base.items() if k not in replacements),
        runtime_verified=False)


def plan(package, source, target, selected, *, source_level='rataje', level='kcd1_travel'):
    package, source, target = map(Path, (package, source, target))
    relative = 'Data/Levels/' + level + '/recast.pak'
    with zipfile.ZipFile(package/'Data/Levels'/level/'level.pak') as z:
        mission = ET.fromstring(read(z, 'objects_mission0.xml'))
        # Static materialization is inappropriate where a native runtime profile
        # manager owns navigation switching. Do not let both mechanisms compete.
        if 'whdata_1' in z.namelist() and any(p.findtext('HasNavigation') == '1'
                for p in ET.fromstring(read(z, 'whdata_1')).iter('GameProfile')):
            raise ValueError('Runtime navigation profiles already own this world')
    with zipfile.ZipFile(source/'Data/Levels'/source_level/'level.pak') as z:
        profiles = ET.fromstring(read(z, 'whdata_1'))
        from chairs import inventory
        source_entities, source_doors, _ = inventory(z, 'AnimDoor')
    with zipfile.ZipFile(target/'Data/Levels/trosecko/recast.pak') as z:
        native_header, native = (read(z, BASE+ext) for ext in ('.hdr', '.nav'))
    decode(native_header, native, native[:56], struct.unpack_from('<I', native, 64)[0])
    with zipfile.ZipFile(package/relative) as z:
        entries = {n: read(z, n) for n in z.namelist()}
    index = {n.lower(): n for n in entries}
    if len(index) != len(entries):
        raise ValueError('Ambiguous navigation archive paths')
    settings, version = native[:56], struct.unpack_from('<I', native, 64)[0]
    current = decode(entries[index[BASE+'.hdr']], entries[index[BASE+'.nav']], settings, version)
    # Verify that the variants really came from the supplied source installation.
    with zipfile.ZipFile(source/'Data/Levels'/source_level/'recast.pak') as z:
        original = decode(read(z, BASE+'.hdr'), read(z, BASE+'.nav'), settings, version)
        for name in selected:
            for ext in ('.hdr', '.nav'):
                path = 'recast/rdnavmesh_' + name.lower() + '_1' + ext
                matches = [n for n in entries if n.lower() == path]
                if len(matches) != 1 or entries[matches[0]] != read(z, path):
                    raise ValueError('Navigation profile differs from its source: ' + path)
            stem = 'recast/rdnavmesh_' + name.lower() + '_1'
            selected_cells = decode(entries[index[stem+'.hdr']], entries[index[stem+'.nav']], settings, version)
            for cell, tiles in selected_cells.items():
                if current.get(cell) not in (original.get(cell), tiles):
                    raise ValueError('Existing navigation cell has unrecognized edits: ' + str(cell))
    changes, report = compose(entries, profiles, selected, native, mission)
    # Retaining an entity GUID while moving the physical door would still leave
    # the baked traversal at the old position. Check the same resolved world TRS
    # used by world_doors.convert; no coordinate-based assignment or name alias.
    selected_links = set()
    for name in selected:
        stem = 'recast/rdnavmesh_' + name.lower() + '_1'
        selected_links.update(door_links(decode(entries[index[stem+'.hdr']], entries[index[stem+'.nav']], settings, version)))
    validate_door_transforms(selected_links, mission, source_entities, source_doors)
    report['door_transforms_validated'] = len(selected_links)
    again, _ = compose(dict(entries, **changes), profiles, selected, native, mission)
    if again != changes:
        raise ValueError('Static navigation conversion is not idempotent')
    return relative, {n: b for n, b in changes.items() if b != entries[n]}, report


def validate_door_transforms(links, mission, source_entities, source_doors):
    from entity_visuals import world_transform
    originals = {int(e.get('EntityGuid'), 16): e for e in source_doors}
    converted = {guid_value(e.get('EntityGuid')): e for e in mission.iter('Entity')
                 if e.get('EntityClass') == 'AnimDoor'}
    for key in links:
        if key not in originals or key not in converted:
            raise ValueError('Navigation door is not in the selected static source world: ' + native_guid(key))
        original, door = originals[key], converted[key]
        p, q, s = world_transform(original, source_entities)
        actual = [tuple(map(float, door.get(field, default).split(','))) for field, default in
                  [('Pos', '0,0,0'), ('Rotate', '1,0,0,0'), ('Scale', '1,1,1')]]
        if any(len(a) != len(b) or not all(map(math.isfinite, a)) for a,b in zip(actual, (p,q,s))):
            raise ValueError('Invalid converted door transform')
        rotation = min(max(abs(a-b) for a,b in zip(actual[1], q)), max(abs(a+b) for a,b in zip(actual[1], q)))
        if rotation > 1e-4 or any(abs(a-b) > 1e-4 for a,b in zip(actual[0]+actual[2], p+s)):
            raise ValueError('Navigation door transform differs from authored source: ' + native_guid(key))


def upgrade(package, source, target, selected):
    """Used only inside the shared clean-build / transactional-resume staging."""
    from setup_package_upgrade import rewrite
    from upgrade_map import digest as file_digest
    relative, changes, report = plan(package, source, target, selected)
    if changes:
        rewrite(Path(package), relative, changes)
    return {relative: file_digest(Path(package)/relative)}, report
