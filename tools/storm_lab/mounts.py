"""Mod-first name resolution over a converted package and the retail install.

Archives are read in place with zipfile; nothing is extracted or modified.
Only the members the evaluator needs are indexed (Storm sources, RPG/Skald
tables, inventory presets and level mission files), so a full package is
indexed in seconds. Every member that is read is hashed for the report.
"""
import hashlib
from pathlib import Path
import zipfile

WANTED = ('libs/storm/', 'libs/tables/rpg/', 'libs/tables/skald/', 'libs/tables/item/inventorypreset')
NATIVE_PAKS = ('Data/IPL_GameData.pak', 'Data/Tables.pak')


def _key(name):
    return name.replace('\\', '/').lstrip('/').lower()


def _wanted(key):
    return key.startswith(WANTED) or key.endswith('objects_mission0.xml')


class Layer:
    """One mount layer: {lower-case member name: (archive label, loader)}."""

    def __init__(self, label):
        self.label = label
        self.members = {}
        self.duplicates = []
        self.archives = {}

    def add_archive(self, path, prefix=''):
        path = Path(path)
        with zipfile.ZipFile(path) as z:
            names = [i.filename for i in z.infolist() if not i.is_dir()]
        self.archives[str(path)] = dict(size=path.stat().st_size, members=len(names))
        for name in names:
            key = _key(prefix + name)
            if not _wanted(key): continue
            self._put(key, path.name if not prefix else prefix + path.name,
                      lambda path=path, name=name: _read_zip(path, name))

    def add_blob(self, name, data, archive='<blob>'):
        self._put(_key(name), archive, lambda data=data: data if isinstance(data, bytes) else data.encode('utf-8'))

    def _put(self, key, archive, loader):
        if key in self.members:
            # Two mod archives carrying the same member: the engine's choice
            # between them is not modeled, so the report lists it.
            self.duplicates.append(dict(member=key, archives=[self.members[key][0], archive]))
            return
        self.members[key] = (archive, loader)


_OPEN = {}


def _read_zip(path, name):
    # Keep one read-only handle per archive; reopening IPL_GameData.pak for
    # each of ~960 Storm sources would dominate the run time.
    handle = _OPEN.get(path)
    if handle is None:
        handle = _OPEN[path] = zipfile.ZipFile(path)
    return handle.read(name)


class Mounts:
    """Resolve names mod-first, then native. Records a SHA-256 for every read."""

    def __init__(self, mod, native):
        self.mod, self.native = mod, native
        self.hashes = {}
        self._cache = {}

    @classmethod
    def from_paths(cls, package=None, target=None):
        mod, native = Layer('mod'), Layer('native')
        if package is not None:
            package = Path(package)
            data = package / 'Data' if (package / 'Data').is_dir() else package
            for pak in sorted(data.glob('*.pak')):
                mod.add_archive(pak)
            for pak in sorted(data.glob('Levels/*/level.pak')):
                mod.add_archive(pak, prefix='levels/' + pak.parent.name + '/')
        if target is not None:
            for rel in NATIVE_PAKS:
                path = Path(target) / rel
                if not path.is_file():
                    raise FileNotFoundError('Native archive not found: ' + str(path))
                native.add_archive(path)
        return cls(mod, native)

    @classmethod
    def blobs(cls, mod=None, native=None):
        layers = []
        for label, blobs in (('mod', mod or {}), ('native', native or {})):
            layer = Layer(label)
            for name, data in sorted(blobs.items()): layer.add_blob(name, data, '<' + label + '>')
            layers.append(layer)
        return cls(*layers)

    def where(self, name):
        key = _key(name)
        if key in self.mod.members: return 'mod'
        if key in self.native.members: return 'native'
        return None

    def read(self, name, layer=None):
        key = _key(name)
        layers = [self.mod, self.native] if layer is None else [getattr(self, layer)]
        for current in layers:
            if key in current.members:
                cache_key = (current.label, key)
                if cache_key not in self._cache:
                    archive, loader = current.members[key]
                    data = loader()
                    self._cache[cache_key] = data
                    self.hashes[current.label + ':' + key] = dict(archive=archive, sha256=hashlib.sha256(data).hexdigest())
                return self._cache[cache_key]
        return None

    def names(self, prefix, layer=None):
        prefix = _key(prefix)
        layers = [self.mod, self.native] if layer is None else [getattr(self, layer)]
        seen = []
        for current in layers:
            for key in current.members:
                if key.startswith(prefix) and key not in seen: seen.append(key)
        return sorted(seen)

    def provenance(self):
        return dict(mod_archives=self.mod.archives, native_archives=self.native.archives,
                    mod_duplicate_members=self.mod.duplicates, files_read=dict(sorted(self.hashes.items())))
