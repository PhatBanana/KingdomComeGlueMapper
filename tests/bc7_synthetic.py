"""Tiny hand-made BC7 textures: each 4x4 block is one constant colour (mode 6, equal endpoints)."""
import struct


def constant_block(r7, g7, b7, a7, p=1):
    """One block whose 16 texels all read (2*v7+p) per channel; p is the shared endpoint p-bit."""
    value = 1 << 6
    shift = 7
    for channel in map(int, (r7, g7, b7, a7)):
        value |= channel << shift; value |= channel << (shift + 7); shift += 14
    value |= (p << shift) | (p << (shift + 1))
    return value.to_bytes(16, 'little')


def bc7_dds(width, height, mips, dxgi=99, trailer=True):
    """A DX10 BC7 file; `mips` lists each level's blocks (row-major) down to the 4x4 tail."""
    header = bytearray(148)
    header[:4] = b'DDS '
    struct.pack_into('<7I', header, 4, 124, 0x2100F, height, width, 0, 0, len(mips))
    struct.pack_into('<2I4s', header, 76, 32, 4, b'DX10')
    struct.pack_into('<5I', header, 128, dxgi, 3, 0, 1, 0)
    return bytes(header) + b''.join(b''.join(level) for level in mips) + (b'CExtCEnd' if trailer else b'')
