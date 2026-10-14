"""Stage a reversible raw KCD1 lighting experiment; no texture/voxel conversion.

Entity IDs and level-relative asset paths are adapted only for the existing
converted map. Source defaults, bake schedules, DDS payloads and SVO archive
are retained. KCD2 may reject these source formats; that is the experiment.
"""
import argparse
import copy
import hashlib
import json
from pathlib import Path
import shutil
import xml.etree.ElementTree as ET
import zipfile

from build_horse_trader_test import rewrite, digest
from chairs import inventory
from cooking_pots import vector
from entity_visuals import world_transform
from upgrade_map import read, xml
from world_lighting import defaults, overlay


def build(source, mod, output):
    if output.exists():
        raise FileExistsError('Use a fresh output directory')
    baseline = mod/'Data/Levels/kcd1_travel/level.pak'
    output.mkdir(parents=True)
    shutil.copy2(baseline, output/'baseline-level.pak')
    report = {'mode': 'raw KCD1 payloads; KCD2 compatibility unverified',
              'baseline_sha256': digest(baseline), 'entities': [], 'assets': [],
              'adaptations': ['existing target entity IDs/GUIDs', 'flatten authored world transforms',
                              'level-relative paths and dynamic cubemap folder aliases'],
              'not_converted': ['DDS encoding/dimensions/mips', 'nine source bake times',
                                'reflex radiance samples', 'area flags', 'shadow tiers',
                                'SVO archive and voxel cells', 'source GI and time-of-day configuration']}
    replacements = {}
    with zipfile.ZipFile(source/'Data/Levels/rataje/level.pak') as old, zipfile.ZipFile(baseline) as current, zipfile.ZipFile(source/'Data/Scripts.pak') as scripts:
        all_entities, _, _ = inventory(old, 'EnvironmentLight')
        root = ET.fromstring(read(current, 'objects_mission0.xml'))
        mapped = {e.get('Name')[len('gm_lighting_'):]: e for e in root.iter('Entity') if e.get('Name','').startswith('gm_lighting_')}
        names = {n.lower(): n for n in old.namelist()}
        schemas = {}
        for kind in ('EnvironmentLight', 'ReflexLight'):
            path = next(n for n in scripts.namelist() if n.lower().endswith('/'+kind.lower()+'.lua'))
            schemas[kind] = defaults(read(scripts, path))
        dependencies = set()
        for identity, dest in mapped.items():
            original = all_entities[identity]
            kind = original.get('EntityClass')
            old_id, old_guid = dest.get('EntityId'), dest.get('EntityGuid')
            dest.attrib.clear()
            dest.attrib.update(copy.deepcopy(original.attrib))
            dest.set('EntityId', old_id)
            dest.set('EntityGuid', old_guid)
            # Dynamic probe textures are looked up using the entity's name.
            dest.attrib.pop('ParentId', None)
            dest.attrib.pop('ParentGuid', None)
            pos, rot, scale = world_transform(original, all_entities)
            dest.attrib.update(Pos=vector(pos), Rotate=vector(rot), Scale=vector(scale))
            for child in list(dest):
                dest.remove(child)
            for child in original:
                if child.tag not in ('Properties', 'EntityLinks'):
                    dest.append(copy.deepcopy(child))
            if kind in schemas:
                props = copy.deepcopy(schemas[kind])
                overlay(props, original.find('Properties'))
                dest.append(props)
                if kind == 'ReflexLight':
                    for node, key in [('Options','file_deferred_clip_geom'), ('Projector','texture_Texture')]:
                        path = props.find(node).get(key, '')
                        if path:
                            dependencies.add(path.replace('\\','/').lower())
            elif original.find('Properties') is not None:
                dest.append(copy.deepcopy(original.find('Properties')))
            clip = dest.find('ClipVolume')
            if clip is not None:
                path = clip.get('GeometryFileName').replace('\\','/').lower().replace('%level%/', '')
                replacements[path] = read(old, names[path])
            links = original.find('EntityLinks')
            if links is not None:
                new_links = ET.SubElement(dest, 'EntityLinks')
                for link in links:
                    target = mapped.get(link.get('TargetId'))
                    if target is None:
                        raise ValueError('Unresolved source lighting dependency: '+str(link.attrib))
                    ET.SubElement(new_links, 'Link', Name=link.get('Name',''), TargetId=target.get('EntityId'), TargetGuid=target.get('EntityGuid'))
            report['entities'].append({'source_id': identity, 'name': dest.get('Name'), 'class': kind})
        replacements['objects_mission0.xml'] = xml(root)
        mission = ET.fromstring(read(current, 'mission_mission0.xml'))
        source_mission = ET.fromstring(read(old, 'mission_mission0.xml'))
        for tag in ('Environment', 'TimeOfDay'):
            existing = mission.find(tag)
            if existing is not None:
                mission.remove(existing)
            mission.append(copy.deepcopy(source_mission.find(tag)))
        replacements['mission_mission0.xml'] = xml(mission)
        rewrite(baseline, output/'level.pak', replacements)
    # Keep every DDS/mip member byte-for-byte and retain the source paths.
    # The folder alias is necessary because KCD2 derives dynamic paths from
    # the currently loaded level; no missing target time samples are invented.
    assets = {}
    for path in sorted((source/'Data').glob('*.pak')):
        if not path.name.startswith(('Textures', 'Objects', 'Buildings')):
            continue
        with zipfile.ZipFile(path) as archive:
            for name in archive.namelist():
                key = name.replace('\\','/').lower()
                if key.startswith('textures/cubemaps/rataje/') or key in dependencies:
                    blob = read(archive, name)
                    if key in assets and assets[key] != blob:
                        raise ValueError('Ambiguous source asset override: '+key)
                    assets[key] = blob
    missing = dependencies-assets.keys()
    if missing:
        raise ValueError('Missing source dependencies: '+str(sorted(missing)))
    with zipfile.ZipFile(output/'gluemapper_raw_lighting.pak', 'x', zipfile.ZIP_STORED) as archive:
        for name, blob in sorted(assets.items()):
            archive.writestr(name, blob)
            alias = name.replace('textures/cubemaps/rataje/', 'textures/cubemaps/kcd1_travel/')
            if alias != name:
                archive.writestr(alias, blob)
            report['assets'].append({'path': name, 'alias': alias, 'sha256': hashlib.sha256(blob).hexdigest(), 'bytes': len(blob)})
    shutil.copy2(source/'Data/Levels/rataje/svo.pak', output/'svo.pak')
    report['source_svo_sha256'] = digest(source/'Data/Levels/rataje/svo.pak')
    report['staged_svo_sha256'] = digest(output/'svo.pak')
    if report['source_svo_sha256'] != report['staged_svo_sha256']:
        raise ValueError('Raw SVO copy changed')
    with zipfile.ZipFile(output/'gluemapper_raw_lighting.pak') as archive:
        for record in report['assets']:
            for name in set((record['path'], record['alias'])):
                if hashlib.sha256(read(archive, name)).hexdigest() != record['sha256']:
                    raise ValueError('Raw lighting payload changed: '+name)
    report['staged_level_sha256'] = digest(output/'level.pak')
    (output/'report.json').write_text(json.dumps(report, indent=2)+'\n')
    print(f"Staged {len(mapped)} source lighting entities and {len(assets)} raw asset members; SVO copy hash matches", flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--mod', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    build(args.source, args.mod, args.output)
