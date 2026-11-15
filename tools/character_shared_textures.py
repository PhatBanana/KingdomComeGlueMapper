"""Store each baked character texture once, however many people wear it.

People in the same clothes bake byte-identical texture families (a streamed
base .dds with its .N mip and .a alpha files). Each family is named by its
contents under PREFIX and written once to shared archives; every person's
materials point there, and the person's own archives keep meshes and
materials only.

A family is the unit: it is hashed, staged, packed and reused whole, so its
mip files can never come from two owners. The texture kind suffix (_diff,
_ddna, ...) stays in the name because the engine reads meaning from it.
"""
from pathlib import Path
import hashlib
import posixpath
import re
import shutil
import struct
import uuid
import zipfile

PREFIX = 'objects/characters/gluetravel/shared/'
ARCHIVE = 'gluemapper_person_textures_'
SHARD_LIMIT = 900 * 1024**2
MEMBER = re.compile(r'(.+\.dds)(\.(?:a|\d+a?))?')
SHARED = re.compile(re.escape(PREFIX) + r'([0-9a-f]{32}_[a-z0-9]+)\.dds(?:\.(?:a|\d+a?))?')
TEXTURE = re.compile(r'(<Texture\b[^>]*?\bFile\s*=\s*)(["\'])(.*?)\2', re.S)


def family_name(base, members):
    """Content name of a family: members maps '' and mip/alpha suffixes to bytes."""
    digest = hashlib.sha256()
    for suffix in sorted(members):
        digest.update(b'%s:%d:' % (suffix.encode('ascii'), len(members[suffix])))
        digest.update(members[suffix])
    kind = re.search(r'_([a-z0-9]+)\.dds$', posixpath.basename(base).lower())
    return digest.hexdigest()[:32] + '_' + (kind[1] if kind else 'tex')


def texture_path(value, material):
    """Package path a material's Texture File names, as packaged paths are compared."""
    value = value.replace('\\', '/').lower()
    if value.startswith('./'):
        value = posixpath.join(posixpath.dirname(material.replace('\\', '/').lower()), value[2:])
    return value


def references(blob, material):
    """Texture paths of one .mtl, in document order."""
    return [texture_path(m[3], material) for m in TEXTURE.finditer(blob.decode('latin-1'))]


def rewrite(blob, material, mapping):
    """Point the mapped texture paths at their shared families; change nothing else."""
    def replace(match):
        target = mapping.get(texture_path(match[3], material))
        return match[0] if target is None else match[1] + match[2] + target + match[2]
    return TEXTURE.sub(replace, blob.decode('latin-1')).encode('latin-1')  # every other byte as it was


class Store:
    """Folder of complete families staged by any number of processes.

    A family appears under its content name by one rename of a finished
    folder, so a reader never sees part of one and identical families from
    two workers are the same bytes whichever rename wins.
    """
    def __init__(self, folder):
        self.folder = Path(folder)
        self.used = set()

    def put(self, name, members):
        self.used.add(name)
        final = self.folder / name
        if final.is_dir():
            return False
        pending = self.folder / ('.' + uuid.uuid4().hex)
        pending.mkdir(parents=True)
        for suffix, blob in members.items():
            (pending / (name + '.dds' + suffix)).write_bytes(blob)
        return self._publish(pending, final)

    def adopt(self, folder):
        """Copy the families of another store (a cached character) that are missing here."""
        for source in sorted(p for p in Path(folder).iterdir() if p.is_dir()):
            self.used.add(source.name)
            final = self.folder / source.name
            if final.is_dir():
                continue
            self.folder.mkdir(parents=True, exist_ok=True)
            pending = self.folder / ('.' + uuid.uuid4().hex)
            shutil.copytree(source, pending)
            self._publish(pending, final)

    def _publish(self, pending, final):
        try:
            pending.rename(final)
        except OSError:
            shutil.rmtree(pending, ignore_errors=True)
            if not final.is_dir(): raise
            return False
        return True

    def files(self, names=None):
        """Staged files by cache-relative path, for the families named (default: those used here)."""
        return {name + '/' + p.name: p for name in sorted(self.used if names is None else names)
                for p in sorted((self.folder / name).iterdir())}

    def names(self):
        if not self.folder.is_dir(): return []
        return sorted(p.name for p in self.folder.iterdir() if p.is_dir() and not p.name.startswith('.'))


class Sharing:
    """Route one person's packed entries: referenced texture families to the store.

    Feed every entry in order with the members of a family together and the
    materials after the textures (the order of names). Entries that stay in the
    person's archive are returned, materials already pointing at the store.
    """
    def __init__(self, store, namespace, materials, names):
        """materials maps the packed .mtl names to bytes; names lists every packed file."""
        prefix = 'objects/characters/gluetravel/' + namespace.lower() + '/'
        present = {n.replace('\\', '/').lower() for n in names}
        self.store, self.mapping = store, {}
        # Only this person's own textures that a packed material names: a
        # texture nothing here references may be reached from elsewhere.
        self.wanted = {path for name, blob in materials.items() for path in references(blob, name)
                       if path.startswith(prefix) and path in present}
        self.base, self.members = None, []
        self.names = self._ordered(names)

    def _ordered(self, names):
        """Shared families first, each together, then everything else in the given order."""
        first = [n for n in names if self._base(n) is not None]
        chosen = set(first)
        return sorted(first, key=lambda n: (self._base(n), n.lower())) + [n for n in names if n not in chosen]

    def _base(self, name):
        match = MEMBER.fullmatch(name.replace('\\', '/').lower())
        return match[1] if match and match[1] in self.wanted else None

    def route(self, name, blob):
        base = self._base(name)
        if base is not None:
            kept = self._flush() if base != self.base else []
            self.base = base
            self.members.append((name, blob))
            return kept
        kept = self._flush()
        if name.lower().endswith('.mtl'):
            missing = sorted(self.wanted.intersection(references(blob, name)) - set(self.mapping))
            if missing:
                raise ValueError('Material packed before its shared texture: ' + missing[0])
            blob = rewrite(blob, name, self.mapping)
        return kept + [(name, blob)]

    def finish(self):
        return self._flush()

    def _flush(self):
        from texture_streaming import validate_family
        base, entries, self.base, self.members = self.base, self.members, None, []
        if base is None:
            return []
        members = {name.replace('\\', '/').lower()[len(base):]: blob for name, blob in entries}
        resident = members.get('')
        # A family without its base here, and cube/volume textures, keep the
        # writer's own handling: they stay at their original path.
        if resident is None or (len(resident) >= 128 and struct.unpack_from('<I', resident, 112)[0] & 0xFE00):
            return entries
        try: validate_family(resident, {k: v for k, v in members.items() if k})
        except ValueError as error: raise ValueError(base + ': ' + str(error)) from error
        name = family_name(base, members)
        self.store.put(name, members)
        self.mapping[base] = PREFIX + name + '.dds'
        return []


def packaged(*folders):
    """Shared families already present in the texture archives of these Data folders."""
    names = set()
    for folder in folders:
        for path in sorted(Path(folder).glob(ARCHIVE + '*.pak')):
            with zipfile.ZipFile(path) as archive:
                for entry in archive.namelist():
                    match = SHARED.fullmatch(entry.replace('\\', '/').lower())
                    if match: names.add(match[1])
    return names


def pack(store, data_dir, limit=SHARD_LIMIT, existing=()):
    """Write the staged families no archive holds yet; return the new archives.

    Existing archives are never rewritten or removed: another person may use
    any family in them. An archive is named by the families it holds, so
    stages built apart never produce one name with different contents, and
    the same families always produce the same archives.
    """
    store, data_dir = Store(store) if not isinstance(store, Store) else store, Path(data_dir)
    have = packaged(data_dir, *existing)
    groups, used = [], 22
    for name in store.names():
        if name in have: continue
        files = sorted((store.folder / name).iterdir())
        size = sum(p.stat().st_size + 2 * len((PREFIX + p.name).encode('utf-8')) + 76 for p in files)
        if size + 22 > limit: raise ValueError('Shared texture exceeds ZIP32 shard limit: ' + name)
        if not groups or used + size > limit or len(groups[-1]) + len(files) > 50000:
            groups.append([]); used = 22
        groups[-1].extend(files); used += size
    paks = []
    for files in groups:
        identity = hashlib.sha256('\n'.join(p.name for p in files).encode('ascii')).hexdigest()[:16]
        path = data_dir / (ARCHIVE + identity + '.pak')
        paks.append(path)
        if path.exists(): continue  # the same families, already published
        pending = path.with_name(path.name + '.partial')
        pending.unlink(missing_ok=True)  # an interrupted run; never write through an old file
        with zipfile.ZipFile(pending, 'w', zipfile.ZIP_STORED, allowZip64=False) as archive:
            for p in files:
                item = zipfile.ZipInfo(PREFIX + p.name, (2026, 1, 1, 0, 0, 0))
                item.create_system = 0
                archive.writestr(item, p.read_bytes())
        pending.rename(path)
    return paks
