"""Versioned surface-tree migration for fresh, resumed and multiplayer builds."""
from collections import Counter
import hashlib
import json
from pathlib import Path
import struct
import zipfile

from compiled_terrain import parse
from terrain_object_tree import DEFAULT_POLICY, VERSION, place, read_tree
from upgrade_map import read

MARKER = 'terrain/gluemapper_surface_placement.json'
ENTRY = 'terrain/terrain.dat'


def inventory(terrain):
    root, nodes = read_tree(terrain)
    records = Counter((kind, hashlib.sha256(blob).digest()) for n in nodes for kind, blob in n.records)
    summary = dict(nodes=len(nodes), root_records=len(root.records),
                   maximum_records=max(len(n.records) for n in nodes),
                   kinds=dict(Counter(str(k) for n in nodes for k, _ in n.records)))
    return records, summary


def convert(data):
    terrain = parse(data)
    before_records, before = inventory(terrain)
    tree = place(terrain, relocate=True)
    result = bytearray(data[:terrain.tree_offset] + tree)
    struct.pack_into('<I', result, 4, len(result))
    result = bytes(result)
    after_records, after = inventory(parse(result))
    if before_records != after_records:
        raise ValueError('Surface placement changed or lost render records')
    return result, dict(version=VERSION, policy=vars(DEFAULT_POLICY), before=before, after=after,
                        tree_sha256=hashlib.sha256(tree).hexdigest(), runtime_verified=False)


def upgrade_package(package, level='kcd1_travel'):
    """Rewrite a private package atomically. Source/cache and installed files stay separate."""
    from setup_package_upgrade import rewrite
    from setup_campaign import digest
    package = Path(package)
    name = f'Data/Levels/{level}/terrain.pak'
    with zipfile.ZipFile(package/name) as archive:
        data = read(archive, ENTRY)
        marker = json.loads(read(archive, MARKER)) if MARKER in archive.namelist() else None
    if marker and marker.get('version') == VERSION:
        terrain = parse(data)
        if (marker.get('policy') != vars(DEFAULT_POLICY) or
                marker.get('tree_sha256') != hashlib.sha256(data[terrain.tree_offset:]).hexdigest()):
            raise ValueError('Surface placement marker does not match the terrain; rebuild the changed world stage')
        return {}, dict(marker, already_current=True)
    result, report = convert(data)
    rewrite(package, name, {ENTRY: result, MARKER: json.dumps(report, indent=2).encode()})
    return {name: digest(package/name)}, report
