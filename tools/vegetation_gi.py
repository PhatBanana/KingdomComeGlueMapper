"""Upgrade vegetation GI eligibility to the observed native KCD2 group policy.

Native trosecko (597 groups) and kutnohorsko (599 groups) set SIGC_GI_MODE
on every group, including grass and undergrowth. This is eligibility, not a
promise that every render-node type participates in static voxelization.
"""
import struct

POLICY = 'kcd2-vegetation-gi-v1'
GI_ENABLED = 1 << 8


def eligible_instance(render_flags):
    # Render-node bits are a different field from vegetation-group flags.
    return not bool(render_flags & ((1 << 8) | (1 << 22) | (1 << 27)))


def upgrade_group(record):
    if len(record) != 360:
        raise ValueError('Expected 360-byte vegetation group')
    result = bytearray(record)
    flags = struct.unpack_from('<I', result, 332)[0]
    struct.pack_into('<I', result, 332, flags | GI_ENABLED)
    return bytes(result)


def upgrade_terrain(blob):
    from compiled_terrain import parse
    terrain = parse(blob)
    if terrain.version != 29:
        raise ValueError('Expected converted KCD2 terrain')
    table = terrain.tables['vegetation']
    result = bytearray(blob)
    changed = 0
    for i in range(len(table['paths'])):
        offset = table['offset'] + i * 360
        old = blob[offset:offset + 360]
        new = upgrade_group(old)
        changed += new != old
        result[offset:offset + 360] = new
    return bytes(result), {'policy': POLICY, 'groups': len(table['paths']), 'upgraded': changed}
