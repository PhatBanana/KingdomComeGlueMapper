"""Stage authored character LODs without changing installed LOD0 or textures."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
from pathlib import Path
import zipfile

from character_person import resolve_person
from character_person_appearance import build_appearance
from upgrade_map import read


def build(source, target, baseline, output, *, workers=2):
    source, target, baseline, output = map(Path, (source, target, baseline, output))
    if output.exists():
        raise FileExistsError('Choose a fresh character LOD stage')
    if not 1 <= workers <= 2:
        raise ValueError('Character conversion supports one or two concurrent workers')
    output.mkdir(parents=True)
    index, imports = {}, {}
    for path in sorted((baseline / 'Data').glob('*.pak')):
        with zipfile.ZipFile(path) as archive:
            for name in archive.namelist():
                if name.lower().endswith('.skin'):
                    key = name.replace('\\', '/').lower()
                    if key in index:
                        raise ValueError('Ambiguous installed skin ownership: ' + key)
                    index[key] = (path, name)
                if name.startswith('Libs/GlueMapper/PersonImport/') and name.endswith('.json'):
                    record = json.loads(read(archive, name))
                    imports[record['namespace']] = record
    if not imports:
        raise ValueError('No source person receipts in the selected package')

    def convert(record):
        namespace = record['namespace']
        person = resolve_person(source, record['person'], include_ai=False)
        folder = output / 'people' / namespace
        appearance = build_appearance(source, target, person, namespace, folder)
        additions = {}
        for path in folder.rglob('*.skin'):
            virtual = path.relative_to(folder).as_posix()
            if '_lod' not in path.stem.lower():
                old = index.get(virtual.lower())
                if old is None:
                    raise ValueError('LOD migration would add new base geometry: ' + virtual)
                with zipfile.ZipFile(old[0]) as archive:
                    original = read(archive, old[1])
                if original != path.read_bytes():
                    raise ValueError('LOD migration base differs; rebuild the actor explicitly: ' + virtual)
            else:
                additions[virtual] = path.read_bytes()
        report = dict(person=record['person'], namespace=namespace, lod_files=len(additions),
                      parts=[dict(kind=p['kind'], model=p['model'], lods=p['lods'])
                             for p in appearance['parts']], base_geometry_unchanged=True)
        print(json.dumps(dict(person=record['person'], lod_files=len(additions))), flush=True)
        return additions, report

    reports, files = [], {}
    with ThreadPoolExecutor(max_workers=workers) as pool:
        for added, report in pool.map(convert, imports.values()):
            if files.keys() & added.keys():
                raise ValueError('Character LOD output collision')
            files.update(added); reports.append(report)
    if not files:
        raise ValueError('Selected characters have no authored source LODs')
    pak = output / 'gluemapper_character_lods.pak'
    with zipfile.ZipFile(pak, 'w', compression=zipfile.ZIP_DEFLATED, allowZip64=False) as archive:
        for name, payload in sorted(files.items()):
            archive.writestr(name, payload)
    report = dict(version=1, people=reports, lod_files=len(files),
        archive_sha256=hashlib.sha256(pak.read_bytes()).hexdigest(), runtime_verified=False,
        policy='Authored source LODs; native character selection; LOD0 and materials unchanged')
    (output / 'report.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('source', 'target', 'baseline', 'output'):
        parser.add_argument('--' + name, type=Path, required=True)
    parser.add_argument('--workers', type=int, default=2)
    build(**vars(parser.parse_args()))
