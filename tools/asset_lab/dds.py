"""DDS header, streaming-family and stream-piece rules (read from bytes, never repaired)."""
import re
import struct

SPLIT = 0x200000
MAX_DIMENSION = 16384
MEMBER = re.compile(r'^(?P<base>.+\.dds)(?:\.(?P<part>\d+a?|a))?$')
FOURCC_BLOCK = {b'DXT1': 8, b'DXT3': 16, b'DXT5': 16, b'ATI1': 8, b'ATI2': 16, b'BC4U': 8, b'BC5U': 16}
DXGI_BLOCK = {71: 8, 72: 8, 74: 16, 75: 16, 77: 16, 78: 16, 80: 8, 81: 8, 83: 16, 84: 16,
              95: 16, 96: 16, 98: 16, 99: 16}
DXGI_PIXEL = {2: 16, 10: 8, 16: 8, 28: 4, 29: 4, 41: 4, 49: 2, 54: 2, 56: 2, 61: 1, 65: 1, 87: 4, 91: 4}
DXGI_NAME = {2: 'R32G32B32A32_FLOAT', 10: 'R16G16B16A16_FLOAT', 16: 'R32G32_FLOAT', 28: 'R8G8B8A8_UNORM',
             29: 'R8G8B8A8_UNORM_SRGB', 41: 'R32_FLOAT', 49: 'R8G8_UNORM', 54: 'R16_FLOAT', 56: 'R16_UNORM',
             61: 'R8_UNORM', 65: 'A8_UNORM', 71: 'BC1_UNORM', 72: 'BC1_UNORM_SRGB', 74: 'BC2_UNORM',
             75: 'BC2_UNORM_SRGB', 77: 'BC3_UNORM', 78: 'BC3_UNORM_SRGB', 80: 'BC4_UNORM', 81: 'BC4_SNORM',
             83: 'BC5_UNORM', 84: 'BC5_SNORM', 95: 'BC6H_UF16', 96: 'BC6H_SF16', 98: 'BC7_UNORM',
             99: 'BC7_UNORM_SRGB', 87: 'B8G8R8A8_UNORM', 91: 'B8G8R8A8_UNORM_SRGB'}
SRGB_DXGI = {29, 72, 75, 78, 91, 99}


class Malformed(ValueError):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


def parse_header(blob):
    """Return layout facts from the first 148 bytes, or raise Malformed(code, message).

    Layouts this module does not model (arrays, cubemaps, unknown formats) are returned
    with an ``unsupported`` reason and no sizes; callers must report them, not pass them.
    """
    if len(blob) < 128 or bytes(blob[:4]) != b'DDS ':
        raise Malformed('dds_magic', 'Not a DDS header')
    size, _, h, w, _, _, mips = struct.unpack_from('<7I', blob, 4)
    if size != 124 or struct.unpack_from('<I', blob, 76)[0] != 32:
        raise Malformed('dds_header_size', 'DDS header or pixel-format size is not 124/32')
    mips = mips or 1
    if not w or not h or w > MAX_DIMENSION or h > MAX_DIMENSION:
        raise Malformed('dds_dimensions', f'Unusable dimensions {w}x{h}')
    if mips > max(w, h).bit_length():
        raise Malformed('dds_mip_count', f'{mips} mips for {w}x{h}')
    pf_flags = struct.unpack_from('<I', blob, 80)[0]
    fourcc = bytes(blob[84:88])
    caps2 = struct.unpack_from('<I', blob, 112)[0]
    flags = struct.unpack_from('<I', blob, 36)[0]
    header, block, pixel, dxgi = 128, None, None, None
    dimension = misc = count = 0
    if fourcc == b'DX10':
        if len(blob) < 148: raise Malformed('dds_truncated', 'Truncated DX10 header')
        dxgi, dimension, misc, count, _ = struct.unpack_from('<5I', blob, 128)
        header = 148
        block, pixel = DXGI_BLOCK.get(dxgi), DXGI_PIXEL.get(dxgi)
        name = 'DX10:' + DXGI_NAME.get(dxgi, f'dxgi{dxgi}')
    elif fourcc in FOURCC_BLOCK:
        block, name = FOURCC_BLOCK[fourcc], fourcc.decode('latin1')
    elif pf_flags & (0x40 | 0x20000 | 0x2):
        bits = struct.unpack_from('<I', blob, 88)[0]
        name = f'RAW{bits}'
        if bits in (8, 16, 24, 32): pixel = bits // 8
    else:
        name = 'fourcc:' + fourcc.decode('latin1', 'replace')
    info = dict(width=w, height=h, mips=mips, header=header, format=name, block=block, pixel=pixel, dxgi=dxgi,
                srgb=dxgi in SRGB_DXGI, split_flag=bool(flags & SPLIT), cubemap=bool(caps2 & 0xFE00))
    if info['cubemap'] or misc & 4:
        info['cubemap'] = True
        info['unsupported'] = 'cubemap'
    elif fourcc == b'DX10' and (dimension != 3 or count > 1):
        info['unsupported'] = 'texture array or non-2D texture'
    elif block is None and pixel is None:
        info['unsupported'] = 'unknown pixel format ' + name
    if 'unsupported' in info:
        info['sizes'] = []
        return info
    info['sizes'] = [(((max(1, w >> i) + 3) // 4) * ((max(1, h >> i) + 3) // 4) * block) if block
                     else max(1, w >> i) * max(1, h >> i) * pixel for i in range(mips)]
    return info


def slot_class(key):
    """Texture-name suffix class (``_diff``, ``_ddna``...), the retail slot signal."""
    stem = key.rsplit('/', 1)[-1]
    stem = stem[:stem.index('.dds')] if '.dds' in stem else stem.rsplit('.', 1)[0]
    return '_' + stem.rsplit('_', 1)[1] if '_' in stem else ''


def families(keys):
    """Group lower-case member names as ``{base: {suffix: key}}`` ('' is the base itself)."""
    out = {}
    for key in keys:
        m = MEMBER.match(key)
        if m: out.setdefault(m.group('base'), {})[m.group('part') or ''] = key
    return out


def family_problems(info, base_size, tail, parts, label):
    """Structure findings for one family given sizes only. ``parts`` maps ``'1'`` -> bytes.

    The rules follow retail families and the texture_streaming converter: the base
    holds the resident tail, ``.N`` holds mip ``split - N`` exactly. Returns
    ``[(severity, code, detail)]``.
    """
    out = []
    sizes = info['sizes']
    resident = base_size - info['header'] - (8 if tail == b'CExtCEnd' else 0)
    split = [i for i in range(len(sizes)) if sum(sizes[i:]) == resident]
    if len(split) != 1:
        out.append(('error', 'dds_resident_mismatch', f'{label}: resident {resident} B matches no mip tail of '
                    f'{info["width"]}x{info["height"]} {info["format"]} ({info["mips"]} mips, total {sum(sizes)} B)'))
        return out
    split = split[0]
    if split and not info['split_flag']:
        out.append(('error', 'dds_split_flag_missing', f'{label}: {split} streamed mips without the split flag'))
    for n in range(1, split + 1):
        want = sizes[split - n]
        have = parts.get(str(n))
        if have is None:
            out.append(('error', 'dds_part_missing', f'{label}: streamed mip .{n} ({want} B) is absent'))
        elif have != want:
            out.append(('error', 'dds_part_size', f'{label}: .{n} is {have} B, mip needs {want} B'))
    stale = sorted(k for k in parts if int(k) > split or int(k) < 1)
    if stale: out.append(('review', 'dds_part_stale', f'{label}: unused streamed parts {stale}'))
    return out


def implied_piece(info, base_size):
    """Largest stream piece the header implies, independent of the bytes present."""
    sizes = info['sizes']
    if not sizes: return base_size
    return max(base_size, sizes[0] if info['split_flag'] else info['header'] + sum(sizes))
