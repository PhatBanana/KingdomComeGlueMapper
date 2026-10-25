"""Keep imported KCD1 roads visible as far as KCD1 drew them.

KCD1 and KCD2 read the same road view-distance byte (offset 42 of a KCD2 road
record, 38 in KCD1) with different formulas. Both were read from the shipped
WHGame.dll binaries (CRoadRenderNode vtable, GetMaxViewDist):

- KCD1: max(e_ViewDistMin, 0.5 * |bounds diagonal| * e_ViewDistRatio * byte / 100)
- KCD2: max(e_ViewDistMin, wh_e_ViewDistRatioRoad * byte / 100)

KCD2 dropped the road's size from the product, so copying the KCD1 byte
shrinks a typical imported road's distance from about 160 m to about 20 m at
the default spec. Native KCD2 roads use byte 100 almost everywhere. Rewrite each
imported road byte so KCD2 reproduces the KCD1 distance at the default spec,
capped at the native byte and never below the source byte. Byte 255 is the
engine's special 100x multiplier in both games and is left alone.
"""
import math
import struct

from terrain_object_tree import bounds

VERSION = 1
VIEW_BYTE = 42
KCD1_VIEW_RATIO = 100.0       # KCD1 e_ViewDistRatio, sys_spec_ObjectDetail [default]
KCD2_ROAD_VIEW_RATIO = 110.0  # KCD2 wh_e_ViewDistRatioRoad, sys_spec_ObjectDetail [default]
NATIVE_ROAD_BYTE = 100        # byte used by about 90% of trosecko roads
IMPORTED_PREFIX = 'gluelandscape/'


def kcd1_distance(record):
    """KCD1 road view distance at the default spec, before the e_ViewDistMin floor."""
    if len(record) < 112 or struct.unpack_from('<I', record)[0] != 11:
        raise ValueError('Expected a KCD2 road record')
    box = bounds(record)
    radius = 0.5 * math.sqrt(sum((box[a+3] - box[a]) ** 2 for a in range(3)))
    byte = record[VIEW_BYTE]
    ratio = 100.0 if byte == 255 else byte / 100.0
    return radius * KCD1_VIEW_RATIO * ratio


def target_byte(record):
    byte = record[VIEW_BYTE]
    if byte == 255 or byte >= NATIVE_ROAD_BYTE:
        return byte
    wanted = math.ceil(kcd1_distance(record) * 100.0 / KCD2_ROAD_VIEW_RATIO - 1e-6)
    return max(byte, min(NATIVE_ROAD_BYTE, wanted))


def imported(material, paths):
    if material == -1:
        return True  # KCD1 roads without a material; native roads always have one
    if not 0 <= material < len(paths):
        raise ValueError('Road material outside table')
    return paths[material].replace('\\', '/').lower().startswith(IMPORTED_PREFIX)


def convert(terrain):
    """Return terrain bytes with imported road view bytes rewritten, and a report."""
    from water_volumes import read_water
    if terrain.version != 29:
        raise ValueError('Expected KCD2 terrain')
    output = bytearray(terrain.data)
    paths = terrain.tables['materials']['paths']
    counts = dict(roads=0, imported=0, changed=0)
    before, after = [], []

    def visit(data, offset, size, kind):
        if kind != 11:
            return
        counts['roads'] += 1
        record = data[offset:offset+size]
        if not imported(struct.unpack_from('<i', record, 108)[0], paths):
            return
        counts['imported'] += 1
        byte = target_byte(record)
        before.append(record[VIEW_BYTE])
        after.append(byte)
        if byte != record[VIEW_BYTE]:
            output[offset+VIEW_BYTE] = byte
            counts['changed'] += 1
    read_water(terrain, visit)

    def median(values):
        return sorted(values)[len(values)//2] if values else None
    report = dict(version=VERSION, **counts, kcd1_view_ratio=KCD1_VIEW_RATIO,
                  kcd2_road_view_ratio=KCD2_ROAD_VIEW_RATIO, native_byte=NATIVE_ROAD_BYTE,
                  median_byte_before=median(before), median_byte_after=median(after))
    return bytes(output), report
