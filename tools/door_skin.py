"""Normalize the legacy rigid-door internal vertex origin before rig conversion."""
import struct
import numpy as np
from audit_character_bodies import inspect_mesh
from clothing_regions import read_chunks, write_chunks


def align_internal_origin(blob):
    _,vertices,_ = inspect_mesh(blob)
    chunks=read_chunks(blob)
    internal, = [c for c in chunks if c.kind==0x2005]
    remapping, = [c for c in chunks if c.kind==0x2006]
    if internal.version!=0x800 or (len(internal.data)-32)%64:
        raise ValueError('Unsupported door internal vertices')
    count=(len(internal.data)-32)//64
    remap=np.frombuffer(remapping.data,dtype='<u2')
    if len(remap)!=len(vertices) or np.any(remap>=count):raise ValueError('Invalid door vertex remap')
    positions=np.array([struct.unpack_from('<3f',internal.data,32+64*int(i)+12) for i in remap])
    delta=np.asarray(vertices)-positions
    if not np.isfinite(delta).all():raise ValueError('Nonfinite door geometry')
    if np.allclose(delta,0,rtol=0,atol=1e-5):return blob, [0.,0.,0.]
    # Some shipped doors have an old local origin in the internal CPU buffer.
    # Accept only a single rigid translation; do not mask remap or mesh defects.
    if not np.allclose(delta,delta[0],rtol=0,atol=1e-5):
        raise ValueError('Door internal geometry differs by more than a rigid origin offset')
    payload=bytearray(internal.data)
    for i in range(count):
        offset=32+64*i+12
        p=np.asarray(struct.unpack_from('<3f',payload,offset))+delta[0]
        struct.pack_into('<3f',payload,offset,*p)
    return write_chunks(chunks,{internal.id:bytes(payload)}),delta[0].tolist()
