"""Restore source-authored probe activation when the converted bake is complete.

Incremental packages can retain old diagnostic disables. Reconcile them against
active source layers and validate every native time sample before restoring one.
Never enable probes whose original bake was missing or whose source was inactive.
"""
import argparse
from contextlib import ExitStack
import json
import os
from pathlib import Path
import tempfile
import xml.etree.ElementTree as ET
import zipfile

from chairs import inventory
from lighting_cubemaps import TARGET_TIMES, stamp, standard_cube
from upgrade_map import read, xml


def reconcile(root, sources, validate_cube):
    sources = {e.get('EntityId'): e for e in sources}
    records = []
    for entity in root.iter('Entity'):
        name = entity.get('Name', '')
        if entity.get('EntityClass') != 'EnvironmentLight' or not name.startswith('gm_lighting_'):
            continue
        source = sources.get(name.removeprefix('gm_lighting_'))
        props = entity.find('Properties')
        if source is None or props is None or props.get('bActive', '1') != '0':
            continue
        source_props = source.find('Properties')
        if source_props is None or source_props.get('bActive', '1') != '1':
            continue
        advanced = props.find('OptionsAdvanced')
        record = {'name': name, 'source_id': source.get('EntityId')}
        paths = []
        if advanced is not None:
            if advanced.get('bDynamic', '0') == '1':
                paths = [f'textures/cubemaps/kcd1_travel/{name}/{stamp(t)}_cm.dds' for t in TARGET_TIMES]
            elif advanced.get('texture_deferred_cubemap'):
                paths = [advanced.get('texture_deferred_cubemap').replace('\\', '/').lower()]
        try:
            if not paths or any(not p.endswith('_cm.dds') for p in paths):
                raise ValueError('No converted cubemap reference')
            for path in paths:
                validate_cube(path)
                validate_cube(path.removesuffix('_cm.dds') + '_cm_diff.dds')
        except (KeyError, ValueError) as error:
            record.update(status='preserved_disabled', reason=str(error))
        else:
            props.set('bActive', '1')
            record.update(status='restored', validated_cubemaps=len(paths)*2)
        records.append(record)
    return {'restored_count': sum(r['status'] == 'restored' for r in records), 'probes': records}


def build(mod, source, output):
    mod, source, output = map(Path, (mod, source, output))
    if output.exists():
        raise FileExistsError('Choose a fresh probe-activation output directory')
    with zipfile.ZipFile(source/'Data/Levels/rataje/level.pak') as pak:
        _, selected, _ = inventory(pak, 'EnvironmentLight')
    level = mod/'Data/Levels/kcd1_travel/level.pak'
    with ExitStack() as stack:
        # Include level-local resources; later local entries override root PAKs.
        paths = sorted((mod/'Data').glob('*.pak')) + sorted(level.parent.glob('*.pak'))
        index = {}
        for path in paths:
            pak = stack.enter_context(zipfile.ZipFile(path))
            for name in pak.namelist():
                if name.lower().startswith('textures/cubemaps/'):
                    index[name.lower()] = (pak, name)
        def validate(path):
            members = []
            i = 1
            while path+'.'+str(i) in index:
                members.append(read(*index[path+'.'+str(i)]))
                i += 1
            standard_cube(read(*index[path]), members)
        archive = stack.enter_context(zipfile.ZipFile(level))
        root = ET.fromstring(read(archive, 'objects_mission0.xml'))
        report = reconcile(root, selected, validate)
        output.mkdir(parents=True)
        if report['restored_count']:
            with zipfile.ZipFile(output/'level.pak', 'w') as result:
                for info in archive.infolist():
                    result.writestr(info, xml(root) if info.filename == 'objects_mission0.xml'
                                    else archive.read(info))
            with zipfile.ZipFile(output/'level.pak') as result:
                if result.testzip():
                    raise ValueError('Invalid repaired level archive')
                for info in archive.infolist():
                    if info.filename != 'objects_mission0.xml' and archive.read(info) != result.read(info.filename):
                        raise ValueError('Unexpected non-probe resource change')
    (output/'report.json').write_text(json.dumps(report, indent=2)+'\n', encoding='utf-8')
    return report


def repair_package(mod, source):
    mod = Path(mod)
    with tempfile.TemporaryDirectory(prefix='probe-activation-', dir=mod.parent) as temporary:
        stage = Path(temporary)/'stage'
        report = build(mod, source, stage)
        if report['restored_count']:
            os.replace(stage/'level.pak', mod/'Data/Levels/kcd1_travel/level.pak')
    report_path = mod/'probe-activation-repair.json'
    report_path.unlink(missing_ok=True)  # Detach hard-linked baseline reports.
    report_path.write_text(json.dumps(report, indent=2)+'\n', encoding='utf-8')
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    for key in ('mod', 'source', 'output'):
        parser.add_argument('--'+key, type=Path, required=True)
    print(json.dumps(build(**vars(parser.parse_args())), indent=2))
