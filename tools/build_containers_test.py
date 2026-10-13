"""Stage explicitly selected unowned chest samples without installing them."""
import argparse
import json
from pathlib import Path
import zipfile

from build_horse_trader_test import digest, rewrite
from container_audit import audit
from chairs import inventory
from merchant_stash import stash_assets
from ordinary_containers import eligibility, register
from region_travel import guid
from upgrade_map import read


def build(source, target, mod, output, ids, baseline_level=None):
    if output.exists(): raise FileExistsError('Choose a fresh staging directory')
    report = audit(source, target)
    requested = [r['source_id'] for r in report['records'] if eligibility(r) is None] if ids == 'eligible' else ids.split(',')
    if len(set(requested)) != len(requested): raise ValueError('Duplicate selection')
    by_id = {r['source_id']: r for r in report['records']}
    records = [by_id[sid] for sid in requested]
    for record in records:
        reason = eligibility(record)
        if reason: raise ValueError(record['source_id']+': '+reason)
    original = baseline_level or mod/'Data/Levels/kcd1_travel/level.pak'
    baseline = digest(original)
    with zipfile.ZipFile(original) as archive:
        files = {name: read(archive, name) for name in ('objects_mission0.xml', 'waitinglinks.xml', 'whdata_0')}
    with zipfile.ZipFile(source/'Data/Levels/rataje/level.pak') as archive:
        entities, _, _ = inventory(archive, 'Stash')
    models, resources = {}, {}
    for record in records:
        model = record['model']
        if model in models: continue
        prefix = 'gluebuild/ordinary_containers/'+record['source_id']+'/'
        resources.update(stash_assets(source, entities[record['source_id']], prefix))
        models[model] = prefix+Path(model).name
    updated, converted = register(files, records, models, guid)
    if digest(original) != baseline: raise ValueError('Installed baseline changed during staging')
    destination = output/'Data/Levels/kcd1_travel/level.pak'
    rewrite(original, destination, updated)
    asset_pak = output/'Data/gluemapper_ordinary_containers.pak'
    with zipfile.ZipFile(asset_pak, 'x', zipfile.ZIP_STORED, allowZip64=False) as archive:
        for name, payload in sorted(resources.items()): archive.writestr(name, payload)
    converted.update(baseline=str(original), baseline_sha256=baseline,
        level_sha256=digest(destination), assets_sha256=digest(asset_pak), asset_files=len(resources),
        eligible_initial_chests=sum(eligibility(r) is None for r in report['records']),
        deployment='staged only; installed game unchanged')
    (output/'containers-report.json').write_text(json.dumps(converted, indent=2)+'\n', encoding='utf-8')
    (output/'source-audit.json').write_text(json.dumps(report, indent=2)+'\n', encoding='utf-8')
    print(json.dumps(converted, indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('source', 'target', 'mod', 'output'): parser.add_argument('--'+name, type=Path, required=True)
    parser.add_argument('--ids', required=True, help='Comma-separated source EntityIds, or eligible')
    parser.add_argument('--baseline-level', type=Path, help='Explicit pre-conversion level archive')
    build(**vars(parser.parse_args()))
