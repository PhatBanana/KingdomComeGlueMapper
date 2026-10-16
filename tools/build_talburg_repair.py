"""Stage the reviewed Talburg bed and detached tower LOD repairs."""
import argparse
from contextlib import ExitStack
import json
from pathlib import Path
import xml.etree.ElementTree as ET
import zipfile
from build_horse_trader_test import digest, rewrite
from entity_visuals import collect_visuals, TALBURG_BEDS
from region_travel import guid
from static_assets import asset_pack
from static_lod_transforms import align_external_lod
from upgrade_map import read, xml
from world_beds import convert, LEVEL_FILES, ANIMATIONS, SCHEDULER


def build(library, mod, output):
    if output.exists():
        raise FileExistsError(output)
    output.mkdir(parents=True)
    package = output/'package'
    level = 'Data/Levels/kcd1_travel/level.pak'
    travel = 'Data/gluemappertravel.pak'
    lods = 'Data/gluemapper_world_lods_000.pak'
    baseline = {p: digest(mod/p) for p in (level, travel, lods)}
    changes = {}
    with ExitStack() as stack:
        source = stack.enter_context(zipfile.ZipFile(library/'KingdomComeDeliverance/Data/Levels/rataje/level.pak'))
        native = stack.enter_context(zipfile.ZipFile(library/'KingdomComeDeliverance2/Data/Levels/trosecko/level.pak'))
        old = stack.enter_context(zipfile.ZipFile(library/'KingdomComeDeliverance/Data/GameData.pak'))
        new = stack.enter_context(zipfile.ZipFile(library/'KingdomComeDeliverance2/Data/IPL_GameData.pak'))
        installed = stack.enter_context(zipfile.ZipFile(mod/level))
        files = {n: read(installed, n) for n in LEVEL_FILES}
        root = ET.fromstring(files['objects_mission0.xml'])
        visuals, _ = collect_visuals(source, library)
        selected = [v for v in visuals if v['source_id'] in TALBURG_BEDS]
        if {v['source_id'] for v in selected} != TALBURG_BEDS:
            raise ValueError('Missing reviewed source bed')
        _, emitted, _, mesh = asset_pack(stack, library, 'gluebuild/talburg_repair')
        for v in selected:
            node = v['entity']
            if any(e.get('Name') == node.get('Name') for e in root):
                raise ValueError('Bed visual already installed')
            path = 'gluebuild/talburg_repair/bed_' + v['source_id'] + '.cgf'
            emitted[path] = mesh(v['model'])
            node.set('Geometry', path)
            root.append(node)
        files['objects_mission0.xml'] = xml(root)
        updated, report = convert(files, source, native, read(old, 'Libs/SmartObjects.xml'),
                                  read(new, 'Libs/SmartObjects.xml'), guid, source_ids=TALBURG_BEDS)
        if report['converted'] != 4:
            raise ValueError('Expected four new sleep contracts')
        changes[level] = updated
        modid = ET.parse(mod/'mod.manifest').findtext('info/modid')
        changes[travel] = {f'Mods/{modid}/Data/Levels/kcd1_travel/{n}': updated[n] for n in (ANIMATIONS, SCHEDULER)}
        basepak = stack.enter_context(zipfile.ZipFile(mod/'Data/kingdomcomegluemapper_world_000.pak'))
        lodpak = stack.enter_context(zipfile.ZipFile(mod/lods))
        base = read(basepak, 'gluebuild/setup_buildings/mesh1770.cgf')
        repaired, evidence = {}, []
        for i in (1, 2, 3):
            name = f'gluebuild/setup_buildings/mesh1770_lod{i}.cgf'
            payload, proof = align_external_lod(base, read(lodpak, name))
            if proof is None:
                raise ValueError('Tower LOD no longer matches reviewed diagnosis: ' + name)
            repaired[name] = payload
            evidence.append(dict(path=name, **proof))
        changes[lods] = repaired
        asset_path = package/'Data/gluemapper_talburg_repair.pak'
        asset_path.parent.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(asset_path, 'x', zipfile.ZIP_STORED) as dest:
            for name, blob in emitted.items():
                dest.writestr(name, blob)
    preserved = {}
    for relative, replacements in changes.items():
        rewrite(mod/relative, package/relative, replacements)
        with zipfile.ZipFile(mod/relative) as a, zipfile.ZipFile(package/relative) as b:
            before = {i.filename: (i.CRC, i.file_size) for i in a.infolist() if i.filename not in replacements}
            after = {i.filename: (i.CRC, i.file_size) for i in b.infolist() if i.filename not in replacements}
            if before != after or any(read(b,n) != payload for n,payload in replacements.items()):
                raise ValueError('Archive preservation check failed: ' + relative)
            preserved[relative] = len(before)
    receipt = dict(package=str(package.resolve()), baseline=baseline,
                   packages={str(p.relative_to(package)).replace('\\','/'): digest(p) for p in package.rglob('*.pak')},
                   beds=report, tower=evidence, unrelated_entries_preserved=preserved,
                   installed=False, runtime_verified=False)
    (output/'repair.json').write_text(json.dumps(receipt, indent=2)+'\n', encoding='utf-8')
    print(json.dumps(dict(packages=len(receipt['packages']), beds=report['converted'], tower_lods=len(evidence), preserved=preserved)))


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    for name in ('library', 'mod', 'output'):
        p.add_argument('--'+name, type=Path, required=True)
    build(**vars(p.parse_args()))
