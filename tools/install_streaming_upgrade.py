"""Install staged texture/spatial conversions, preserving GI and unrelated assets.

Rewrite every existing copy of a replaced texture so mount order cannot select
an old header. New mip slices and proxy assets are additive. Keep hardlink backups
and a transaction journal; never update packages while KingdomCome is running.
"""
import argparse
from collections import Counter
from contextlib import ExitStack
import json
from pathlib import Path
import shutil
import xml.etree.ElementTree as ET
import zipfile
from campaign_package import write_asset_shards, safe_name
from install_world_surfaces import game_running
from validate_world_surfaces import digest
from spatial_hlod import read_groups, records


def install(data, level, textures, spatial, recovery):
    data, level, textures, spatial, recovery = map(lambda p: Path(p).resolve(),
                                                  (data, level, textures, spatial, recovery))
    if not level.is_relative_to(data):
        raise ValueError('Level must be inside target mod Data')
    if game_running():
        raise RuntimeError('Close KingdomCome before installing streaming data')
    recovery.mkdir(parents=True, exist_ok=False)
    incoming = recovery / 'incoming'; incoming.mkdir()
    previous = recovery / 'previous'; previous.mkdir()
    baseline = {}; replacements = {}; changed = []
    lighting = {str(p): digest(p) for p in level.glob('svo*.pak')}
    with ExitStack() as stack:
        assets = {}
        for folder in (textures, spatial / 'packages'):
            for path in sorted(folder.glob('kingdomcomegluemapper_world_*.pak')):
                z = stack.enter_context(zipfile.ZipFile(path))
                if z.testzip(): raise ValueError('Staged asset CRC failure')
                for name in z.namelist():
                    key = safe_name(name)
                    if key in assets: raise ValueError('Conflicting staged asset '+key)
                    assets[key] = (z, name)
        used = set()
        for path in sorted(data.glob('*.pak')):
            with zipfile.ZipFile(path) as old:
                if not any(safe_name(n) in assets for n in old.namelist()): continue
                target = incoming / path.name
                baseline[str(path)] = digest(path)
                with zipfile.ZipFile(target, 'x', zipfile.ZIP_STORED) as out:
                    for item in old.infolist():
                        name = safe_name(item.filename)
                        if name in assets:
                            z, entry = assets[name]; payload = z.read(entry); used.add(name)
                        else: payload = old.read(item)
                        out.writestr(item, payload)
                replacements[str(path)] = str(target)
        extras = incoming / 'extras'; extras.mkdir()
        shards, _ = write_asset_shards(extras, ((n, assets[n][0].read(assets[n][1]))
                                              for n in sorted(assets.keys()-used)))
        for index, name in enumerate(shards):
            target = data / f'gluemapper_spatial_streaming_{index:03d}.pak'
            if target.exists(): raise ValueError('Streaming upgrade already present')
            replacements[str(target)] = str(extras / name)
    # Check every original level entry except the three intentional outputs.
    for filename in ('level.pak', 'terrain.pak'):
        path = level / filename; staged = spatial / 'packages' / filename
        baseline[str(path)] = digest(path)
        with zipfile.ZipFile(path) as old, zipfile.ZipFile(staged) as new:
            if set(old.namelist()) != set(new.namelist()) or new.testzip():
                raise ValueError('Level archive membership/CRC mismatch')
            for name in old.namelist():
                if name.lower() in ('terrain/hlods.xml', 'terrain/hlods.dat', 'terrain/terrain.dat'): continue
                if old.read(name) != new.read(name):
                    raise ValueError('Unrelated level/lighting entry changed: '+name)
            if filename == 'level.pak':
                near = Counter(read_groups(ET.fromstring(old.read('terrain/hlods.xml')), old.read('terrain/hlods.dat')))
                tree = ET.fromstring(new.read('terrain/hlods.xml')); blob = new.read('terrain/hlods.dat')
                retained = Counter()
                for node in tree.iter('HLod'):
                    offset, size = int(node.get('DataOffset')), int(node.get('DataSize'))
                    own = records(blob[offset+4:offset+size])
                    proxies = {int(c.get('ProxyIndex')) for c in node if int(c.get('ProxyIndex', '-1')) >= 0}
                    if any(i >= len(own) or len(own[i]) != 104 for i in proxies):
                        raise ValueError('Invalid parent proxy index')
                    retained.update(r for i, r in enumerate(own) if i not in proxies)
                if retained != near: raise ValueError('Near geometry changed')
        replacements[str(path)] = str(staged)
    for index, path in enumerate(baseline):
        backup = previous / str(index)
        try: backup.hardlink_to(Path(path))
        except OSError: shutil.copy2(path, backup)
    backups = {path: str(previous / str(i)) for i, path in enumerate(baseline)}
    journal = dict(status='prepared', baseline=baseline, backups=backups,
                   replacements=replacements, lighting=lighting, runtime_verified=False)
    receipt = recovery / 'installation.json'
    receipt.write_text(json.dumps(journal, indent=2)+'\n')
    # Copy first, verify, then replace; backup links stay immutable.
    copies = {}
    for i, (target, source) in enumerate(replacements.items()):
        copy = incoming / f'install-{i}.pak'; shutil.copy2(source, copy)
        if digest(copy) != digest(source): raise ValueError('Staging copy mismatch')
        copies[target] = copy
    try:
        if game_running(): raise RuntimeError('Game started during install preparation')
        if any(digest(p) != sha for p, sha in baseline.items()):
            raise ValueError('Installed inputs changed during preparation')
        for target, copy in copies.items():
            copy.replace(target); changed.append(target)
        if any(digest(p) != sha for p, sha in lighting.items()):
            raise ValueError('Lighting changed during install')
        journal['installed'] = {p: digest(p) for p in replacements}
        journal['status'] = 'installed_verified'
    except Exception:
        for target in reversed(changed):
            if target in backups:
                copy = incoming / 'rollback.pak'; shutil.copy2(backups[target], copy); copy.replace(target)
            else: Path(target).unlink()
        journal['status'] = 'rolled_back'
        raise
    finally:
        receipt.write_text(json.dumps(journal, indent=2)+'\n')
    return journal


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('data', 'level', 'textures', 'spatial', 'recovery'):
        parser.add_argument('--'+name, type=Path, required=True)
    args = parser.parse_args()
    print(install(**vars(args))['status'])
