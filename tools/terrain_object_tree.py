"""KCD2 surface insertion, independent of the source tree's available children.

Surface insertion uses these spatial subdivision rules:
8 m minimum cells, 1/16 node-radius size gate, view-distance gate, then centre
selection (X=4, Y=2, Z=1; equality selects the low half). Cell bounds are NOT
object bounds. The engine recomputes aggregate object bounds while loading.
"""
from bisect import bisect_right
from dataclasses import dataclass, field
import math
import struct
from types import SimpleNamespace

VERSION = 1
KIND_ORDER = {9: 0, 7: 1, 11: 2, 23: 3}
SURFACES = frozenset((7, 9, 11))


@dataclass(frozen=True)
class Policy:
    """Placement defaults; independent of the player's graphics preset."""
    minimum_size: float = 8.0
    size_ratio: float = 0.0625
    vegetation_view_ratio: float = 30.0
    view_ratio: float = 60.0
    road_view_distance: float = 28.0
    minimum_view_distance: float = 5.0


DEFAULT_POLICY = Policy()


def f32(value):
    """Native comparisons use single precision, including the equality boundaries."""
    try:
        return struct.unpack('<f', struct.pack('<f', value))[0]
    except OverflowError as error:
        raise ValueError('Object bounds exceed supported float32 arithmetic') from error


def bounds(blob, offset=4):
    if len(blob) < offset + 24:
        raise ValueError('Truncated object bounds')
    box = struct.unpack_from('<6f', blob, offset)
    if not all(map(math.isfinite, box)) or any(box[a] > box[a+3] for a in range(3)):
        raise ValueError('Invalid or non-finite object bounds')
    return box


def radius_squared(box):
    sides = [f32(box[a+3] - box[a]) for a in range(3)]
    squares = [f32(side * side) for side in sides]
    return f32(f32(f32(squares[0]+squares[1])+squares[2]) * 0.25)


def maximum_view_distance(record, policy=DEFAULT_POLICY):
    """Surface render-node defaults. Keep the serialized view/LOD bytes unchanged.

    255 is the native exceptional 100x view multiplier, not 2.55x. These are
    view-distance bytes; KCD2's separate nonlinear LOD encoding does not apply.
    Decal orientation already contains scale in compiled terrain records.
    """
    kind = struct.unpack_from('<I', record)[0]
    if kind not in SURFACES or len(record) < 44:
        raise ValueError('Expected a complete KCD2 surface record')
    ratio = 100.0 if record[42] == 255 else f32(record[42] * f32(0.01))
    if kind == 11:
        distance = policy.road_view_distance
    elif kind == 7:
        if len(record) != 120:
            raise ValueError('Unexpected KCD2 decal size')
        # Matrix33 first column: m00, m10, m20.
        column = [struct.unpack_from('<f', record, offset)[0] for offset in (72, 84, 96)]
        if not all(map(math.isfinite, column)):
            raise ValueError('Non-finite decal orientation')
        squares = [f32(v*v) for v in column]
        length = f32(math.sqrt(f32(f32(squares[0]+squares[1])+squares[2])))
        distance = f32(f32(length * 0.75) * policy.view_ratio)
    else:
        distance = f32(f32(math.sqrt(radius_squared(bounds(record)))) * policy.view_ratio)
    return max(policy.minimum_view_distance, f32(distance * ratio))


def child_box(box, child):
    middle = [f32(f32(box[a] + box[a+3]) * 0.5) for a in range(3)]
    return tuple(middle[a] if child & (4 >> a) else box[a] for a in range(3)) + tuple(
        box[a+3] if child & (4 >> a) else middle[a] for a in range(3))


def destination(root_box, object_box, max_view_distance, policy=DEFAULT_POLICY):
    """Return the native octant path, including children absent from the input."""
    values = (*root_box, *object_box, max_view_distance, *vars(policy).values())
    if (not all(map(math.isfinite, values)) or max_view_distance < 0
            or any(v <= 0 for v in vars(policy).values())
            or any(root_box[a] >= root_box[a+3] or object_box[a] > object_box[a+3] for a in range(3))):
        raise ValueError('Invalid octree insertion parameters')
    centre = [f32(f32(object_box[a] + object_box[a+3]) * 0.5) for a in range(3)]
    object_radius_sq = radius_squared(object_box)
    cell, path = root_box, []
    while cell[3] - cell[0] > policy.minimum_size:
        node_radius = f32(math.sqrt(radius_squared(cell)))
        radius_limit = f32(node_radius * policy.size_ratio)
        if (object_radius_sq >= f32(radius_limit * radius_limit)
                or max_view_distance >= f32(node_radius * policy.vegetation_view_ratio)
                or not all(cell[a] <= centre[a] <= cell[a+3] for a in range(3))):
            break
        child = sum((4 >> a) for a in range(3) if centre[a] > (cell[a] + cell[a+3]) * 0.5)
        path.append(child)
        if len(path) > 32:
            raise ValueError('Object tree exceeds supported depth')
        cell = child_box(cell, child)
    return tuple(path)


@dataclass
class Node:
    box: tuple
    reserved: int = 0
    records: list = field(default_factory=list)
    children: dict = field(default_factory=dict)


def read_tree(terrain):
    """Validate every record using the shared bounded parser before modifying it."""
    from water_volumes import read_water
    data, starts, nodes = terrain.data, [], []

    def visit(offset, depth):
        if depth > 32 or offset + 32 > len(data):
            raise ValueError('Invalid object tree')
        version, mask, reserved, *rest = struct.unpack_from('<HBB6fI', data, offset)
        if version != 8:
            raise ValueError('Expected KCD2 object tree version 8')
        node = Node(bounds(data, offset+4), reserved)
        if any(node.box[a] >= node.box[a+3] for a in range(3)):
            raise ValueError('Empty octree cell')
        starts.append(offset+32)
        nodes.append(node)
        cursor = offset + 32 + rest[-1]
        if cursor > len(data):
            raise ValueError('Object block exceeds terrain')
        for bit in range(8):
            if mask & (1 << bit):
                child, cursor = visit(cursor, depth+1)
                if child.box != child_box(node.box, bit):
                    raise ValueError('Octree child bounds do not match its octant')
                node.children[bit] = child
        return node, cursor

    root, end = visit(terrain.tree_offset, 0)
    if end != len(data):
        raise ValueError('Unconsumed object tree bytes')
    def collect(blob, offset, size, kind):
        nodes[bisect_right(starts, offset)-1].records.append((kind, blob[offset:offset+size]))
    read_water(SimpleNamespace(data=data, tree_offset=terrain.tree_offset, version=29), collect)
    return root, nodes


def serialize(root):
    chunks = []
    def visit(node):
        # Stable within each native render-list category.
        payload = b''.join(blob for _, blob in sorted(node.records, key=lambda r: KIND_ORDER.get(r[0], 4)))
        mask = sum(1 << bit for bit in node.children)
        chunks.append(struct.pack('<HBB6fI', 8, mask, node.reserved, *node.box, len(payload)))
        chunks.append(payload)
        for bit in sorted(node.children):
            visit(node.children[bit])
    visit(root)
    return b''.join(chunks)


def place(terrain, records=(), *, relocate=False, policy=DEFAULT_POLICY):
    """Insert new surfaces, or reinsert existing surfaces for completed builds.

    Existing brush/vegetation/merged records and their cell ownership survive.
    No geometry, material indices, IDs, layers, flags or view/LOD bytes change.
    """
    root, nodes = read_tree(terrain)
    records = list(records)
    if relocate:
        for node in nodes:
            records.extend(blob for kind, blob in node.records if kind in SURFACES)
            node.records[:] = [(kind, blob) for kind, blob in node.records if kind not in SURFACES]
    if not records:
        return terrain.data[terrain.tree_offset:]
    for record in records:
        # Validate complete strides, not just enough bytes to extract an AABB.
        from water_volumes import read_water
        check = struct.pack('<HBB6fI', 8, 0, 0, *root.box, len(record)) + record
        _, counts = read_water(SimpleNamespace(data=check, tree_offset=0, version=29))
        kind = struct.unpack_from('<I', record)[0]
        if kind not in SURFACES or counts != {kind: 1}:
            raise ValueError('Expected one KCD2 surface record')
        path = destination(root.box, bounds(record), maximum_view_distance(record, policy), policy)
        node = root
        for bit in path:
            if bit not in node.children:
                node.children[bit] = Node(child_box(node.box, bit))
            node = node.children[bit]
        node.records.append((kind, record))
    return serialize(root)
