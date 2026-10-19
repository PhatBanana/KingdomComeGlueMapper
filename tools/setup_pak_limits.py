"""Keep travel asset payloads in bounded retail-mountable archives."""
from pathlib import Path
import shutil
import tempfile
import zipfile

TRAVEL = 'Data/gluemappertravel.pak'
SHARD_BYTES = 1024 ** 3
RETAIL_BYTES = 2 ** 31


def validate(package):
    # ZIP64 can describe an archive which retail refuses to mount. This check
    # is deliberately separate from Python ZIP integrity and receipt hashes.
    for path in Path(package).rglob('*.pak'):
        if path.stat().st_size >= RETAIL_BYTES:
            raise ValueError('PAK exceeds retail size limit; rebuild with corrected setup: '
                             + path.relative_to(package).as_posix())


def split_assets(package, max_bytes=SHARD_BYTES, max_entries=50000):
    """Move objects/ payloads only; preserve paths, bytes and gameplay tables.

    Existing asset shards are retained. Subsequent migrations may append new
    assets to travel; new shards sort after old shards, preserving precedence.
    All new archives are checked before replacing the original travel archive.
    """
    from setup_campaign import digest
    package = Path(package)
    path = package/TRAVEL
    if not path.is_file() or path.stat().st_size < max_bytes:
        return {}
    with tempfile.TemporaryDirectory(prefix='travel-paks-', dir=package.parent) as temp:
        work = Path(temp)
        outputs = []
        with zipfile.ZipFile(path) as source:
            infos = source.infolist()
            if len({i.filename for i in infos}) != len(infos):
                raise ValueError('Duplicate travel archive members')
            assets = [i for i in infos if i.filename.replace('\\', '/').lower().startswith('objects/')]
            remaining = [i for i in infos if i not in assets]
            def cost(i): return i.file_size + 76 + 2*len(i.filename.encode('utf-8'))
            if not assets or 22 + sum(map(cost, remaining)) >= RETAIL_BYTES:
                raise ValueError('Travel resources exceed retail size limit after asset separation')
            groups = []
            size = 22
            for info in assets:
                amount = cost(info)
                if amount + 22 > max_bytes:
                    raise ValueError('Individual travel asset exceeds shard limit: '+info.filename)
                if not groups or size+amount > max_bytes or len(groups[-1]) >= max_entries:
                    groups.append([]); size = 22
                groups[-1].append(info); size += amount
            index = 0
            for group in groups:
                while (package/f'Data/gluemappertravel_assets_{index:04d}.pak').exists(): index += 1
                outputs.append((f'Data/gluemappertravel_assets_{index:04d}.pak', group))
                index += 1
            outputs.append((TRAVEL, remaining))
            for relative, members in outputs:
                staged = work/Path(relative).name
                with zipfile.ZipFile(staged, 'x', zipfile.ZIP_STORED, allowZip64=False) as out:
                    for info in members:
                        item = zipfile.ZipInfo(info.filename, info.date_time)
                        item.create_system = info.create_system
                        item.external_attr = info.external_attr
                        with source.open(info) as src, out.open(item, 'w') as dst:
                            shutil.copyfileobj(src, dst, 1024*1024)
                with zipfile.ZipFile(staged) as check:
                    expected = [(i.filename, i.file_size, i.CRC) for i in members]
                    actual = [(i.filename, i.file_size, i.CRC) for i in check.infolist()]
                    if actual != expected or check.testzip() is not None:
                        raise ValueError('Travel shard payload mismatch: '+relative)
                limit = RETAIL_BYTES if relative == TRAVEL else max_bytes+1
                if staged.stat().st_size >= limit:
                    raise ValueError('Travel shard exceeds size limit: '+relative)
        changed = {}
        for relative, _ in outputs:
            staged = work/Path(relative).name
            changed[relative] = digest(staged)
            staged.replace(package/relative)
        return changed


