"""Deflate the texture members of a finished package, as KCD2's own archives do.

Every package writer stores members uncompressed, which keeps each recipe rewrite a
plain byte copy. Retail KCD2 deflates 277k of its 304k texture members, so the
engine reads deflated textures, and the generated clothing bakes (half-float, 8 bytes
a pixel) deflate to about a sixth of their size. This pass runs once, on a finished
package, and rewrites only archives that hold stored texture members.

What stays stored: everything that is not a texture (audio, video, banks, navigation,
voxels, geometry and tables are small next to the textures), block-compressed textures
(they save about a fifth at a quarter of the speed), the `hlods/` textures (retail keeps
its hlod archives stored), and the lighting archives (their cubemaps are required stored). A member is deflated only when that saves at
least MIN_SAVING of it. The result is lossless: every member decompresses to its
original bytes and keeps its name, order, time and attributes; the CRC of every
deflated member is checked before an archive replaces the original. A second pass
finds nothing to do. GLUEMAPPER_PACKAGE_DEFLATE=0 turns the pass off.
"""
import copy
import json
import os
import re
import time
import zipfile
import zlib
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

VERSION = 1
LEVEL = 6               # within 1% of level 9 on the bakes, at a third of its time
MIN_SAVING = 0.05
TEXTURE = re.compile(r'\.dds(?:\.\d+a?|\.a)?$', re.I)
KEEP_STORED_ARCHIVES = re.compile(r'^gluemapper_lighting', re.I)
SETTING = 'GLUEMAPPER_PACKAGE_DEFLATE'
# One member (at most ~45 MB) and its compressed copy per thread; zlib and crc32
# release the GIL on large buffers, so threads compress archives in parallel.
WORKER_BYTES = 256 * 1024**2


def enabled():
    return os.environ.get(SETTING) != '0'


def _family(name):
    """The base .dds name of a texture member or of one of its streamed pieces (lower case, forward slashes)."""
    return re.sub(r'(\.dds)(?:\.\d+a?|\.a)$', r'\1', name.replace('\\', '/').lower())


def uncompressed_textures(package):
    """Base names of the package's textures stored in a pixel format, not a block format.

    Only those shrink much (generated half-float bakes to about a sixth). Block-compressed
    textures save about a fifth at a quarter of the speed, so they stay stored. A family's
    streamed pieces can live in another shard, so this reads every base header once.
    """
    from audit_maps import open_entry
    from texture_streaming import layout
    found = set()
    for path in sorted(Path(package).rglob('*.pak')):
        with zipfile.ZipFile(path) as archive:
            for member in archive.infolist():
                if not member.filename.lower().endswith('.dds') or member.file_size < 128: continue
                with open_entry(archive, member) as stream: head = stream.read(148)
                try: info = layout(head + b'\0' * (148 - len(head)))
                except ValueError: continue
                if info['block'] is None: found.add(_family(member.filename))
    return found


def eligible(archive_name, member, uncompressed):
    """True for a stored member of an uncompressed texture family this pass would deflate."""
    name = member.filename.replace('\\', '/')
    return bool(member.compress_type == zipfile.ZIP_STORED and member.file_size > 0 and TEXTURE.search(name)
                and _family(name) in uncompressed and not name.lower().startswith('hlods/')
                and not KEEP_STORED_ARCHIVES.match(archive_name))


def _receipt(package):
    from setup_campaign import RECEIPT
    path = Path(package) / RECEIPT
    return json.loads(path.read_text(encoding='utf-8')) if path.is_file() else {}


def candidates(package, uncompressed=None):
    """Archives holding an eligible member that this pass has not already compacted, largest first.

    An archive keeps stored textures that would not shrink, so the receipt records
    each compacted archive's digest; one a later step rewrote has a new digest.
    """
    package = Path(package)
    receipt = _receipt(package)
    files, compacted = receipt.get('files', {}), receipt.get('package_compaction', {}).get('compacted', {})
    pending = [path for path in sorted(package.rglob('*.pak'))
               if compacted.get(path.relative_to(package).as_posix(), object()) != files.get(path.relative_to(package).as_posix())]
    if not pending: return []
    if uncompressed is None: uncompressed = uncompressed_textures(package)
    found = []
    for path in pending:
        with zipfile.ZipFile(path) as archive:
            if any(eligible(path.name, member, uncompressed) for member in archive.infolist()):
                found.append(path)
    return sorted(found, key=lambda p: -p.stat().st_size)


def _zip64(archive):
    """Whether the source needed ZIP64, so a ZIP32 pak never silently becomes ZIP64."""
    members = archive.infolist()
    return len(members) >= 0xFFFF or any(
        m.header_offset >= 0xFFFFFFFF or m.file_size >= 0xFFFFFFFF or m.compress_size >= 0xFFFFFFFF for m in members)


def _worth_deflating(data, sample=256 * 1024, pieces=4):
    """Predict the saving from four slices spread over the member, instead of compressing it twice."""
    if len(data) <= sample * pieces:
        slices = [data]
    else:
        step = (len(data) - sample) // (pieces - 1)
        slices = [data[i * step:i * step + sample] for i in range(pieces)]
    raw = packed = 0
    for piece in slices:
        compressor = zlib.compressobj(LEVEL, zlib.DEFLATED, -15)
        packed += len(compressor.compress(piece)) + len(compressor.flush()); raw += len(piece)
    return packed <= raw * (1 - MIN_SAVING)


def compact_archive(path, uncompressed, cancelled=lambda: False):
    """Rewrite one archive with its eligible members deflated; returns (bytes before, bytes after, members deflated)."""
    from audit_maps import copy_member, open_entry
    path = Path(path)
    pending = path.with_name(path.name + '.deflate')
    before, deflated = path.stat().st_size, []
    try:
        with zipfile.ZipFile(path) as source, \
             zipfile.ZipFile(pending, 'x', zipfile.ZIP_STORED, allowZip64=_zip64(source)) as out:
            out.comment = source.comment
            for number, member in enumerate(source.infolist()):
                if number % 200 == 0 and cancelled():
                    raise InterruptedError('Cancelled while compressing package textures')
                if not eligible(path.name, member, uncompressed):
                    copy_member(source, member, out); continue
                with open_entry(source, member) as stream:
                    data = stream.read()       # the reader checks the stored CRC
                if not _worth_deflating(data):
                    copy_member(source, member, out); continue
                info = copy.copy(member)
                out.writestr(info, data, compress_type=zipfile.ZIP_DEFLATED, compresslevel=LEVEL)
                deflated.append(member.filename)
        with zipfile.ZipFile(pending) as check, zipfile.ZipFile(path) as source:
            if [m.filename for m in check.infolist()] != [m.filename for m in source.infolist()]:
                raise ValueError('Compressed archive changed its member list: ' + path.name)
            originals = {m.filename: m for m in source.infolist()}
            for name in deflated:
                written = check.getinfo(name)
                if (written.CRC, written.file_size) != (originals[name].CRC, originals[name].file_size):
                    raise ValueError('Compressed member changed: ' + name)
                with check.open(written) as stream:      # decompresses and checks the CRC
                    while stream.read(8 << 20): pass
        os.replace(pending, path)                        # replaces the entry, never writes through a hard link
    except BaseException:
        pending.unlink(missing_ok=True)
        raise
    return before, path.stat().st_size, len(deflated)


def compact_package(package, notify=lambda *args: None, cancelled=lambda: False):
    """Deflate a staged package's texture members and record the new archive digests in its receipt.

    Runs on a private copy (setup_resume.update_private_package): archives are
    replaced, never edited in place, so hard links to the verified package stay as they were.
    """
    from bounded_pool import worker_count
    from setup_campaign import RECEIPT, digests
    package = Path(package)
    started = time.perf_counter()
    notify('Compress package textures', 0, 0, 'Finding uncompressed textures')
    uncompressed = uncompressed_textures(package)
    archives = candidates(package, uncompressed)
    if not archives:
        return dict(version=VERSION, archives=0)
    workers = worker_count(len(archives), WORKER_BYTES, 'GLUEMAPPER_DEFLATE_WORKERS')
    done, totals = 0, [0, 0, 0]
    notify('Compress package textures', 0, len(archives), f'{len(archives)} archives in {workers} threads')
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = [pool.submit(compact_archive, path, uncompressed, cancelled) for path in archives]
        try:
            for future in futures:
                before, after, members = future.result()
                totals[0] += before; totals[1] += after; totals[2] += members; done += 1
                notify('Compress package textures', done, len(archives),
                       f'{done} of {len(archives)} archives, {totals[0] / 1e9:.1f} -> {totals[1] / 1e9:.1f} GB')
        finally:
            for future in futures: future.cancel()
    if cancelled(): raise InterruptedError('Cancelled after compressing package textures')
    receipt_path = package / RECEIPT
    receipt = json.loads(receipt_path.read_text(encoding='utf-8'))
    hashed = {path.relative_to(package).as_posix(): value for path, value in digests(archives).items()}
    receipt['files'].update(hashed)
    compacted = {name: value for name, value in receipt.get('package_compaction', {}).get('compacted', {}).items()
                 if receipt['files'].get(name) == value}
    compacted.update(hashed)
    report = dict(version=VERSION, level=LEVEL, archives=len(archives), members=totals[2],
                  bytes_before=totals[0], bytes_after=totals[1], seconds=round(time.perf_counter() - started, 1),
                  runtime_verified=False, compacted=compacted)
    receipt['package_compaction'] = report
    receipt_path.unlink()                                # the staged receipt is a hard link to the original
    receipt_path.write_text(json.dumps(receipt, indent=2), encoding='utf-8')
    return report
