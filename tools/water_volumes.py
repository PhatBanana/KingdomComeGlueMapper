"""Bounded readers/conversion for the installed v28/v29 water volume records."""
from bisect import bisect_right
from collections import Counter
import math
import struct
from types import SimpleNamespace


def water_record(data, offset, end, version):
    extra = 4 if version == 29 else 0
    header = 144 + extra
    if offset + header > end:
        raise ValueError("Truncated water header")
    bits = struct.unpack_from("<I", data, offset + 40 + extra)[0]
    vertices = struct.unpack_from("<I", data, offset + 124 + extra)[0]
    contour = struct.unpack_from("<I", data, offset + 136 + extra)[0]
    auxiliary = bits >> 24
    size = header + auxiliary * 4 + (vertices + contour) * 12
    if bits & 0xffff not in (2, 3) or auxiliary != (18 if extra else 16):
        raise ValueError("Unsupported water type or auxiliary layout")
    if vertices < 3 or (bits & 0xffff == 3 and vertices != 4) or offset + size > end:
        raise ValueError("Invalid water polygon or record bounds")
    geometry = offset + header + auxiliary * 4
    coordinates = struct.unpack_from(f"<{(vertices + contour) * 3}f", data, geometry)
    bbox = struct.unpack_from("<6f", data, offset + 4)
    if not all(map(math.isfinite, coordinates + bbox)):
        raise ValueError("Non-finite water geometry")
    if not all(bbox[a] <= bbox[a + 3] for a in range(3)):
        raise ValueError("Invalid water bounds")
    return {"offset": offset, "size": size, "type": bits & 0xffff,
            "auxiliary": auxiliary, "vertices": vertices, "contour": contour,
            "geometry_offset": geometry, "bbox": bbox,
            "material": struct.unpack_from("<i", data, offset + 52 + extra)[0]}


def read_water(terrain, visitor=None):
    """Walk every object block using observed, bounds-checked record strides.

    Roads use twelve-byte vertices and sixteen-bit indices in both builds;
    tangent stride changes from eight to sixteen bytes. No record scanning or
    resynchronizing on apparent type numbers is permitted.
    """
    data = terrain.data
    new = terrain.version == 29
    extra = 4 if new else 0
    cursor = terrain.tree_offset
    water = []
    counts = Counter()

    def visit(depth=0):
        nonlocal cursor
        if depth > 32 or cursor + 32 > len(data):
            raise ValueError("Invalid object tree")
        header = struct.unpack_from("<HBB6fI", data, cursor)
        if header[0] != (8 if new else 5):
            raise ValueError("Unexpected object tree version")
        cursor += 32
        end = cursor + header[-1]
        if end > len(data):
            raise ValueError("Object block exceeds file")
        while cursor < end:
            if cursor + 4 > end:
                raise ValueError("Truncated object type")
            kind = struct.unpack_from("<I", data, cursor)[0]
            if kind in (1, 2, 7):
                size = {1: 100 + extra, 2: 64, 7: 116 + extra}[kind]
            elif kind == 23:
                if cursor + 68 + extra > end:
                    raise ValueError("Truncated merged node")
                groups = struct.unpack_from("<I", data, cursor + 40 + extra)[0]
                size = 68 + extra + groups * (12 if new else 8)
            elif kind == 11:
                if cursor + 108 + extra > end:
                    raise ValueError("Truncated road node")
                v, i, t, p, s = struct.unpack_from("<5I", data, cursor + 80 + extra)
                size = 108 + extra + v * 12 + i * 2 + t * (16 if new else 8) + p * 40 + s * 12
                size = (size + 3) & ~3
            elif kind == 9:
                record = water_record(data, cursor, end, terrain.version)
                water.append(record)
                size = record["size"]
            else:
                raise ValueError(f"Unsupported object type {kind} at {cursor}")
            if cursor + size > end:
                raise ValueError(f"Object type {kind} exceeds its block")
            if visitor is not None:
                visitor(data, cursor, size, kind)
            counts[kind] += 1
            cursor += size
        for bit in range(8):
            if header[1] & (1 << bit):
                visit(depth + 1)
    visit()
    if cursor != len(data):
        raise ValueError("Unconsumed object tree bytes")
    return water, dict(counts)


def convert_water(data, record, material, auxiliary_tail):
    start = record["offset"]
    old = data[start:start + record["size"]]
    if len(auxiliary_tail) != 8:
        raise ValueError("Expected two native auxiliary values")
    source = water_record(old, 0, len(old), 28)
    header = bytearray(old[:36] + bytes(4) + old[36:144])
    struct.pack_into("<H", header, 28, 0)  # isolated development layer
    bits = struct.unpack_from("<I", header, 44)[0]
    struct.pack_into("<I", header, 44, (bits & 0xffffff) | (18 << 24))
    struct.pack_into("<i", header, 56, material)
    # Keep the flag byte but clear compiler padding following it.
    header[145:148] = bytes(3)
    output = bytes(header) + old[144:208] + auxiliary_tail + old[208:]
    target = water_record(output, 0, len(output), 29)
    if output[target["geometry_offset"]:] != old[source["geometry_offset"]:]:
        raise ValueError("Water surface or physics contour changed")
    return output


# Native nodes group their records in this kind order (water, decal, road, merged).
NATIVE_KIND_ORDER = {9: 0, 7: 1, 11: 2, 23: 3}


def _tree_nodes(data, offset, new):
    """Node headers in file order as (header offset, payload size, box, child indices)."""
    nodes = []

    def visit(cursor, depth):
        if depth > 32 or cursor + 32 > len(data):
            raise ValueError("Invalid object tree")
        header = struct.unpack_from("<HBB6fI", data, cursor)
        if header[0] != (8 if new else 5):
            raise ValueError("Unexpected object tree version")
        node = (cursor, header[-1], header[3:9], [])
        nodes.append(node)
        cursor += 32 + header[-1]
        for bit in range(8):
            if header[1] & (1 << bit):
                node[3].append(len(nodes))
                cursor = visit(cursor, depth + 1)
        return cursor

    if visit(offset, 0) != len(data):
        raise ValueError("Unconsumed object tree bytes")
    return nodes


def place_records(terrain, records):
    """Return the object tree with each record in the deepest node containing its bounds.

    Appending converted roads, decals and water to the root left ~30k objects in
    one node where native levels hold at most a few hundred, and menus opened
    right after a cold load then froze the renderer. Records that fit no child
    stay in the root; nodes that receive nothing are copied verbatim.
    """
    data = terrain.data
    new = struct.unpack_from("<H", data, terrain.tree_offset)[0] == 8
    nodes = _tree_nodes(data, terrain.tree_offset, new)
    added = {}
    for record in records:
        box = struct.unpack_from("<6f", record, 4)
        if not all(map(math.isfinite, box)):
            raise ValueError("Non-finite record bounds")
        index = 0
        while True:
            inside = [c for c in nodes[index][3]
                      if all(nodes[c][2][a] <= box[a] and box[a + 3] <= nodes[c][2][a + 3] for a in range(3))]
            if not inside:
                break
            index = inside[0]
        added.setdefault(index, []).append(record)
    existing = {index: [] for index in added}
    starts = [offset + 32 for offset, _, _, _ in nodes]

    def collect(blob, offset, size, kind):
        index = bisect_right(starts, offset) - 1
        if index in existing:
            existing[index].append((kind, blob[offset:offset + size]))
    if added:
        read_water(SimpleNamespace(data=data, tree_offset=terrain.tree_offset, version=29 if new else 28), collect)
    output = bytearray()
    for index, (offset, size, _, _) in enumerate(nodes):
        start = offset + 32
        if index not in added:
            output += data[offset:start + size]
            continue
        own = existing[index] + [(struct.unpack_from("<I", r)[0], r) for r in added[index]]
        own.sort(key=lambda r: NATIVE_KIND_ORDER.get(r[0], len(NATIVE_KIND_ORDER)))
        payload = b"".join(blob for _, blob in own)
        header = bytearray(data[offset:start])
        struct.pack_into("<I", header, 28, len(payload))
        output += header + payload
    return bytes(output)


def append_water(terrain, records, material_paths):
    table = terrain.tables["materials"]
    if table["paths"]:
        raise ValueError("This water stage expects an empty base material table")
    prefix = terrain.data[:table["offset"] - 4]
    names = bytearray(struct.pack("<I", len(material_paths)))
    for name in material_paths:
        encoded = name.encode("utf-8")
        if len(encoded) >= 256:
            raise ValueError("Material path too long")
        names.extend(encoded.ljust(256, b"\0"))
    nodes = terrain.data[table["offset"]:terrain.tree_offset]
    output = bytearray(prefix + names + nodes + place_records(terrain, records))
    struct.pack_into("<I", output, 4, len(output))
    return bytes(output)
