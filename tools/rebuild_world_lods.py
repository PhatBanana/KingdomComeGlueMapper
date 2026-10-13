"""Restore omitted external LOD dependencies without replacing installed assets.

Builds an additive package only. Installation requires a game restart.
"""
import argparse
from contextlib import ExitStack
import hashlib
import json
from pathlib import Path
import re
import zipfile

from campaign_package import PREFIXES, dependency_closure, safe_name, write_asset_shards
from upgrade_map import read


def build(converted, installed, output):
    converted, installed, output = map(Path, (converted, installed, output))
    output.mkdir(parents=True, exist_ok=False)
    with ExitStack() as stack:
        source, current = {}, {}
        for path in sorted(converted.glob('gluemapper_*.pak')):
            archive = stack.enter_context(zipfile.ZipFile(path))
            for name in archive.namelist():
                key = safe_name(name)
                if key.split('/')[0] in PREFIXES:
                    source[key] = (archive, name)
        for prefix in PREFIXES:
            for path in sorted((converted / prefix).rglob('*')):
                if path.is_file():
                    if not path.resolve().is_relative_to(converted.resolve()):
                        raise ValueError('Asset outside converted directory')
                    source[safe_name(path.relative_to(converted).as_posix())] = path
        for path in sorted(installed.glob('*.pak')):
            archive = stack.enter_context(zipfile.ZipFile(path))
            for name in archive.namelist():
                key = safe_name(name)
                if key.split('/')[0] in PREFIXES:
                    current[key] = (archive, name)
        index = {**source, **current}

        def load(name):
            entry = index[name]
            return entry.read_bytes() if isinstance(entry, Path) else read(*entry)

        models = sorted(n for n in current if n.endswith('.cgf')
                        and not re.search(r'_lod\d+\.cgf$', n))
        expected = {name[:-4] + f'_lod{i}.cgf' for name in models
                    for i in range(1, 7) if name[:-4] + f'_lod{i}.cgf' in source}
        missing = expected - current.keys()
        print(f'{len(models)} installed models; {len(expected)} authored LODs; {len(missing)} missing', flush=True)
        # Resolve every authored LOD, including those already installed, so
        # missing secondary dependencies are repaired as well.
        selected = dependency_closure(expected, index, load)
        additions = sorted(set(selected) - current.keys())
        shards, assets = write_asset_shards(output,
            ((n, load(n)) for n in additions), total_entries=len(additions))
        renamed = []
        for i, name in enumerate(shards):
            target = f'gluemapper_world_lods_{i:03d}.pak'
            (output/name).rename(output/target)
            renamed.append(target)
        packaged = {}
        for name in renamed:
            with zipfile.ZipFile(output/name) as archive:
                if archive.testzip() is not None:
                    raise ValueError('Corrupt rebuilt LOD archive')
                for entry in archive.namelist():
                    if entry in current or entry in packaged:
                        raise ValueError('LOD repair would override an existing asset')
                    packaged[entry] = hashlib.sha256(read(archive, entry)).hexdigest()
        if set(packaged) != set(additions) or expected - current.keys() - packaged.keys():
            raise ValueError('Incomplete LOD dependency package')
        for asset in assets:
            if packaged[asset['path']] != asset['sha256']:
                raise ValueError('LOD package payload mismatch')
        report = dict(converted=str(converted.resolve()), installed=str(installed.resolve()),
            installed_base_models=len(models), models_with_source_lods=len({n.rsplit('_lod',1)[0] for n in expected}),
            authored_lods=len(expected), already_installed_lods=len(expected)-len(missing),
            restored_lods=len(missing), missing_dependencies_after=0,
            archives=renamed, assets=assets, lod_paths=sorted(expected),
            runtime_lod_transitions_verified=False)
        (output/'receipt.json').write_text(json.dumps(report, indent=2))
        return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--converted', required=True)
    parser.add_argument('--installed', required=True)
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    report = build(args.converted, args.installed, args.output)
    print(json.dumps({k:v for k,v in report.items() if k not in ('assets','lod_paths')}, indent=2))
