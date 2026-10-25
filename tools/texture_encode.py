"""Store generated clothing textures in native block-compressed formats.

Macro colour bakes (`native_*_diff.dds`, `native_*_spec.dds`) hold v = rgb**2.2
and are sampled linearly; the clothing shader displays v**(1/2.2). Plain 8-bit
storage of v crushes dark channels ("brown leather turns red"), which is why
they were RGBA16F (8 bytes per texel). An sRGB texture is decoded to linear by
the GPU on read, so storing srgb_encode(v) returns the same v while spending its
8 bits perceptually: BC7_SRGB keeps the displayed error near 1-2/255 at one
byte per texel. Effect masks (`*_bgs.dds`) are numeric and use the native
BloodGrimeScratchMask preset (linear BC7).

The encoder is the official resource compiler from the KCD2 Modding Tools,
already required for shader builds. Every call works in its own temporary
folder (log files included), so it is safe in bake-pool worker processes.

GLUEMAPPER_CLOTHING_TEXTURES selects the storage: `bc7` (default) or `float`
(the previous RGBA16F macro bakes and uncompressed RGBA8 masks, kept for A/B).
"""
import functools
import os
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
    for root in found.get('mod_tools', []):
        candidate = Path(root) / 'Tools/rc/rc.exe'
        if candidate.is_file(): return candidate.resolve()
    return None


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


def _run(args, cwd):
    result = subprocess.run(args, cwd=cwd, capture_output=True, text=True, errors='replace',
                            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    if result.returncode:
        raise ValueError('KCD2 resource compiler failed (' + str(result.returncode) + '): '
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


def encode_colour(pixels, rc=None):
    return compile_rgba8(colour_bytes(pixels), COLOUR_PRESET, COLOUR_DXGI, rc)


def encode_mask(rgba, rc=None):
    return compile_rgba8(np.asarray(rgba, dtype=np.uint8), MASK_PRESET, MASK_DXGI, rc)


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
