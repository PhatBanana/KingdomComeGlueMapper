"""Share parsed ZIP directories between the archive opens of one build.

Combine opens archives about 6,000 times and rebuilds the same central
directories each time: half a second per open for the 148,000-entry KCD1
level archive, minutes a build in all. A read-mode directory is kept by file
identity, size and modification time, the digest memo's contract, and handed
to later readers of the same unchanged file. Writers keep the stdlib path, and
a ZipInfo given to a writer is copied first, so an entry shared between
readers is never edited through it.
"""
import copy
import os
import threading
import time
import zipfile
from collections import OrderedDict

_STDLIB = zipfile.ZipFile
_DIRECTORIES = OrderedDict()
_LOCK = threading.Lock()
_ENTRY_LIMIT = 600_000  # a few hundred MB of ZipInfo objects at most
_SETTLED_NS = 2_000_000_000


def _identity(archive):
    try:
        stat = os.fstat(archive.fp.fileno())
    except (AttributeError, OSError, ValueError):
        return None
    # FAT, exFAT and some shares report no file ID, and a write in the same
    # clock tick keeps the time, so very recent files are read again.
    if stat.st_ino == 0 or time.time_ns() - stat.st_mtime_ns <= _SETTLED_NS:
        return None
    return stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns, getattr(archive, 'metadata_encoding', None)


class CachedZipFile(_STDLIB):
    """zipfile.ZipFile whose read-mode directory comes from the shared memo."""

    def _RealGetContents(self):
        # The stdlib reads the central directory only here, from __init__.
        key = _identity(self) if self.mode == 'r' else None
        if key is not None:
            with _LOCK:
                hit = _DIRECTORIES.get(key)
                if hit is not None:
                    _DIRECTORIES.move_to_end(key)
            if hit is not None:
                self.filelist, self.NameToInfo, self.start_dir, self._comment = hit
                return
        super()._RealGetContents()
        if key is None or len(self.filelist) > _ENTRY_LIMIT:
            return
        with _LOCK:
            _DIRECTORIES[key] = (self.filelist, self.NameToInfo, self.start_dir, self._comment)
            _DIRECTORIES.move_to_end(key)
            total = sum(len(kept[0]) for kept in _DIRECTORIES.values())
            while total > _ENTRY_LIMIT:
                _, dropped = _DIRECTORIES.popitem(last=False)
                total -= len(dropped[0])

    # writestr, open('w') and mkdir edit the ZipInfo they are given. A directory
    # entry borrowed from a reader must stay as read.
    def open(self, name, mode='r', pwd=None, *, force_zip64=False):
        if mode == 'w' and isinstance(name, zipfile.ZipInfo):
            name = copy.copy(name)
        return super().open(name, mode, pwd, force_zip64=force_zip64)

    def writestr(self, zinfo_or_arcname, data, compress_type=None, compresslevel=None):
        if isinstance(zinfo_or_arcname, zipfile.ZipInfo):
            zinfo_or_arcname = copy.copy(zinfo_or_arcname)
        return super().writestr(zinfo_or_arcname, data, compress_type, compresslevel)

    def mkdir(self, zinfo_or_directory_name, mode=0o777):
        if isinstance(zinfo_or_directory_name, zipfile.ZipInfo):
            zinfo_or_directory_name = copy.copy(zinfo_or_directory_name)
        return super().mkdir(zinfo_or_directory_name, mode)

    def close(self):
        """Diagnostic only: with GLUEMAPPER_WRITE_LOG set, record each archive this process writes."""
        log = os.environ.get('GLUEMAPPER_WRITE_LOG')
        writing = log and self.mode in ('w', 'x', 'a') and self.fp is not None and isinstance(self.filename, str)
        super().close()
        if writing:
            _record_write(log, self.filename, self.mode)


def _record_write(log, filename, mode):
    import json, sys
    try: size = os.path.getsize(filename)
    except OSError: return
    callers, frame = [], sys._getframe(2)
    while frame is not None and len(callers) < 3:
        name = os.path.basename(frame.f_code.co_filename)
        if name.endswith('.py') and name not in ('archive_directories.py', '__init__.py', 'zipfile.py') \
                and (not callers or callers[-1] != name[:-3]):
            callers.append(name[:-3])
        frame = frame.f_back
    line = json.dumps(dict(path=filename, bytes=size, mode=mode, seconds=round(time.perf_counter(), 3),
                           pid=os.getpid(), callers=callers)) + '\n'
    with _LOCK, open(log, 'a', encoding='utf-8') as stream:
        stream.write(line)


def install():
    """Serve every zipfile.ZipFile(...) in this process from the memo.

    Called from the setup worker entry points. GLUEMAPPER_ARCHIVE_DIRECTORY_CACHE=0
    keeps the stdlib class.
    """
    if os.environ.get('GLUEMAPPER_ARCHIVE_DIRECTORY_CACHE') == '0':
        return False
    zipfile.ZipFile = CachedZipFile
    return True


def uninstall():
    zipfile.ZipFile = _STDLIB
    clear()


def clear():
    with _LOCK:
        _DIRECTORIES.clear()
