"""Re-encode packaged clothing textures of a saved build without re-baking them.

Saved packages store macro colour bakes (`native_*_diff.dds`, `native_*_spec.dds`)
as RGBA16F and effect masks (`native_*_bgs.dds`) as uncompressed RGBA8, split
into Cry streaming families that may cross the shards of one archive group
(gm_person_<id>.pak, gm_person_<id>_01.pak, ...; gluemapper_containers_NN.pak).
Each family's top mip is decoded and compiled to the format a fresh build now
writes (texture_encode), then split exactly as the archive writers split it.

Archives are rewritten to new files that replace the old ones; an existing
archive is never modified in place (installs may hard-link package files).
Families that are already block-compressed, or too small to compress, are left
alone, so the step is idempotent.
"""
from collections import defaultdict
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor, as_completed
import io
import os
import re
import struct
import tempfile
import time
import zipfile
from pathlib import Path

import numpy as np

VERSION = 1
RECEIPT_KEY = 'clothing_texture_encoding'
FAMILY = re.compile(r'(.*/native_[^/]*_(diff|spec|bgs)\.dds)(\.\d+)?', re.I)
GROUPS = (re.compile(r'(gm_person_[0-9a-f]+)(?:_\d+)?\.pak', re.I),
          re.compile(r'(gluemapper_containers)_\d+\.pak', re.I))
# Asset shards are written below these sizes (actor 900 MiB, containers 1 GiB).
SHARD_LIMIT = 1024 ** 3


def archive_groups(package):
    """{group: [Data/... shard paths in name order]} for every clothing archive group."""
    groups = defaultdict(list)
    for path in sorted((Path(package) / 'Data').glob('*.pak')):
        for pattern in GROUPS:
            match = pattern.fullmatch(path.name)
            if match: groups[match[1].lower()].append(path)
    return dict(groups)


def join_family(base, members):
    """The complete DDS file a split family was cut from (Cry streaming order)."""
    from texture_streaming import layout
    info = layout(base)
    body = base[info['header']:]
    if body.endswith(b'CExtCEnd'): body = body[:-8]
    numbers = sorted((int(k[1:]) for k in members), reverse=True)
    if numbers and sorted(numbers) != list(range(1, max(numbers) + 1)):
        raise ValueError('Incomplete split DDS mip family')
    return base[:info['header']] + b''.join(members['.' + str(n)] for n in numbers) + body


def classify(base):
    """'colour' for RGBA16F, 'mask' for 32-bit uncompressed, else None (already converted)."""
    if len(base) < 128 or base[:4] != b'DDS ': return None
    if base[84:88] == b'DX10':
        return 'colour' if len(base) >= 148 and struct.unpack_from('<I', base, 128)[0] == 10 else None
    flags, fourcc, bits = struct.unpack_from('<I4sI', base, 80)
    return 'mask' if flags & 0x40 and not flags & 4 and bits == 32 else None


def decode_float(blob):
    """Top mip of a joined RGBA16F DDS as float32 H x W x 4."""
    height, width = struct.unpack_from('<II', blob, 12)
    count = width * height * 4
    return np.frombuffer(blob, '<f2', count, 148).reshape(height, width, 4).astype(np.float32)


def decode_mask(blob):
    from PIL import Image
    image = Image.open(io.BytesIO(blob))
    image.load()
    return np.asarray(image.convert('RGBA'))


def encode_family(job):
    """Worker: read one family from its shards, encode it, write members to a folder.

    Returns (name, kind, {suffix: file}) or (name, None, reason) when skipped.
    """
    import texture_encode
    from texture_streaming import generated_entries
    name, kind, locations, rc, output = job
    parts = {}
    for suffix, shard in locations.items():
        with zipfile.ZipFile(shard) as archive:
            parts[suffix] = archive.read(name + suffix)
    blob = join_family(parts.pop(''), parts)
    height, width = struct.unpack_from('<II', blob, 12)
    if not texture_encode.encodable(width, height):
        return name, None, 'small'
    if kind == 'colour':
        encoded = texture_encode.encode_colour(decode_float(blob), rc)
    else:
        encoded = texture_encode.encode_mask(decode_mask(blob), rc)
    files = {}
    folder = Path(output)
    folder.mkdir(parents=True, exist_ok=True)
    for member, data in generated_entries([(name, encoded)]):
        suffix = member[len(name):]
        path = folder / ('m' + suffix.replace('.', '_'))
        path.write_bytes(data)
        files[suffix] = str(path)
    return name, kind, files


def scan(shards):
    """Index a group: {member name: shard}, convertible families {base: kind}, and counts."""
    import texture_encode
    owners, families, already, small = {}, {}, 0, 0
    for shard in shards:
        with zipfile.ZipFile(shard) as archive:
            for info in archive.infolist():
                if info.filename in owners:
                    raise ValueError('Duplicate clothing archive member: ' + info.filename)
                owners[info.filename] = shard
                match = FAMILY.fullmatch(info.filename)
                if match and match[3] is None:
                    with archive.open(info) as stream:
                        header = stream.read(148)
                    kind = classify(header)
                    if kind and kind == ('mask' if match[2].lower() == 'bgs' else 'colour'):
                        height, width = struct.unpack_from('<II', header, 12)
                        if texture_encode.encodable(width, height): families[info.filename] = kind
                        else: small += 1
                    elif kind is None:
                        already += 1
    return owners, families, already, small


def rewrite_group(shards, owners, converted, notify=lambda *a: None):
    """Write each shard anew with converted families; return {shard: pending path}.

    A new member goes to the shard of the old member with the same suffix (or of
    the base), so a shard never grows by more than a mask header.
    """
    from texture_streaming import checked_entries
    placement = defaultdict(dict)        # shard -> {old member name: [(new name, file)]}
    removed = set()
    for base, files in converted.items():
        old = [n for n in owners if n == base or (n.startswith(base + '.') and n[len(base) + 1:].isdigit())]
        removed.update(old)
        for suffix, path in files.items():
            anchor = base + suffix if base + suffix in owners else base
            placement[owners[anchor]].setdefault(anchor, []).append((base + suffix, path))
    pending = {}
    try:
        for shard in shards:
            target = shard.with_name(shard.name + '.bc7-pending')
            pending[shard] = target
            with zipfile.ZipFile(shard) as source, \
                    zipfile.ZipFile(target, 'x', zipfile.ZIP_STORED, allowZip64=False) as out:
                for info in source.infolist():
                    if info.filename not in removed:
                        item = zipfile.ZipInfo(info.filename, info.date_time)
                        item.create_system, item.external_attr = info.create_system, info.external_attr
                        with source.open(info) as src, out.open(item, 'w') as dst:
                            while chunk := src.read(1 << 20): dst.write(chunk)
                    for name, path in placement[shard].get(info.filename, ()):
                        item = zipfile.ZipInfo(name, info.date_time)
                        item.create_system = info.create_system
                        out.writestr(item, Path(path).read_bytes())
            with zipfile.ZipFile(target) as check:
                if check.testzip() is not None:
                    raise ValueError('Clothing archive verification failed: ' + shard.name)
            if target.stat().st_size > max(shard.stat().st_size, SHARD_LIMIT):
                raise ValueError('Re-encoded clothing archive grew past its shard limit: ' + shard.name)
        # Families may cross shards; validate every family across the new group.
        def entries():
            for target in pending.values():
                with zipfile.ZipFile(target) as archive:
                    for info in archive.infolist():
                        yield info.filename, archive.read(info)
        for _ in checked_entries(entries()): pass
    except BaseException:
        for target in pending.values(): target.unlink(missing_ok=True)
        raise
    return pending


def upgrade(package, target_or_mod_tools=None, notify=lambda *a: None, cancelled=lambda: False, workers=None):
    """Re-encode float/RGBA8 clothing textures of a saved package; (files, report)."""
    import texture_encode
    from bounded_pool import worker_count
    from setup_campaign import digest
    package = Path(package).resolve()
    selected = texture_encode.mode()
    # Colour is BC7_SRGB unless rc's 'auto' output picks BC7 (e.g. near-black specular).
    report = dict(version=VERSION, mode=selected, colour_format='BC7_SRGB', mask_format='BC7',
                  converted=dict(colour=0, mask=0), skipped_small=0, already_compressed=0,
                  archives=0, bytes_before=0, bytes_after=0, runtime_verified=False)
    if selected == 'float':
        return {}, report
    groups = archive_groups(package)
    scanned = {}
    for group, shards in groups.items():
        owners, families, already, small = scan(shards)
        report['already_compressed'] += already
        report['skipped_small'] += small
        if families: scanned[group] = (shards, owners, families)
    total = sum(len(f) for _, _, f in scanned.values())
    if not total:
        return {}, report
    rc = str(_mod_tools_rc(target_or_mod_tools))
    changed = {}
    started = time.monotonic()
    # rc's BC7 compressor already uses every core (about 4 s per 2048px texture
    # whatever the worker count); a few workers only overlap decoding and I/O.
    count = workers or worker_count(min(total, 4), 512 * 1024 ** 2, 'GLUEMAPPER_BAKE_WORKERS')
    with tempfile.TemporaryDirectory(prefix='clothing-bc7-', dir=package.parent) as temporary, \
            (ProcessPoolExecutor(max_workers=count) if count > 1 else ThreadPoolExecutor(1)) as pool, \
            ThreadPoolExecutor(max_workers=2) as writers:
        work = Path(temporary)
        remaining = {g: len(f) for g, (_, _, f) in scanned.items()}
        results = {g: {} for g in scanned}
        futures, rewrites = {}, {}
        index = 0
        for group, (shards, owners, families) in scanned.items():
            for base, kind in families.items():
                locations = {n[len(base):]: str(owners[n]) for n in owners
                             if n == base or (n.startswith(base + '.') and n[len(base) + 1:].isdigit())}
                job = (base, kind, locations, rc, str(work / f'{index:06d}'))
                futures[pool.submit(encode_family, job)] = group
                index += 1
        done = 0
        try:
            for future in as_completed(futures):
                group = futures[future]
                name, kind, files = future.result()
                if kind is None: report['skipped_small'] += 1
                else:
                    results[group][name] = files
                    report['converted'][kind] += 1
                done += 1
                notify('Compress saved clothing textures', done, total, name)
                if cancelled(): raise InterruptedError('Cancelled during clothing texture compression')
                remaining[group] -= 1
                if not remaining[group] and results[group]:
                    shards, owners, _ = scanned[group]
                    rewrites[group] = writers.submit(rewrite_group, shards, owners, results[group])
            pendings = {g: f.result() for g, f in rewrites.items()}
        except BaseException:
            for future in futures: future.cancel()
            for future in rewrites.values():
                try:
                    for target in future.result().values(): target.unlink(missing_ok=True)
                except Exception: pass
            raise
        for group, pending in pendings.items():
            for shard, target in pending.items():
                report['bytes_before'] += shard.stat().st_size
                report['bytes_after'] += target.stat().st_size
                target.replace(shard)
                relative = shard.relative_to(package).as_posix()
                changed[relative] = digest(shard)
    report['archives'] = len(changed)
    report['seconds'] = round(time.monotonic() - started, 1)
    return changed, report


def _mod_tools_rc(target_or_mod_tools):
    """Accept the mod-tools folder, rc.exe, or the KCD2 game folder (as finalize passes)."""
    import texture_encode
    if target_or_mod_tools is not None:
        path = Path(target_or_mod_tools)
        if path.suffix.lower() == '.exe' or (path / 'Tools/rc/rc.exe').is_file():
            return texture_encode.rc_executable(path)
        if not os.environ.get('KCD2_MOD_TOOLS'):
            from setup_shaders import tool_root
            try:
                return texture_encode.rc_executable(tool_root(path))
            except ValueError:
                pass
    return texture_encode.rc_executable()
