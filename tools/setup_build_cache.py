"""Workspace-wide immutable build artifacts; job packages always receive copies."""
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import shutil
import uuid


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


def file_hash(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as f:
        for block in iter(lambda: f.read(4*1024**2), b''): h.update(block)
    return h.hexdigest()


@contextmanager
def environment(config):
    values = {'GLUEMAPPER_BUILD_CACHE': str(Path(config['workspace']).resolve()/'cache'),
              'GLUEMAPPER_REBUILD_CACHE': '1' if config.get('rebuild_cache') else '0',
              'GLUEMAPPER_IMPORTED_CACHE': config.get('imported_cache','')}
    old = {k: os.environ.get(k) for k in values}
    os.environ.update(values)
    try: yield
    finally:
        for k, v in old.items():
            if v is None: os.environ.pop(k, None)
            else: os.environ[k] = v


def root():
    value = os.environ.get('GLUEMAPPER_BUILD_CACHE')
    return Path(value) if value else None


def forced():
    return os.environ.get('GLUEMAPPER_REBUILD_CACHE') == '1'


class Cache:
    def __init__(self, folder):
        self.folder = Path(folder)
        self.folder.mkdir(parents=True, exist_ok=True)

    def lookup(self, key):
        """Never accept partial publication, changed bytes or redirected paths."""
        try:
            name = json.loads((self.folder/(key+'.json')).read_text())['entry']
            if Path(name).name != name or not name.startswith(key+'-'): return None
            entry = self.folder/name
            if entry.resolve() != entry.absolute(): return None
            report = json.loads((entry/'manifest.json').read_text())
            if report['key'] != key or not report['files']: return None
            for rel, expected in report['files'].items():
                p = entry/'payload'/rel
                if (Path(rel).is_absolute() or '..' in Path(rel).parts or ':' in rel
                        or '\\' in rel or p.resolve() != p.absolute()
                        or file_hash(p) != expected): return None
            actual = {p.relative_to(entry/'payload').as_posix()
                      for p in (entry/'payload').rglob('*') if p.is_file()}
            if actual != set(report['files']): return None
            return entry/'payload', report['metadata']
        except (OSError, ValueError, KeyError, TypeError, AttributeError): return None

    def publish(self, key, files, metadata, cancelled=lambda: False):
        # A unique attempt plus atomic pointer keeps the old entry valid until
        # replacement completes. Failed/cancelled attempts are never selected.
        entry = self.folder/(key+'-'+uuid.uuid4().hex)
        payload = entry/'payload'; payload.mkdir(parents=True)
        hashes = {}
        for rel, source in files.items():
            if cancelled(): raise InterruptedError('Cancelled before caching completed outputs')
            destination = payload/rel
            if (Path(rel).is_absolute() or '..' in Path(rel).parts or ':' in rel
                    or '\\' in rel): raise ValueError('Unsafe cache output')
            destination.parent.mkdir(parents=True, exist_ok=True)
            expected = file_hash(source)
            shutil.copy2(source, destination)
            if file_hash(destination) != expected: raise ValueError('Cache copy changed: '+rel)
            hashes[rel] = expected
        (entry/'manifest.json').write_text(json.dumps(dict(key=key, files=hashes, metadata=metadata)))
        if cancelled(): raise InterruptedError('Cancelled before publishing cache')
        pending = self.folder/(entry.name+'.tmp')
        pending.write_text(json.dumps(dict(entry=entry.name)))
        pending.replace(self.folder/(key+'.json'))
        return payload


def copy_payload(payload, destination):
    """No hard links: later consumers may rewrite or consume their own copy."""
    shutil.copytree(payload, destination, dirs_exist_ok=True)
