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


@functools.lru_cache(maxsize=None)
def _half_lut():
    """Stored bytes for every half-float value: sRGB-encoded colour, and alpha."""
    values = np.nan_to_num(np.arange(65536, dtype=np.uint16).view(np.float16).astype(np.float64), nan=0.0)
    colour = np.round(srgb_encode(values) * 255).astype(np.uint8)
    alpha = np.round(np.clip(values, 0, 1) * 255).astype(np.uint8)
    return colour, alpha


def _half_bytes(level):
    """colour_bytes for a half-float level, by table lookup (identical, about 10x faster)."""
    colour, alpha = _half_lut()
    bits = np.ascontiguousarray(level, dtype=np.float16).view(np.uint16)
    out = np.empty(level.shape, np.uint8)
    out[..., :3] = colour[bits[..., :3]]
    out[..., 3] = alpha[bits[..., 3]]
    return out


def _box_half(level):
    """2x2 box of a float32 level, as Pillow's BOX resize computes it for even sizes.

    Pillow filters rows then columns, rounding each pass to float32; (a+b)*0.5 in
    float32 rounds exactly like the double-precision pass it performs.
    """
    rows = (level[:, 0::2] + level[:, 1::2]) * np.float32(.5)
    return (rows[0::2] + rows[1::2]) * np.float32(.5)


def colour_levels(pixels):
    """Box chain in linear light, each level rounded to half float as write_float_dds stores it,
    as sRGB-encoded uint8 RGBA levels down to the 4x4 tail."""
    level = np.asarray(pixels, dtype=np.float16)
    count = mip_count(level.shape[1], level.shape[0])
    levels = [_half_bytes(level)]
    for _ in range(count - 1):
        level = _box_half(level.astype(np.float32)).astype(np.float16)
        levels.append(_half_bytes(level))
    return levels


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


class Staged(tuple):
    """A texconv input written by stage():
    (source, target, srgb, width, height, count, average, cache key, cache folder)."""
    __slots__ = ()
    source = property(lambda self: self[0])
    target = property(lambda self: self[1])
    key = property(lambda self: self[7])

    def retarget(self, target):
        """The same input written to another file (an identical bake wanted at a second path)."""
        return Staged((self[0], str(target), *self[2:]))


class Staging(tuple):
    """Where workers stage texconv inputs: (folder, cache folder or None, encoder identity)."""
    __slots__ = ()
    directory = property(lambda self: self[0])
    cache = property(lambda self: self[1])
    tool = property(lambda self: self[2])


# Bump when the staged input layout or the finalized header changes.
CACHE_VERSION = b'gluemapper-bc7-texconv-1'


def _cached(cache, key):
    return Path(cache) / key[:2] / (key + '.dds')


def _publish(cache, key, blob):
    """Atomically store an encoded texture under its input key (identical inputs, identical bytes)."""
    import uuid
    path = _cached(cache, key)
    path.parent.mkdir(parents=True, exist_ok=True)
    pending = path.with_name(path.name + '.' + uuid.uuid4().hex + '.tmp')
    pending.write_bytes(blob)
    try:
        os.replace(pending, path)
    except PermissionError:
        # Character workers share this cache. On Windows another process reading
        # the same key blocks the replace; its file holds these same bytes.
        pending.unlink(missing_ok=True)
        if not path.is_file():
            raise


def _lookup(cache, key, width, height, srgb):
    try:
        blob = _cached(cache, key).read_bytes()
        check_compiled(blob[:-8] if blob.endswith(b'CExtCEnd') else blob, width, height, (99 if srgb else 98,))
        return blob
    except (OSError, ValueError):
        return None


def stage(levels, srgb, target, staging):
    """Write a uint8 RGBA chain as texconv input in `staging`; encode later with encode_staged.

    The input is a DX10 R8G8B8A8 DDS already in the output's colour space (sRGB
    in and out with -srgb; UNORM in and out otherwise), so texconv converts
    nothing, and it keeps a supplied chain instead of regenerating it.

    `staging` is a Staging, or a plain folder (no cache). With a cache, the key is
    the hash of the exact texconv input and encoder; a texture encoded before (for
    another person wearing the same garment, or an earlier build) is written to
    `target` now and None is returned.
    """
    import hashlib
    import uuid
    if not isinstance(staging, Staging): staging = Staging((str(staging), None, ''))
    height, width = levels[0].shape[:2]
    if not encodable(width, height):
        raise ValueError(f'Texture {width}x{height} cannot be block-compressed here')
    header = bytearray(148)
    header[:4] = b'DDS '
    struct.pack_into('<7I', header, 4, 124, 0x2100F, height, width, width * 4, 0, len(levels))
    struct.pack_into('<2I4s', header, 76, 32, 4, b'DX10')
    struct.pack_into('<I', header, 108, 0x401008)
    struct.pack_into('<5I', header, 128, 29 if srgb else 28, 3, 0, 1, 0)
    chunks = [bytes(header)] + [np.ascontiguousarray(level, dtype=np.uint8).data for level in levels]
    key = None
    if staging.cache:
        digest = hashlib.sha256(CACHE_VERSION + staging.tool.encode())
        for chunk in chunks: digest.update(chunk)
        key = digest.hexdigest()
        blob = _lookup(staging.cache, key, width, height, srgb)
        if blob is not None:
            Path(target).write_bytes(blob)
            return None
    source = Path(staging.directory) / (uuid.uuid4().hex + '.dds')
    with open(source, 'wb') as stream:
        for chunk in chunks: stream.write(chunk)
    # rc's average brightness: mean linear RGB of the top level.
    top = levels[0][..., :3]
    average = float(_srgb_byte_lut()[top].mean() if srgb else (top.astype(np.float64) / 255).mean())
    return Staged((str(source), str(target), srgb, width, height, len(levels), average, key, staging.cache))


@functools.lru_cache(maxsize=None)
def _srgb_byte_lut():
    return srgb_decode(np.arange(256, dtype=np.float64) / 255)


def _finalize(job, blob):
    source, target, srgb, width, height, count, average = job[:7]
    dxgi = 99 if srgb else 98
    check_compiled(blob, width, height, (dxgi,))
    if struct.unpack_from('<I', blob, 28)[0] != count:
        raise ValueError('texconv changed the mip chain')
    return cry_header(width, height, count, dxgi, average) + blob[148:] + b'CExtCEnd'


def _texconv_batch(jobs, executable, srgb, output):
    listing = Path(output) / 'inputs.txt'
    listing.write_text('\n'.join(job.source for job in jobs) + '\n', encoding='utf-8')
    _run([executable, '-f', 'BC7_UNORM_SRGB' if srgb else 'BC7_UNORM', *(['-srgb'] if srgb else []),
          '-y', '-nologo', '-o', str(output), '-flist', str(listing)], output, 'texconv')


def encode_staged(jobs, executable, write=True):
    """Encode staged textures with one texconv run per colour space; write each target.

    The chain length comes from each input (texconv keeps supplied mips). If a
    batch fails, its files are retried one at a time so the error names the
    texture. Inputs are removed once encoded. Returns {target: DDS bytes} when
    write is False.
    """
    results = {}
    # Identical inputs within the batch (the same garment on several people) are
    # encoded once; the copies take the representative's bytes. A copy whose
    # input an earlier batch already encoded and removed is read from the cache.
    copies, unique, first = {}, [], {}
    for job in jobs:
        if job.key and not Path(job.source).exists():
            blob = _lookup(job[8], job.key, job[3], job[4], job[2])
            if blob is None:
                raise ValueError('texconv input vanished for ' + job.target)
            if write: Path(job.target).write_bytes(blob)
            else: results[job.target] = blob
        elif job.key and job.key in first:
            copies.setdefault(first[job.key], []).append(job)
            if job.source != first[job.key].source: Path(job.source).unlink(missing_ok=True)
        else:
            if job.key: first[job.key] = job
            unique.append(job)
    with tempfile.TemporaryDirectory(prefix='gm-bc7-out-') as temporary:
        for srgb in (True, False):
            group = [job for job in unique if job[2] == srgb]
            if not group: continue
            output = Path(temporary) / ('srgb' if srgb else 'linear')
            output.mkdir()
            try:
                _texconv_batch(group, executable, srgb, output)
                failed = []
            except ValueError:
                failed = group
            for job in group:
                produced = output / Path(job.source).name
                try:
                    if job in failed or not produced.is_file():
                        single = output / 'single'; single.mkdir(exist_ok=True)
                        _texconv_batch([job], executable, srgb, single)
                        produced = single / Path(job.source).name
                    blob = _finalize(job, produced.read_bytes())
                except (ValueError, OSError) as error:
                    raise ValueError('texconv could not encode ' + job.target + ': ' + str(error)) from error
                produced.unlink()
                if job.key: _publish(job[8], job.key, blob)
                for each in [job, *copies.get(job, ())]:
                    if write: Path(each.target).write_bytes(blob)
                    else: results[each.target] = blob
                Path(job.source).unlink(missing_ok=True)
    return results


def compile_texconv(levels, srgb, executable):
    """Block-compress one uint8 RGBA mip chain with texconv; return rc-layout DDS bytes."""
    with tempfile.TemporaryDirectory(prefix='gm-bc7-') as staging:
        job = stage(levels, srgb, 'texture', staging)
        return encode_staged([job], executable, write=False)['texture']


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


def write_colour_dds(path, pixels, max_size=None, staging=None):
    """Write one macro colour bake in the configured storage.

    With `staging` (from a Batches owned by the caller), a texture that will be
    compressed is only prepared for texconv and the Staged job is returned; the
    caller's Batches writes `path`. Otherwise the file is written now.
    """
    from npc_effects import MAX_FLOAT_SIZE, write_float_dds
    max_size = MAX_FLOAT_SIZE if max_size is None else max_size
    pixels = np.asarray(pixels)
    if mode() == 'float' or not encodable(pixels.shape[1], pixels.shape[0]):
        return write_float_dds(path, pixels, max_size)
    level = capped(pixels, max_size)
    if not encodable(level.shape[1], level.shape[0]):
        return write_float_dds(path, pixels, max_size)
    if staging is not None:
        return stage(colour_levels(level), True, path, staging)
    Path(path).write_bytes(encode_colour(level))


def write_mask_dds(path, image, staging=None):
    """Write one byte-channel effect mask (PIL image) in the configured storage (see write_colour_dds)."""
    if mode() == 'float' or not encodable(*image.size):
        image.save(path)
        return None
    rgba = np.asarray(image.convert('RGBA'))
    if staging is not None:
        return stage(mask_levels(rgba), False, path, staging)
    Path(path).write_bytes(encode_mask(rgba))


# Measured per 2048px texture on the GPU: one texconv run per texture costs
# about 0.25 s of process start and device setup on top of ~0.43 s of encoding.
BATCH_SIZE = 8


class Batches:
    """Encode textures that pool workers staged, in texconv batches on one background thread.

    staging() is None unless texconv will encode (bc7 storage, texconv found and
    not overridden), in which case workers write straight to their targets as
    before. add() takes each worker's result; finish() encodes the rest and waits;
    abort() discards staged work. GPU encoding is serial (one texconv at a time),
    which is its throughput limit anyway, and overlaps the workers' CPU work.
    """
    def __init__(self, batch=BATCH_SIZE):
        self.batch, self.pending, self.futures = batch, [], []
        self.directory = self.executable = self.thread = None
        self.checked = False
        self.encoded = self.reused = 0

    def staging(self):
        if not self.checked:
            self.checked = True
            choice = (os.environ.get(ENCODER_SETTING) or 'auto').strip().lower()
            if mode() == 'bc7' and choice != 'rc':
                found = texconv_executable()
                if found: self.executable = str(found)
        if self.executable is None: return None
        if self.directory is None:
            self.directory = tempfile.mkdtemp(prefix='gm-bc7-batch-')
        return Staging((self.directory, str(encode_cache()), _tool_identity(self.executable)))

    def add(self, result):
        if isinstance(result, Staged):
            self.encoded += 1
            self.pending.append(result)
            if len(self.pending) >= self.batch: self._flush()
        else:
            self.reused += 1

    def _flush(self):
        from concurrent.futures import ThreadPoolExecutor
        if not self.pending: return
        if self.thread is None: self.thread = ThreadPoolExecutor(1)
        self.futures.append(self.thread.submit(encode_staged, self.pending, self.executable))
        self.pending = []

    def ticket(self):
        """A future completing once every texture added so far is written (or raising its error).

        Batches run in order on one thread, so a check queued behind them sees them all finished.
        """
        from concurrent.futures import Future
        self._flush()
        if not self.futures:
            done = Future(); done.set_result(None)
            return done
        return self.thread.submit(_first_error, list(self.futures))

    def finish(self):
        try:
            self._flush()
            futures, self.futures = self.futures, []
            for future in futures: future.result()
        except BaseException:
            self.abort()
            raise
        self._cleanup()

    def abort(self):
        for future in self.futures: future.cancel()
        for future in self.futures:
            try: future.result()
            except BaseException: pass
        self.futures, self.pending = [], []
        self._cleanup()

    def _cleanup(self):
        if self.thread is not None:
            self.thread.shutdown()
            self.thread = None
        if self.directory is not None:
            shutil.rmtree(self.directory, ignore_errors=True)
            self.directory = None


@functools.lru_cache(maxsize=None)
def _tool_identity(executable):
    """Encoder identity for cache keys: texconv's own bytes (a new release re-encodes)."""
    import hashlib
    return 'texconv:' + hashlib.sha256(Path(executable).read_bytes()).hexdigest()


_SESSION_CACHE = None


def encode_cache():
    """Folder of encoded textures keyed by their exact texconv input.

    The workspace build cache (GLUEMAPPER_BUILD_CACHE/bc7-textures) keeps them
    across builds; without one, or when the cache is being rebuilt, a temporary
    folder deduplicates within this process only.
    """
    global _SESSION_CACHE
    try:
        from setup_build_cache import root, forced
        folder = root()
        if folder is not None and not forced():
            folder = folder / 'bc7-textures'
            folder.mkdir(parents=True, exist_ok=True)
            return folder
    except ImportError:
        pass
    if _SESSION_CACHE is None:
        import atexit
        _SESSION_CACHE = Path(tempfile.mkdtemp(prefix='gm-bc7-cache-'))
        atexit.register(shutil.rmtree, _SESSION_CACHE, True)
    return _SESSION_CACHE


def _first_error(futures):
    for future in futures:
        future.result()
