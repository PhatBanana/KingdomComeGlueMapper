"""Give converted building blend materials non-overlapping secondary UV charts.

Only render vertices are duplicated at chart seams. Physics chunks, node
transforms, primary UVs, positions, normals and tangents retain their values.
"""
import struct

import numpy as np

from clothing_regions import read_chunks, write_chunks


def reatlas(blob, material_id, resolution=2048):
    import xatlas

    chunks = read_chunks(blob)
    lookup = {c.id: c for c in chunks}
    replacements = {}
    matches = []
    for mesh in chunks:
        if mesh.kind != 0x1000 or mesh.version not in (0x800, 0x801):
            continue
        flags, _, nv, ni, ns, sid = struct.unpack_from('<6I', mesh.data)
        if not nv or flags & 1:
            continue
        ids = struct.unpack_from('<16I', mesh.data, 28)
        subset = lookup[sid]
        if subset.version != 0x800 or len(subset.data) < 16 + ns * 36:
            raise ValueError('Unsupported building subsets')
        ranges = []
        for i in range(ns):
            first, count, _, _, mat = struct.unpack_from('<5I', subset.data, 16+i*36)
            if mat == material_id:
                ranges.append((i, first, count))
        if ranges:
            matches.append((mesh, nv, ni, ids, subset, ranges))
    if len(matches) != 1:
        raise ValueError('Blend atlas requires exactly one render mesh per material')
    mesh, nv, ni, ids, subset, ranges = matches[0]
    streams = {}
    for kind, ident in enumerate(ids):
        if not ident:
            continue
        c = lookup[ident]
        _, stream_kind, count, width = struct.unpack_from('<4I', c.data)
        if c.kind != 0x1016 or c.version != 0x800 or stream_kind != kind or len(c.data) != 24+count*width:
            raise ValueError('Unsupported building vertex stream')
        if count != (ni if kind == 5 else nv):
            raise ValueError('Building stream count mismatch')
        streams[kind] = (c, width)
    if 8 not in streams or streams[8][1] != 8 or streams[2][1] != 8:
        raise ValueError('Blend atlas requires float primary and secondary UV streams')
    pos, width = streams[0]
    if width not in (8, 12):
        raise ValueError('Unsupported position stream')
    positions = np.frombuffer(pos.data, '<f2' if width == 8 else '<f4', offset=24).reshape(nv, width//(2 if width == 8 else 4))[:, :3].astype(np.float32)
    index_chunk, width = streams[5]
    if width not in (2, 4):
        raise ValueError('Unsupported building indices')
    indices = np.frombuffer(index_chunk.data, '<u2' if width == 2 else '<u4', offset=24).astype(np.uint32)
    selected = np.concatenate([np.arange(first, first+count) for _, first, count in ranges])
    faces = indices[selected].reshape(-1, 3)
    if indices.max() >= nv:
        raise ValueError('Invalid building index')
    atlas = xatlas.Atlas()
    atlas.add_mesh(positions, faces, uvs=np.frombuffer(streams[2][0].data, '<f4', offset=24).reshape(-1, 2))
    options = xatlas.PackOptions()
    options.resolution = resolution
    options.padding = 8
    options.bilinear = True
    options.bruteForce = False
    atlas.generate(pack_options=options)
    mapping, new_faces, uv = atlas[0]
    if atlas.atlas_count != 1:
        raise ValueError('Building atlas unexpectedly spans multiple textures')
    # xatlas must keep face order and original triangle corner identity.
    if not np.array_equal(mapping[new_faces], faces):
        raise ValueError('Atlas changed building triangle correspondence')
    size = tuple(1 << (int(v)-1).bit_length() for v in (atlas.width, atlas.height))
    uv = uv * np.array([atlas.width/size[0], atlas.height/size[1]], np.float32)
    uv0 = np.frombuffer(streams[2][0].data, '<f4', offset=24).reshape(-1, 2)
    uv2 = np.frombuffer(streams[8][0].data, '<f4', offset=24).reshape(-1, 2)
    triangles = list(zip(uv0[faces], uv2[faces], uv[new_faces]))
    for kind, (chunk, width) in streams.items():
        if kind == 5:
            continue
        source = np.frombuffer(chunk.data, 'u1', offset=24).reshape(nv, width)
        extra = uv.astype('<f4').view('u1').reshape(-1, 8) if kind == 8 else source[mapping]
        header = bytearray(chunk.data[:24])
        struct.pack_into('<I', header, 8, nv+len(mapping))
        replacements[chunk.id] = bytes(header)+source.tobytes()+extra.tobytes()
    indices[selected] = nv+new_faces.reshape(-1)
    index_header = bytearray(index_chunk.data[:24])
    width = 2 if indices.max() < 65536 else 4
    struct.pack_into('<I', index_header, 12, width)
    replacements[index_chunk.id] = bytes(index_header)+indices.astype('<u2' if width == 2 else '<u4').tobytes()
    subset_data = bytearray(subset.data)
    for i, first, count in ranges:
        used = indices[first:first+count]
        struct.pack_into('<2I', subset_data, 16+i*36+8, int(used.min()), int(used.max()-used.min()+1))
    replacements[subset.id] = bytes(subset_data)
    mesh_data = bytearray(mesh.data)
    struct.pack_into('<I', mesh_data, 8, nv+len(mapping))
    replacements[mesh.id] = bytes(mesh_data)
    return write_chunks(chunks, replacements), triangles, size
