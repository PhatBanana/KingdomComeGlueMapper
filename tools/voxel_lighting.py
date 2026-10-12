"""Bounded KCD1 opacity-bake reader and KCD2 SVI3/SVV3 writer.

The source basic-GI bake contains opacity only. It cannot supply the albedo
and normal channels required by advanced GI. No such channels are fabricated.
"""
import math
import struct
import zlib

import numpy as np


INDEX_MAGIC = b'3IVS'
VOXEL_MAGIC = b'3VVS'
ABSENT = 0xffffffff
RECORD = struct.Struct('<8I')


def inflate(blob, expected):
    if not 0 < expected <= 1024*1024:
        raise ValueError('Voxel block exceeds supported size')
    stream = zlib.decompressobj()
    raw = stream.decompress(blob, expected+1)
    if len(raw) != expected or not stream.eof or stream.unused_data or stream.unconsumed_tail:
        raise ValueError('Invalid voxel compression or size')
    return raw


def opacity_block(raw, active_layers=frozenset({0})):
    if len(raw) < 16:
        raise ValueError('Truncated source voxel header')
    dims, crop = raw[:3], raw[4:7]
    layers, subsets = raw[3], raw[7]
    if not layers or subsets != 1 or raw[8:12] != bytes(4):
        raise ValueError('Unsupported source voxel layers/subsets')
    if any(d == 0 or d+c > 16 for d, c in zip(dims, crop)):
        raise ValueError('Invalid source voxel crop')
    count = math.prod(dims)
    if len(raw) != 12+layers*(4+count*2):
        raise ValueError('Source opacity payload size mismatch')
    packed = np.zeros(count*2, dtype=np.uint8)
    layer_ids = set()
    for i in range(layers):
        offset = 12+i*(4+count*2)
        identity = struct.unpack_from('<I', raw, offset)[0]
        if identity in layer_ids:
            raise ValueError('Duplicate source voxel layer')
        layer_ids.add(identity)
        if identity in active_layers:
            data = np.frombuffer(raw, dtype=np.uint8, count=count*2, offset=offset+4)
            # Combine selected layers channel-wise, as the source runtime does.
            packed = np.maximum(packed & 15, data & 15) | (np.maximum(packed >> 4, data >> 4) << 4)
    rgba = np.empty(count*4, dtype=np.uint8)
    # Source nibble encoding is sqrt(comp)/16. Expand to linear bytes using
    # the source decoder's truncation, retaining BGRA on-disk channel order.
    lut = np.array([int((n*16/255)**2*255) for n in range(16)], dtype=np.uint8)
    rgba[0::2] = lut[packed & 15]
    rgba[1::2] = lut[packed >> 4]
    # Native shipped bricks have a full 16^3 extent and zero crop origin.
    # Place legacy cropped samples at their original cell coordinates, rather
    # than depending on the target's handling of the old crop metadata.
    full = np.zeros((16, 16, 16, 4), dtype=np.uint8)
    x, y, z = crop
    dx, dy, dz = dims
    full[z:z+dz, y:y+dy, x:x+dx] = rgba.reshape(dz, dy, dx, 4)
    header = bytes([16,16,16,0])+bytes(8)+struct.pack('<II', 1, int(full[:,:,:,3].max()))
    return header+full.tobytes()


def source_nodes(blob, center, extent=256, active_layers=frozenset({0})):
    """Yield absolute node boxes and decoded opacity; reject corrupt graphs."""
    seen = set()
    intervals = []

    def walk(offset, size, origin, edge):
        if offset in seen or offset < 0 or offset+size > len(blob) or size < 4 or edge < 1:
            raise ValueError('Invalid source voxel tree reference')
        seen.add(offset)
        intervals.append((offset, offset+size))
        length = struct.unpack_from('<I', blob, offset)[0]
        end = offset+4+((length+3) & ~3)
        if end > offset+size or offset+size-end not in (0, 64):
            raise ValueError('Source voxel node size mismatch')
        payload = None
        if length:
            if length < 5:
                raise ValueError('Truncated compressed voxel')
            expected = struct.unpack_from('<I', blob, offset+4)[0]
            payload = opacity_block(inflate(blob[offset+8:offset+4+length], expected), active_layers)
        yield (*origin, edge), payload
        if end != offset+size:
            if edge % 2:
                raise ValueError('Non-integral voxel child size')
            half = edge//2
            for child in range(8):
                pos, length = struct.unpack_from('<II', blob, end+child*8)
                if length:
                    child_origin = tuple(origin[a]+half*((child >> (2-a)) & 1) for a in range(3))
                    yield from walk(pos, length, child_origin, half)
                elif pos:
                    raise ValueError('Dangling voxel child offset')

    yield from walk(0, 68, tuple(c-extent//2 for c in center), extent)
    intervals.sort()
    if intervals[0][0] != 0 or intervals[-1][1] != len(blob) or any(a[1] != b[0] for a, b in zip(intervals, intervals[1:])):
        raise ValueError('Overlapping or unconsumed source voxel records')


def convert_tile(blob, center, extent=256, active_layers=frozenset({0})):
    index = bytearray(INDEX_MAGIC)
    voxels = bytearray(VOXEL_MAGIC)
    nodes = list(source_nodes(blob, center, extent, active_layers))
    # Native indexes are ordered by their spatial key; root is first.
    nodes[1:] = sorted(nodes[1:], key=lambda n: n[0])
    for box, payload in nodes:
        if payload is None:
            offset = size = ABSENT
        else:
            offset = len(voxels)
            compressed = struct.pack('<I', len(payload))+zlib.compress(payload)
            size = len(compressed)
            voxels.extend(compressed)
        index.extend(RECORD.pack(*box, 1, 0, offset, size))
    validate_pair(index, voxels)
    return bytes(index), bytes(voxels)


def validate_pair(index, voxels):
    if index[:4] != INDEX_MAGIC or voxels[:4] != VOXEL_MAGIC or (len(index)-4) % RECORD.size:
        raise ValueError('Invalid native voxel file header')
    boxes = set()
    cursor = 4
    blocks = 0
    masks = set()
    for x, y, z, edge, enabled, reserved, offset, size in RECORD.iter_unpack(index[4:]):
        box = (x, y, z, edge)
        if box in boxes or edge == 0 or edge & (edge-1) or enabled != 1 or reserved:
            raise ValueError('Invalid native voxel index record')
        boxes.add(box)
        if offset == size == ABSENT:
            continue
        if offset != cursor or size < 5 or offset+size > len(voxels):
            raise ValueError('Invalid native voxel payload reference')
        expected = struct.unpack_from('<I', voxels, offset)[0]
        raw = inflate(voxels[offset+4:offset+size], expected)
        if len(raw) < 20 or raw[3] or raw[7] or raw[8:12] != bytes(4):
            raise ValueError('Unsupported native voxel block header')
        mask, alpha = struct.unpack_from('<II', raw, 12)
        if mask not in (1, 7) or alpha > 255 or any(d == 0 or d+c > 16 for d, c in zip(raw[:3], raw[4:7])):
            raise ValueError('Invalid native voxel channels/crop')
        if len(raw) != 20+math.prod(raw[:3])*4*mask.bit_count():
            raise ValueError('Native voxel channel payload mismatch')
        masks.add(mask)
        cursor += size
        blocks += 1
    if cursor != len(voxels):
        raise ValueError('Unreferenced native voxel payload')
    return {'nodes': len(boxes), 'blocks': blocks, 'channel_masks': sorted(masks)}
