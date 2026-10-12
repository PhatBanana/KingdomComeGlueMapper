"""Select initial-state water before flattening source layers for KCD2."""
from collections import defaultdict
import os
import re
from pathlib import Path
import struct
import tempfile
import xml.etree.ElementTree as ET
import zipfile

from compiled_terrain import parse
from upgrade_map import read
from water_volumes import read_water


def select_water(terrain, layers):
    kept, excluded = [], []
    for record in read_water(terrain)[0]:
        layer = struct.unpack_from('<H', terrain.data, record['offset'] + 28)[0]
        name = layers.get(layer, '')
        row = dict(record, layer=layer, layer_name=name)
        # Named setup/part/camp layers can contain permanent river physics.
        # Only explicit later states establish exclusion without editor ancestry.
        later_state = re.search(r'(?:^|_)state([0-9]+)(?=_|\{|$)', name.lower())
        inactive = layer != 0 and later_state is not None and int(later_state[1]) > 0
        (excluded if inactive else kept).append(row)
    return kept, excluded


def identity(terrain, record):
    start = record['offset']
    # IDs and geometry survive conversion; material indices and padding do not.
    extra = 4 if terrain.version == 29 else 0
    return (terrain.data[start+44+extra:start+52+extra],
            terrain.data[start+4:start+28],
            terrain.data[record['geometry_offset']:start+record['size']])


def repair_terrain(target, source, layers):
    kept, excluded = select_water(source, layers)
    allowed = {identity(source, r) for r in kept}
    rejected = defaultdict(list)
    for r in excluded:
        rejected[identity(source, r)].append(r)
    removals = {}
    for r in read_water(target)[0]:
        key = identity(target, r)
        if key in rejected and key not in allowed:
            removals[r['offset']] = dict(r, source_layer=rejected[key][0]['layer'],
                                        source_layer_name=rejected[key][0]['layer_name'])
    if not removals:
        return target.data, []
    # Rebuild tree blocks, preserving every retained record byte-for-byte.
    records = {}
    read_water(target, lambda data, off, size, kind: records.update({off: size}))
    cursor = target.tree_offset
    def node():
        nonlocal cursor
        header = bytearray(target.data[cursor:cursor+32])
        end = cursor+32+struct.unpack_from('<I', header, 28)[0]
        cursor += 32
        payload = []
        while cursor < end:
            size = records[cursor]
            if cursor not in removals:
                payload.append(target.data[cursor:cursor+size])
            cursor += size
        body = b''.join(payload)
        struct.pack_into('<I', header, 28, len(body))
        children = b''.join(node() for bit in range(8) if header[2] & (1 << bit))
        return bytes(header)+body+children
    output = bytearray(target.data[:target.tree_offset]+node())
    if cursor != len(target.data):
        raise ValueError('Unconsumed terrain tree')
    struct.pack_into('<I', output, 4, len(output))
    checked = parse(output)
    before = read_water(target)[1]
    after = read_water(checked)[1]
    expected = dict(before)
    expected[9] -= len(removals)
    if not expected[9]: expected.pop(9)
    if after != expected:
        raise ValueError('Unexpected object counts after water selection')
    return bytes(output), list(removals.values())


def repair_package(mod, source_root):
    with zipfile.ZipFile(Path(source_root)/'Data/Levels/rataje/level.pak') as z:
        source = parse(read(z, 'terrain/terrain.dat'))
        layers = {int(e.get('Id')): e.get('Name', '') for e in
                  ET.fromstring(read(z, 'leveldata.xml')).find('Layers')}
    path = Path(mod)/'Data/Levels/kcd1_travel/terrain.pak'
    with zipfile.ZipFile(path) as z:
        blob, removed = repair_terrain(parse(read(z, 'terrain/terrain.dat')), source, layers)
        if removed:
            fd, temp = tempfile.mkstemp(suffix='.pak', dir=path.parent)
            os.close(fd)
            try:
                with zipfile.ZipFile(temp, 'w', zipfile.ZIP_STORED) as out:
                    for entry in z.infolist():
                        out.writestr(entry, blob if entry.filename.lower() == 'terrain/terrain.dat' else z.read(entry))
            except BaseException:
                Path(temp).unlink(missing_ok=True)
                raise
    if removed: os.replace(temp, path)
    return {'removed_water_volumes': len(removed), 'records': removed}
