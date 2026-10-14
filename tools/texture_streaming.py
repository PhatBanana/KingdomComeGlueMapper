"""Validate Cry DDS families and split generated 2D textures like native RC.

Existing mip pixels are preserved; missing byte-channel mask mips are filtered. Unsupported layouts fail
explicitly; cubemaps/arrays belong to their own converters.
"""
import struct
import re
import os
import subprocess
import tempfile
from pathlib import Path

SPLIT = 0x200000
BLOCK_BYTES = {71: 8, 72: 8, 74: 16, 75: 16, 77: 16, 78: 16,
               80: 8, 81: 8, 83: 16, 84: 16, 95: 16, 96: 16, 98: 16, 99: 16}


def layout(blob):
    if len(blob) < 128 or blob[:4] != b'DDS ':
        raise ValueError('Invalid DDS header')
    if struct.unpack_from('<I', blob, 4)[0] != 124 or struct.unpack_from('<I', blob, 76)[0] != 32:
        raise ValueError('Invalid DDS header size')
    h, w = struct.unpack_from('<II', blob, 12)
    mips = struct.unpack_from('<I', blob, 28)[0] or 1
    if not w or not h or mips > max(w, h).bit_length():
        raise ValueError('Invalid DDS dimensions/mip count')
    if struct.unpack_from('<I', blob, 112)[0] & 0xFE00:
        raise ValueError('Cubemap/volume requires a dedicated converter')
    header = 128
    fourcc = bytes(blob[84:88])
    pixel = None
    block = {b'DXT1': 8, b'DXT3': 16, b'DXT5': 16, b'ATI1': 8, b'ATI2': 16}.get(fourcc)
    if fourcc == b'DX10':
        if len(blob) < 148: raise ValueError('Truncated DX10 header')
        fmt, dimension, flags, count, _ = struct.unpack_from('<5I', blob, 128)
        if dimension != 3 or flags & 4 or count != 1:
            raise ValueError('Only single 2D textures supported')
        header = 148
        block = BLOCK_BYTES.get(fmt)
        pixel = {2:16,10:8,16:8,28:4,29:4,41:4,49:2,54:2,56:2,61:1,65:1,87:4,91:4}.get(fmt)
    elif not block and struct.unpack_from('<I', blob, 80)[0] & (0x40 | 0x20000 | 2):
        bits = struct.unpack_from('<I', blob, 88)[0]
        if bits in (8, 16, 24, 32): pixel = bits // 8
    if block is None and pixel is None: raise ValueError('Unsupported DDS pixel format')
    sizes = []
    for i in range(mips):
        wi, hi = max(1, w >> i), max(1, h >> i)
        sizes.append(((wi + 3)//4)*((hi + 3)//4)*block if block else wi*hi*pixel)
    return dict(header=header, width=w, height=h, sizes=sizes, block=block,
                flags=struct.unpack_from('<I', blob, 36)[0])


def validate_family(base, members):
    """members maps suffixes (.1, .2, .a, .1a) to bytes; no silent gaps."""
    info = layout(base)
    sizes = info['sizes']
    resident = len(base)-info['header']-(8 if base.endswith(b'CExtCEnd') else 0)
    candidates = [i for i in range(len(sizes)) if sum(sizes[i:]) == resident]
    if len(candidates) != 1: raise ValueError('Resident DDS data does not match mip sizes')
    split = candidates[0]
    if split and not info['flags'] & SPLIT: raise ValueError('Split DDS lacks streaming flag')
    required = {'.'+str(split-i): size for i, size in enumerate(sizes[:split])}
    for suffix, size in required.items():
        if suffix not in members: raise ValueError('Missing texture mip '+suffix)
        if len(members[suffix]) != size: raise ValueError('Wrong texture mip size '+suffix)
    if any(re.fullmatch(r'\.\d+a', k) for k in members) and '.a' not in members:
        raise ValueError('Missing alpha base for texture mips')
    if '.a' in members:
        alpha = members['.a']
        if not alpha.startswith(b'DDS '): alpha = b'DDS '+alpha
        validate_family(alpha, {k[:-1]: v for k, v in members.items() if k.endswith('a') and k != '.a'})
    return dict(streamed_mips=split, resident_mips=len(sizes)-split,
                stale_mips=sorted(k for k in members if k[1:].isdigit() and k not in required))


def split_generated(blob):
    """Native RC /streaming=1 layout: BC and uncompressed resident tails.

    Verified byte-for-byte against KCD2 RC for BC3, RGBA8 and RGBA16F.
    Existing Cry streaming families are left to validate_family.
    """
    if blob.endswith(b'CExtCEnd'): blob=blob[:-8]
    info = layout(blob)
    blob = complete_rgba_mips(blob)
    info = layout(blob)
    if info['flags'] & SPLIT: raise ValueError('Texture is already streamed')
    sizes = info['sizes']
    if len(blob) != info['header'] + sum(sizes): raise ValueError('Not a complete DDS mip chain')
    count = len(sizes)
    minimum_count = max(1, min(info['width'], info['height']).bit_length()-2)
    if count < minimum_count:
        raise ValueError('Generated DDS is missing lower mips; regenerate before streaming')
    count = min(count, minimum_count)
    # Native RC keeps <=16x16 resident for uncompressed, <=32x32 for BC.
    resident_count = 4 if info['block'] else 3
    split = max(0, count-resident_count)
    header = bytearray(blob[:info['header']])
    struct.pack_into('<I', header, 28, count)
    struct.pack_into('<I', header, 36, info['flags'] | SPLIT)
    struct.pack_into('<I', header, 116, min(4 if info['block'] else 2, count))
    struct.pack_into('<I', header, 124, 0x43525946)
    offset = info['header']; result = {}
    for i in range(split):
        result['.'+str(split-i)] = blob[offset:offset+sizes[i]]; offset += sizes[i]
    result[''] = bytes(header)+blob[offset:info['header']+sum(sizes[:count])]
    validate_family(result[''], {k:v for k,v in result.items() if k})
    return result


def repair_family(base, members, candidates):
    """Recover missing slices only from byte-identical overlapping families.

    A matching filename/size alone never establishes content identity.
    Conflicting donor bytes fail rather than making an arbitrary choice.
    """
    additions = {}
    for donor_base, donor in candidates:
        if family_signature(donor_base) != family_signature(base): continue
        if any(k in donor and donor[k] != v for k,v in members.items()): continue
        try: validate_family(donor_base, donor)
        except ValueError: continue
        for k,v in donor.items():
            if k in members: continue
            if k in additions and additions[k] != v:
                raise ValueError('Conflicting texture mip donors '+k)
            additions[k] = v
    validate_family(base, {**members, **additions})
    return additions


def family_signature(base):
    """Same format/header/tail, allowing an HD overlay to extend the top mips."""
    layout(base)
    normalized=bytearray(base)
    normalized[12:20]=bytes(8)
    normalized[28:32]=bytes(4)
    return bytes(normalized)


def complete_rgba_mips(blob):
    """Extend generated byte-channel masks without changing existing mip bytes.

    Pillow DDS masks use tightly packed RGB(A) channels. Each channel is filtered
    independently in its encoded numeric domain (these are material masks).
    Float/BC texture generators already supply their authored mip chain.
    """
    from PIL import Image
    info = layout(blob)
    count = len(info['sizes'])
    full = max(info['width'], info['height']).bit_length()
    if count == full or info['block'] or blob[84:88] == b'DX10':
        return blob
    bits = struct.unpack_from('<I', blob, 88)[0]
    if bits not in (24, 32) or info['flags'] & SPLIT:
        return blob
    validate_family(blob, {})
    mode = 'RGBA' if bits == 32 else 'RGB'
    # Filter raw channels; their serialized order is preserved by keeping masks.
    w, h = max(1, info['width'] >> (count-1)), max(1, info['height'] >> (count-1))
    end = info['header'] + sum(info['sizes'])
    pixels = Image.frombytes(mode, (w, h), blob[end-info['sizes'][-1]:end])
    tail = bytearray()
    while w > 1 or h > 1:
        w, h = max(1, w//2), max(1, h//2)
        pixels = Image.merge(mode, tuple(c.resize((w, h), Image.Resampling.BOX) for c in pixels.split()))
        tail.extend(pixels.tobytes())
    header = bytearray(blob[:info['header']])
    struct.pack_into('<I', header, 28, full)
    struct.pack_into('<I', header, 8, struct.unpack_from('<I', header, 8)[0] | 0x20000)
    struct.pack_into('<I', header, 108, struct.unpack_from('<I', header, 108)[0] | 0x400008)
    result = bytes(header) + blob[info['header']:end] + tail
    validate_family(result, {})
    return result


def native_split(blob, executable):
    """Use the installed native compiler for formats with distinct mip-tail rules."""
    with tempfile.TemporaryDirectory(prefix='gm-dds-') as temporary:
        root=Path(temporary);source=root/'texture.dds';source.write_bytes(complete_rgba_mips(blob))
        target=root/'compiled'
        result=subprocess.run([str(Path(executable).resolve()),str(source),'/p=PC','/streaming=1','/refresh',
                               '/targetroot='+str(target)],cwd=root,capture_output=True,
                              creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        if result.returncode or not (target/source.name).is_file():
            raise ValueError('Native DDS streaming compilation failed: '+result.stdout.decode(errors='replace'))
        members={p.name[len(source.name):]:p.read_bytes() for p in target.glob(source.name+'*') if p.is_file()}
        validate_family(members[''],{k:v for k,v in members.items() if k})
        return members


def generated_entries(entries, compiler=None):
    """Shared archive-writer adapter; preserve existing DDS families as supplied."""
    for name, blob in entries:
        if (name.lower().endswith('.dds') and not name.lower().startswith(('libs/ui/', 'textures/cubemaps/'))
                and blob.startswith(b'DDS ') and len(blob)>1024*1024):
            if not struct.unpack_from('<I', blob, 36)[0] & SPLIT:
                rc=compiler or os.environ.get('KCD2_RC')
                members=native_split(blob,rc) if rc else split_generated(blob)
                for suffix, data in members.items(): yield name+suffix, data
                continue
        yield name, blob


def checked_entries(entries):
    """Validate families across archive shards without retaining external pixels.

    Additive packages may contain only mip slices. A base present in this stream
    must include every slice it declares. Cubemaps have a separate converter.
    """
    families = {}; seen = set()
    for name, blob in entries:
        key = name.replace('\\', '/').lower()
        if key in seen: raise ValueError('Duplicate packaged asset '+key)
        seen.add(key)
        match = re.fullmatch(r'(.+\.dds)(\.(?:a|\d+a?))?', key)
        if match and not key.startswith(('libs/ui/', 'textures/cubemaps/')):
            family = families.setdefault(match[1], {})
            suffix = match[2] or ''
            family[suffix] = blob if suffix in ('', '.a') else range(len(blob))
        yield name, blob
    for name, parts in families.items():
        if '' not in parts: continue
        base = parts['']
        # Cube/volume headers are handled by lighting_cubemaps, never flatten them.
        if len(base) >= 128 and struct.unpack_from('<I', base, 112)[0] & 0xFE00: continue
        try: validate_family(base, {k:v for k,v in parts.items() if k})
        except ValueError as error: raise ValueError(name+': '+str(error)) from error
