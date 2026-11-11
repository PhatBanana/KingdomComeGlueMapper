"""Keep imported shop stock meshes and textures out of the shared travel archive.

Every later recipe stage rewrites gluemappertravel.pak. A stocked armourer adds
hundreds of megabytes of item assets, so they get their own stored ZIP32 shards
in the same mod, like world container and stable stock assets.
"""
from pathlib import Path
import zipfile

SHARD_LIMIT = 1024**3 - 1024**2


def take_assets(files):
    """Remove and return everything that is not a Libs/ table or definition."""
    return {name: files.pop(name) for name in sorted(files) if not name.lower().startswith('libs/')}


def merge_assets(assets, more):
    for name, blob in more.items():
        if assets.setdefault(name, blob) != blob:
            raise ValueError('Merchant asset collision: ' + name)
    return assets


def write_asset_archives(directory, stem, assets, limit=SHARD_LIMIT):
    """Write `<stem>.pak`, `<stem>_01.pak`, ... and return their names; nothing for no assets."""
    directory = Path(directory)
    names, archive, used = [], None, 0
    try:
        for name, blob in sorted(assets.items()):
            cost = len(blob) + 76 + 2*len(name.encode('utf-8'))
            if cost + 22 > limit:
                raise ValueError('Merchant asset exceeds the archive shard limit: ' + name)
            if archive is None or used + cost > limit:
                if archive is not None: archive.close()
                names.append(stem + ('' if not names else '_%02d' % len(names)) + '.pak')
                directory.mkdir(parents=True, exist_ok=True)
                archive = zipfile.ZipFile(directory/names[-1], 'x', zipfile.ZIP_STORED, allowZip64=False)
                used = 22
            item = zipfile.ZipInfo(name, (2026, 1, 1, 0, 0, 0))
            item.create_system = 0
            archive.writestr(item, blob)
            used += cost
    finally:
        if archive is not None: archive.close()
    return names
