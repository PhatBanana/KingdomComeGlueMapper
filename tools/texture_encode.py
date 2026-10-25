"""Store generated clothing textures in native block-compressed formats.

Macro colour bakes (`native_*_diff.dds`, `native_*_spec.dds`) hold v = rgb**2.2
and are sampled linearly; the clothing shader displays v**(1/2.2). Plain 8-bit
storage of v crushes dark channels ("brown leather turns red"), which is why
they were RGBA16F (8 bytes per texel). An sRGB texture is decoded to linear by
the GPU on read, so storing srgb_encode(v) returns the same v while spending its
8 bits perceptually: BC7_SRGB keeps the displayed error near 1-2/255 at one
byte per texel. Effect masks (`*_bgs.dds`) are numeric and use the native
BloodGrimeScratchMask preset (linear BC7).

Two encoders write the same layout (DX10 BC7, mips to the 4x4 tail, rc's Cry
header fields). Microsoft's texconv (DirectXTex) is preferred: about 1 s per
2048px texture on the GPU, with mips filtered here exactly as the float bakes
were (box in linear light) and its input bytes stored unconverted. The KCD2
Modding Tools' resource compiler (rc.exe, already required for shader builds)
is the fallback, at about 4 s per texture. GLUEMAPPER_TEXTURE_ENCODER selects
`auto` (default), `texconv` or `rc`; GLUEMAPPER_TEXCONV names texconv.exe.
Nothing is downloaded. Every call works in its own temporary folder, so it is
safe in bake-pool worker processes.

GLUEMAPPER_CLOTHING_TEXTURES selects the storage: `bc7` (default) or `float`
(the previous RGBA16F macro bakes and uncompressed RGBA8 masks, kept for A/B).
"""
import functools
import os
import shutil
import sys
import struct
import subprocess
import tempfile
from pathlib import Path

import numpy as np

SETTING = 'GLUEMAPPER_CLOTHING_TEXTURES'
MODES = ('bc7', 'float')
DEFAULT_MODE = 'bc7'
COLOUR_PRESET = 'AlbedoWithOpacity'      # BC7, sRGB, alpha kept (native clothing colour)
MASK_PRESET = 'BloodGrimeScratchMask'    # BC7, linear (native _bgs masks)
# The colour preset's output colour space is 'auto': rc normally writes
# BC7_UNORM_SRGB, but may choose BC7_UNORM for content that is better linear
# (e.g. nearly black specular). Either way the GPU returns the same linear v.
COLOUR_DXGI = (99, 98)                   # BC7_UNORM_SRGB, BC7_UNORM
MASK_DXGI = (98,)                        # BC7_UNORM
ENCODER_SETTING = 'GLUEMAPPER_TEXTURE_ENCODER'
ENCODERS = ('auto', 'texconv', 'rc')
TEXCONV_SETTING = 'GLUEMAPPER_TEXCONV'
SRGB_READ = 0x800                        # Cry image flag rc sets on sRGB colour textures
# Below this, a texture is a uniform placeholder (4x4 fallbacks); compressing it
# saves nothing and would make tiny self-test bakes depend on the mod tools.
MIN_ENCODED_SIZE = 64


def mode():
    value = (os.environ.get(SETTING) or DEFAULT_MODE).strip().lower()
    if value not in MODES:
        raise ValueError(f'{SETTING} must be one of {", ".join(MODES)}; got {value!r}')
    return value


def encodable(width, height):
    """BC7 via rc: power-of-two sides (the presets' powof2=1) of useful size."""
    return all(n >= MIN_ENCODED_SIZE and not n & (n - 1) for n in (width, height))


def srgb_encode(x):
    x = np.clip(np.asarray(x, dtype=np.float64), 0, 1)
    return np.where(x <= .0031308, x * 12.92, 1.055 * x ** (1 / 2.4) - .055)


def srgb_decode(x):
    x = np.asarray(x, dtype=np.float64)
    return np.where(x <= .04045, x / 12.92, ((x + .055) / 1.055) ** 2.4)


def colour_bytes(pixels):
    """Linear float RGBA (H x W x 4) -> sRGB-encoded RGB + linear alpha, uint8."""
    pixels = np.asarray(pixels, dtype=np.float64)
    if pixels.ndim != 3 or pixels.shape[2] != 4 or not np.isfinite(pixels).all():
        raise ValueError('Expected finite H x W x RGBA pixels')
    rgb = np.round(srgb_encode(pixels[..., :3]) * 255)
    alpha = np.round(np.clip(pixels[..., 3:], 0, 1) * 255)
    return np.concatenate([rgb, alpha], axis=-1).astype(np.uint8)


def capped(pixels, max_size):
    """The first level of write_float_dds's box-filtered chain that fits max_size."""
    from PIL import Image
    level = np.asarray(pixels, dtype=np.float32)
    while max(level.shape[:2]) > max_size and min(level.shape[:2]) > 1:
        h, w = max(1, level.shape[0] // 2), max(1, level.shape[1] // 2)
        level = np.stack([np.asarray(Image.fromarray(np.ascontiguousarray(level[..., c])).resize(
            (w, h), Image.Resampling.BOX)) for c in range(level.shape[2])], axis=-1)
        level = level.astype(np.float16).astype(np.float32)   # as write_float_dds stores each level
    return level


@functools.lru_cache(maxsize=None)
def _discovered_rc():
    from steam_installations import discover
    found, _ = discover()
    # Steam-registered Modding Tools, else beside the game in any Steam library.
    roots = [Path(p) for p in found.get('mod_tools', [])]
    roots += [Path(p).parent / 'KCD2Mod' for p in found.get('kcd2', [])]
    for root in roots:
        candidate = root / 'Tools/rc/rc.exe'
        if candidate.is_file(): return candidate.resolve()
    return None


def texconv_executable():
    """texconv.exe from GLUEMAPPER_TEXCONV, PATH, the repository or the frozen app folder; else None."""
    explicit = os.environ.get(TEXCONV_SETTING)
    if explicit:
        path = Path(explicit)
        path = path if path.suffix.lower() == '.exe' else path / 'texconv.exe'
        if not path.is_file():
            raise ValueError(f'{TEXCONV_SETTING} does not name texconv.exe: {path}')
        return path.resolve()
    found = shutil.which('texconv')
    if found: return Path(found).resolve()
    here = Path(__file__).resolve().parent
    for candidate in (here.parent / 'third_party/texconv/texconv.exe', here / 'texconv.exe',
                      Path(sys.executable).resolve().parent / 'texconv.exe'):
        if candidate.is_file(): return candidate.resolve()
    return None


def encoder(mod_tools=None):
    """('texconv', path) or ('rc', path) per GLUEMAPPER_TEXTURE_ENCODER (auto prefers texconv)."""
    choice = (os.environ.get(ENCODER_SETTING) or 'auto').strip().lower()
    if choice not in ENCODERS:
        raise ValueError(f'{ENCODER_SETTING} must be one of {", ".join(ENCODERS)}; got {choice!r}')
    if choice != 'rc':
        found = texconv_executable()
        if found: return 'texconv', str(found)
        if choice == 'texconv':
            raise ValueError(f'texconv.exe not found; set {TEXCONV_SETTING} to its path, '
                             f'or {ENCODER_SETTING}=rc to use the KCD2 Modding Tools.')
    return 'rc', str(rc_executable(mod_tools))


def rc_executable(mod_tools=None):
    """rc.exe from an explicit mod-tools folder (or rc.exe path), KCD2_MOD_TOOLS, or Steam."""
    explicit = mod_tools or os.environ.get('KCD2_MOD_TOOLS')
    if explicit:
        explicit = Path(explicit)
        candidate = explicit if explicit.suffix.lower() == '.exe' else explicit / 'Tools/rc/rc.exe'
        if candidate.is_file(): return candidate.resolve()
        raise ValueError('KCD2 resource compiler not found at ' + str(candidate) +
                         f'. Install the official KCD2 Modding Tools, or set {SETTING}=float.')
    found = _discovered_rc()
    if found is None:
        raise ValueError('Compressed clothing textures need the official KCD2 Modding Tools '
                         '(Tools/rc/rc.exe). Install them through Steam and select their folder in setup, '
                         f'or set {SETTING}=float.')
    return found


def _run(args, cwd, tool='KCD2 resource compiler'):
    result = subprocess.run(args, cwd=cwd, capture_output=True, text=True, errors='replace',
                            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    if result.returncode:
        raise ValueError(tool + ' failed (' + str(result.returncode) + '): '
                         + (result.stdout + result.stderr)[-1500:])


def compile_rgba8(rgba, preset, expected_dxgi, rc=None):
    """Compile H x W x 4 uint8 pixels with an rc preset; return the unsplit DDS bytes.

    A command-line /preset loses to rc's automatic choice for images with alpha
    (BC3), so the preset is saved into the TIF first. /reduce=0 keeps the full
    PC resolution, which these presets otherwise halve.
    """
    from PIL import Image
    rgba = np.asarray(rgba)
    if rgba.dtype != np.uint8 or rgba.ndim != 3 or rgba.shape[2] != 4:
        raise ValueError('Expected H x W x RGBA uint8 pixels')
    height, width = rgba.shape[:2]
    if not encodable(width, height):
        raise ValueError(f'Texture {width}x{height} cannot be block-compressed here')
    executable = str(rc_executable(rc))
    with tempfile.TemporaryDirectory(prefix='gm-bc7-') as temporary:
        root = Path(temporary)
        tif = root / 'texture.tif'
        Image.fromarray(np.ascontiguousarray(rgba), 'RGBA').save(tif)
        common = ['/logprefix=' + str(root) + os.sep, '/userdialog=0']
        _run([executable, str(tif), '/savepreset=' + preset, *common], root)
        _run([executable, str(tif), '/p=PC', '/reduce=0', '/refresh', '/streaming=0', '/threads=1',
              '/targetroot=' + str(root / 'out'), *common], root)
        produced = root / 'out' / 'texture.dds'
        if not produced.is_file():
            raise ValueError('KCD2 resource compiler produced no texture')
        stray = [p.name for p in (root / 'out').iterdir() if p.name != produced.name]
        if stray: raise ValueError('Unexpected resource compiler outputs: ' + ', '.join(stray))
        blob = produced.read_bytes()
    check_compiled(blob, width, height, expected_dxgi)
    return blob


def check_compiled(blob, width, height, dxgi):
    """dxgi: the DXGI formats the preset may produce."""
    from texture_streaming import layout
    info = layout(blob)
    if blob[84:88] != b'DX10' or struct.unpack_from('<I', blob, 128)[0] not in dxgi:
        raise ValueError('Resource compiler wrote an unexpected texture format')
    if (info['width'], info['height']) != (width, height):
        raise ValueError('Resource compiler changed the texture size')
    body = len(blob) - info['header'] - (8 if blob.endswith(b'CExtCEnd') else 0)
    if body != sum(info['sizes']):
        raise ValueError('Resource compiler wrote an incomplete mip chain')


def mip_count(width, height):
    """rc's chain: down to the 4x4 block tail (what split_generated keeps)."""
    return max(1, min(width, height).bit_length() - 2)


def colour_levels(pixels):
    """Box chain in linear light, each level rounded to half float as write_float_dds stores it."""
    from PIL import Image
    level = np.asarray(pixels, dtype=np.float16).astype(np.float32)
    levels = [level]
    for _ in range(mip_count(level.shape[1], level.shape[0]) - 1):
        h, w = max(1, level.shape[0] // 2), max(1, level.shape[1] // 2)
        level = np.stack([np.asarray(Image.fromarray(np.ascontiguousarray(level[..., c])).resize(
            (w, h), Image.Resampling.BOX)) for c in range(4)], axis=-1).astype(np.float16).astype(np.float32)
        levels.append(level)
    return [colour_bytes(level) for level in levels]


def mask_levels(rgba):
    """Byte-channel box chain, as complete_rgba_mips filtered the uncompressed masks."""
    from PIL import Image
    image = Image.fromarray(np.ascontiguousarray(rgba, dtype=np.uint8), 'RGBA')
    levels = [np.asarray(image)]
    for _ in range(mip_count(*image.size) - 1):
        w, h = max(1, image.size[0] // 2), max(1, image.size[1] // 2)
        image = Image.merge('RGBA', tuple(c.resize((w, h), Image.Resampling.BOX) for c in image.split()))
        levels.append(np.asarray(image))
    return levels


def cry_header(width, height, count, dxgi, average):
    """The DDS header rc writes: DX10, Cry flags, average brightness and colour range."""
    header = bytearray(148)
    header[:4] = b'DDS '
    struct.pack_into('<7I', header, 4, 124, 0x21007, height, width, 0, 0, count)
    struct.pack_into('<I', header, 36, SRGB_READ if dxgi == 99 else 0)
    struct.pack_into('<f', header, 40, average)
    struct.pack_into('<4f', header, 60, 1, 1, 1, 1)          # max colour; min colour stays 0
    struct.pack_into('<2I4s', header, 76, 32, 4, b'DX10')
    struct.pack_into('<I', header, 108, 0x401008)
    struct.pack_into('<I', header, 124, 0x43525946)          # 'FYRC'
    struct.pack_into('<5I', header, 128, dxgi, 3, 0, 1, 0)
    return bytes(header)


def compile_texconv(levels, srgb, executable):
    """Block-compress a supplied uint8 RGBA mip chain with texconv; return rc-layout DDS bytes.

    The input is a DX10 R8G8B8A8 DDS already in the output's colour space (sRGB
    in and out with -srgb; UNORM in and out otherwise), so texconv converts
    nothing, and it keeps a supplied chain instead of regenerating it.
    """
    height, width = levels[0].shape[:2]
    if not encodable(width, height):
        raise ValueError(f'Texture {width}x{height} cannot be block-compressed here')
    count = len(levels)
    source_format, target, dxgi = (29, 'BC7_UNORM_SRGB', 99) if srgb else (28, 'BC7_UNORM', 98)
    with tempfile.TemporaryDirectory(prefix='gm-bc7-') as temporary:
        root = Path(temporary)
        source = root / 'texture.dds'
        header = bytearray(148)
        header[:4] = b'DDS '
        struct.pack_into('<7I', header, 4, 124, 0x2100F, height, width, width * 4, 0, count)
        struct.pack_into('<2I4s', header, 76, 32, 4, b'DX10')
        struct.pack_into('<I', header, 108, 0x401008)
        struct.pack_into('<5I', header, 128, source_format, 3, 0, 1, 0)
        source.write_bytes(bytes(header) + b''.join(
            np.ascontiguousarray(level, dtype=np.uint8).tobytes() for level in levels))
        (root / 'out').mkdir()
        _run([executable, '-f', target, *(['-srgb'] if srgb else []), '-m', str(count), '-y', '-nologo',
              '-o', str(root / 'out'), str(source)], root, 'texconv')
        produced = root / 'out' / 'texture.dds'
        if not produced.is_file(): raise ValueError('texconv produced no texture')
        blob = produced.read_bytes()
    check_compiled(blob, width, height, (dxgi,))
    if struct.unpack_from('<I', blob, 28)[0] != count:
        raise ValueError('texconv changed the mip chain')
    top = levels[0][..., :3].astype(np.float64) / 255
    average = float((srgb_decode(top) if srgb else top).mean())
    return cry_header(width, height, count, dxgi, average) + blob[148:] + b'CExtCEnd'


def encode_colour(pixels, tool=None):
    """Linear float RGBA -> BC7 (sRGB) DDS bytes. tool: an encoder() result."""
    kind, path = tool or encoder()
    if kind == 'texconv':
        return compile_texconv(colour_levels(pixels), True, path)
    return compile_rgba8(colour_bytes(pixels), COLOUR_PRESET, COLOUR_DXGI, path)


def encode_mask(rgba, tool=None):
    """uint8 RGBA mask -> linear BC7 DDS bytes. tool: an encoder() result."""
    rgba = np.asarray(rgba, dtype=np.uint8)
    kind, path = tool or encoder()
    if kind == 'texconv':
        return compile_texconv(mask_levels(rgba), False, path)
    return compile_rgba8(rgba, MASK_PRESET, MASK_DXGI, path)


def write_colour_dds(path, pixels, max_size=None):
    """Write one macro colour bake in the configured storage."""
    from npc_effects import MAX_FLOAT_SIZE, write_float_dds
    max_size = MAX_FLOAT_SIZE if max_size is None else max_size
    pixels = np.asarray(pixels)
    if mode() == 'float' or not encodable(pixels.shape[1], pixels.shape[0]):
        return write_float_dds(path, pixels, max_size)
    level = capped(pixels, max_size)
    if not encodable(level.shape[1], level.shape[0]):
        return write_float_dds(path, pixels, max_size)
    Path(path).write_bytes(encode_colour(level))


def write_mask_dds(path, image):
    """Write one byte-channel effect mask (PIL image) in the configured storage."""
    if mode() == 'float' or not encodable(*image.size):
        image.save(path)
        return
    Path(path).write_bytes(encode_mask(np.asarray(image.convert('RGBA'))))
