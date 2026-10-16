"""Repair detached external LOD roots already authored in base-mesh space.

KCD1 exported some external detail meshes on vertically separated authoring
nodes. Preserve all geometry and only align a matching root when its local
bounds fit the base and its translation is outside the entire mesh extent.
"""
import math
import struct
from clothing_regions import read_chunks, write_chunks


def root_mesh(chunks):
    nodes = [c for c in chunks if c.kind == 0x100b and c.version == 0x824
             and len(c.data) >= 204 and struct.unpack_from('<i', c.data, 68)[0] == -1]
    if len(nodes) != 1:
        return None
    node = nodes[0]
    mesh = next((c for c in chunks if c.id == struct.unpack_from('<i', node.data, 64)[0]), None)
    if mesh is None or mesh.kind != 0x1000 or mesh.version != 0x801 or len(mesh.data) != 264:
        return None
    bounds = struct.unpack_from('<6f', mesh.data, 108)
    if not all(map(math.isfinite, bounds)) or any(bounds[i] > bounds[i+3] for i in range(3)):
        return None
    return node, bounds


def align_external_lod(base, lod):
    """Return (payload, evidence); unsupported/unproven relationships stay intact."""
    source, chunks = read_chunks(base), read_chunks(lod)
    a, b = root_mesh(source), root_mesh(chunks)
    if a is None or b is None:
        return lod, None
    parent, bounds = a
    node, detail_bounds = b
    if parent.data[:64] != node.data[:64] or parent.data[84:132] != node.data[84:132]:
        return lod, None
    origin = struct.unpack_from('<3f', parent.data, 132)
    displaced = struct.unpack_from('<3f', node.data, 132)
    if not all(map(math.isfinite, origin + displaced)):
        return lod, None
    extent = math.dist(bounds[:3], bounds[3:])
    # Root translations are centimetres; compiled mesh bounds are metres.
    if math.dist(origin, displaced) * .01 <= max(extent, 1):
        return lod, None
    tolerance = max(.05, extent * .02)
    if any(detail_bounds[i] < bounds[i]-tolerance or
           detail_bounds[i+3] > bounds[i+3]+tolerance for i in range(3)):
        return lod, None
    replacement = node.data[:132] + parent.data[132:144] + node.data[144:]
    return write_chunks(chunks, {node.id: replacement}), dict(
        node=node.data[:64].split(b'\0')[0].decode(),
        old_translation=list(displaced), new_translation=list(origin),
        local_bounds_preserved=True, geometry_preserved=True)
