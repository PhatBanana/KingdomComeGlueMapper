"""Read-only CGF structure check: chunk table, mesh streams, index ranges, finite positions.

Ported from the hand-run ``cgfcheck.py`` used in the GPU-lock triage. Array maths uses
``array``/``bytes`` slicing so a whole package can be scanned without extra dependencies.
"""
from array import array
import math
import struct

STREAM_NAMES = {0: 'pos', 1: 'norm', 2: 'uv', 3: 'col', 4: 'col2', 5: 'idx', 6: 'tan', 7: 'shcoef', 8: 'shape',
                9: 'bonemap', 10: 'faceidx', 11: 'vertidx', 12: 'qtan', 13: 'skin', 14: 'dummy2', 15: 'p3s_c4b_t2s'}
MESH_CHUNK, STREAM_CHUNK = 0x1000, 0x1016
SUBSET_STRIDE = 36
# High bytes of an IEEE half whose exponent is all ones (inf/nan): bits 14..10 -> byte 1 bits 6..2.
_HALF_BAD = bytes(1 if (b & 0x7C) == 0x7C else 0 for b in range(256))


def check(blob):
    """Return ``dict(problems=[...], meshes=[...], max_position=float)``."""
    out = dict(problems=[], meshes=[], max_position=0.0)
    problems = out['problems']
    if len(blob) < 16 or blob[:4] != b'CrCh':
        problems.append(('cgf_magic', 'Not a CrCh chunk file'))
        return out
    version, count, table = struct.unpack_from('<III', blob, 4)
    out['version'] = hex(version)
    if table + count * 16 > len(blob):
        problems.append(('cgf_chunk_table', 'Chunk table exceeds file'))
        return out
    chunks = {}
    for i in range(count):
        kind, ver, ident, size, offset = struct.unpack_from('<HHIII', blob, table + i * 16)
        if offset + size > len(blob): problems.append(('cgf_chunk_truncated', f'chunk {ident} truncated'))
        chunks[ident] = (kind, ver, blob[offset:offset + size])
    for ident, (kind, ver, data) in chunks.items():
        if kind != MESH_CHUNK: continue
        if len(data) < 92:
            problems.append(('cgf_mesh_header', f'mesh {ident} header is {len(data)} B'))
            continue
        flags, _, nverts, nidx, nsub, subid = struct.unpack_from('<6I', data)
        streams = struct.unpack_from('<16I', data, 28)
        mesh = dict(id=ident, verts=nverts, indices=nidx, subsets=nsub, flags=flags)
        indices = None
        for slot, chunk_id in enumerate(streams):
            if not chunk_id: continue
            if chunk_id not in chunks:
                problems.append(('cgf_stream_missing', f'mesh {ident} stream {slot} chunk {chunk_id} absent'))
                continue
            kind2, _, d = chunks[chunk_id]
            if kind2 != STREAM_CHUNK or len(d) < 16:
                problems.append(('cgf_stream_kind', f'mesh {ident} stream chunk {chunk_id} kind {kind2:#x}'))
                continue
            _, stype, cnt, width = struct.unpack_from('<4I', d)
            payload = memoryview(d)[24:]
            name = STREAM_NAMES.get(stype, str(stype))
            if len(payload) < cnt * width:
                problems.append(('cgf_stream_short', f'mesh {ident} {name} stream {len(payload)} B < {cnt * width} B'))
                continue
            if stype == 5:
                if width not in (2, 4):
                    problems.append(('cgf_index_width', f'mesh {ident} index width {width}'))
                    continue
                indices = array('H' if width == 2 else 'I')
                indices.frombytes(bytes(payload[:cnt * width]))
                if cnt != nidx: problems.append(('cgf_index_count', f'mesh {ident} index stream {cnt} != {nidx}'))
                if indices and max(indices) >= nverts:
                    problems.append(('cgf_index_range', f'mesh {ident} index {max(indices)} >= {nverts} vertices'))
                if cnt % 3: problems.append(('cgf_index_triangles', f'mesh {ident} {cnt} indices is not a triangle list'))
            elif cnt != nverts:
                problems.append(('cgf_stream_count', f'mesh {ident} {name} count {cnt} != {nverts} vertices'))
            if stype == 0 and width == 12 and cnt:
                values = array('f')
                values.frombytes(bytes(payload[:cnt * 12]))
                total = sum(values)
                if not math.isfinite(total):
                    problems.append(('cgf_position_nonfinite', f'mesh {ident} has non-finite positions'))
                else:
                    big = max(max(values), -min(values))
                    mesh['max_position'] = big
                    out['max_position'] = max(out['max_position'], big)
            elif (stype == 15 and width in (16, 20)) or (stype == 0 and width == 8):
                raw = bytes(payload[:cnt * width])
                for component in (1, 3, 5):
                    if 1 in raw[component::width].translate(_HALF_BAD):
                        problems.append(('cgf_position_nonfinite', f'mesh {ident} has non-finite half positions'))
                        break
        if subid in chunks and not flags & 1:
            _, _, d = chunks[subid]
            if len(d) < 8:
                problems.append(('cgf_subset_chunk', f'mesh {ident} subset chunk is {len(d)} B'))
                continue
            sub_count = struct.unpack_from('<2I', d)[1]
            if sub_count == 0 or sub_count > 4096 or len(d) < 16 + SUBSET_STRIDE * sub_count:
                problems.append(('cgf_subset_chunk', f'mesh {ident} subset chunk count {sub_count}, {len(d)} B'))
                sub_count = 0
            for i in range(sub_count):
                first, size, first_vertex, vertex_count, _ = struct.unpack_from('<5I', d, 16 + i * SUBSET_STRIDE)
                if first + size > nidx or first_vertex + vertex_count > nverts:
                    problems.append(('cgf_subset_range', f'mesh {ident} subset {i} outside the index/vertex streams'))
                elif indices and size:
                    segment = indices[first:first + size]
                    if min(segment) < first_vertex or max(segment) >= first_vertex + vertex_count:
                        problems.append(('cgf_subset_indices', f'mesh {ident} subset {i} indices leave '
                                         f'[{first_vertex},{first_vertex + vertex_count})'))
        out['meshes'].append(mesh)
    return out
