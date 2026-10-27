"""Mounted read-only view of PAK files (or generated blobs) without extracting anything."""
import hashlib
import io
from pathlib import Path
import struct
import zipfile
import zlib

from . import norm

NATIVE_GLOBS = ('Data/*.pak', 'Data/Levels/*/*.pak', 'Engine/*.pak')


def package_paks(root):
    root = Path(root)
    if root.is_file(): return [root]
    data = root / 'Data' if (root / 'Data').is_dir() else root
    return sorted(data.rglob('*.pak'))


def native_paks(root):
    root = Path(root)
    found = []
    for pattern in NATIVE_GLOBS: found += sorted(root.glob(pattern))
    return found


class Archives:
    """Maps lower-case member names to ``(pak index, original name, size)`` in mount order."""

    def __init__(self, paths, label='package'):
        self.label = label
        self.paths = [Path(p) for p in paths]
        self.blobs_ = {}
        self.members = {}
        self.fingerprints = []
        self._open = {}
        for index, path in enumerate(self.paths):
            with zipfile.ZipFile(path) as z:
                digest = hashlib.sha256()
                infos = z.infolist()
                for info in infos:
                    self.members.setdefault(norm(info.filename), []).append((index, info.filename, info.file_size))
                    digest.update(f'{info.filename}\0{info.file_size}\0{info.CRC}\n'.encode('utf-8', 'surrogatepass'))
            self.fingerprints.append(dict(path=path.as_posix(), bytes=path.stat().st_size, members=len(infos),
                                          directory_sha256=digest.hexdigest()))

    @classmethod
    def blobs(cls, blobs, label='generated'):
        """Synthetic archive for unit tests and ``run`` scenarios."""
        obj = cls([], label)
        digest = hashlib.sha256()
        for name, data in sorted(blobs.items()):
            obj.blobs_[norm(name)] = bytes(data)
            obj.members.setdefault(norm(name), []).append((-1, name, len(data)))
            digest.update(name.encode() + b'\0' + hashlib.sha256(data).digest())
        obj.fingerprints.append(dict(path='<generated>', bytes=sum(map(len, blobs.values())),
                                     members=len(blobs), directory_sha256=digest.hexdigest()))
        return obj

    def merged(self, other, label=None):
        """Mod-first union, used so references resolve against package then native data."""
        obj = Archives([], label or self.label + '+' + other.label)
        obj.paths = self.paths + other.paths
        shift = len(self.paths)
        obj.blobs_ = {**other.blobs_, **self.blobs_}
        for key, rows in self.members.items(): obj.members.setdefault(key, []).extend(rows)
        for key, rows in other.members.items():
            obj.members.setdefault(key, []).extend((i + shift if i >= 0 else i, n, s) for i, n, s in rows)
        obj.fingerprints = self.fingerprints + other.fingerprints
        return obj

    def __contains__(self, name):
        return norm(name) in self.members

    def keys(self):
        return self.members.keys()

    def size(self, name):
        return self.members[norm(name)][0][2]

    def names(self, prefix=''):
        prefix = norm(prefix)
        return [k for k in self.members if k.startswith(prefix)]

    def _zip(self, index):
        z = self._open.get(index)
        if z is None:
            z = self._open[index] = zipfile.ZipFile(self.paths[index])
        return z

    def _row(self, name, which=0):
        return self.members[norm(name)][which]

    def pak_of(self, name, which=0):
        index = self._row(name, which)[0]
        return '<generated>' if index < 0 else self.paths[index].name

    def _stream(self, z, original):
        try: return z.open(original)
        except zipfile.BadZipFile:
            # Some retail archives store backslashes in local headers; read the data directly.
            return io.BytesIO(self._raw(z, z.getinfo(original)))

    @staticmethod
    def _raw(z, info):
        z.fp.seek(info.header_offset)
        header = z.fp.read(30)
        name_length, extra_length = struct.unpack_from('<HH', header, 26)
        z.fp.seek(info.header_offset + 30 + name_length + extra_length)
        data = z.fp.read(info.compress_size)
        if info.compress_type == zipfile.ZIP_STORED: return data
        if info.compress_type == zipfile.ZIP_DEFLATED: return zlib.decompress(data, -15)
        raise NotImplementedError(f'compression {info.compress_type}')

    def label_of(self, name, which=0):
        """``level/pak`` style label that tells same-named members of different archives apart."""
        index = self._row(name, which)[0]
        if index < 0: return '<generated>'
        return self.paths[index].parent.name + '/' + self.paths[index].name

    def same_folder(self, name_a, which_a, name_b, which_b):
        a, b = self._row(name_a, which_a)[0], self._row(name_b, which_b)[0]
        if a < 0 or b < 0: return a == b
        return self.paths[a].parent == self.paths[b].parent

    def read(self, name, which=0):
        index, original, _ = self._row(name, which)
        if index < 0: return self.blobs_[norm(name)]
        z = self._zip(index)
        try: return z.read(original)
        except zipfile.BadZipFile: return self._raw(z, z.getinfo(original))

    def read_head(self, name, count, which=0):
        index, original, size = self._row(name, which)
        if index < 0: return self.blobs_[norm(name)][:count]
        with self._stream(self._zip(index), original) as f: return f.read(count)

    def read_tail(self, name, count):
        index, original, size = self._row(name)
        if index < 0: return self.blobs_[norm(name)][-count:] if count else b''
        z = self._zip(index)
        with self._stream(z, original) as f:
            if z.getinfo(original).compress_type == zipfile.ZIP_STORED and f.seekable():
                f.seek(max(0, size - count))
            elif size > count: f.read(size - count)
            return f.read(count)

    def close(self):
        for z in self._open.values(): z.close()
        self._open.clear()
