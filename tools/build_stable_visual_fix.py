"""Stage a targeted stable repair without rebuilding the installed world or audio."""
import argparse
import copy
import json
from pathlib import Path
import xml.etree.ElementTree as ET
import zipfile

from build_horse_trader_test import digest, rewrite
from character_person_appearance import build_appearance
from region_travel_services import resolve_merchant
from horse_trader_world import STASH_PREFIX
from merchant_stash import source_stash, stash_assets, apply_stash_placement
from upgrade_map import read, xml


def build(source, target, mod, output):
    if output.exists():
        raise FileExistsError('Choose a fresh output directory')
    output.mkdir(parents=True)
    paths = ('Data/gluemappertravel.pak', 'Data/gluemapper_neuhof_assets.pak',
             'Data/Levels/kcd1_travel/level.pak')
    baseline = {p: digest(mod / p) for p in paths}
    modid = ET.parse(mod / 'mod.manifest').findtext('info/modid')
    table = f'Libs/Tables/Character/CharacterComponent__{modid}.xml'
    with zipfile.ZipFile(mod / paths[0]) as archive:
        components = ET.fromstring(read(archive, table))
    component = next(n for n in components.iter('Component') if n.get('Name') == 'gm_neuhof_zora_root')
    workspace = output / 'assets'
    person = resolve_merchant(source, 'neu_zdena')
    body = build_appearance(source, target, person, 'gm_neuhof_zora', workspace)
    built = ET.parse(workspace / 'Libs/Tables/Character/CharacterComponent__gm_neuhof_zora.xml')
    corrected = built.find('.//Component')
    container = components.find('CharacterComponents')
    container.remove(component)
    container.append(copy.deepcopy(corrected))
    hiding_path = f'Libs/Tables/Character/ClothingHidingGroup__{modid}.xml'
    hiding = ET.parse(workspace / 'Libs/Tables/Character/ClothingHidingGroup__gm_neuhof_zora.xml').getroot()
    with zipfile.ZipFile(mod / paths[0]) as archive:
        if hiding_path in archive.namelist():
            existing = ET.fromstring(read(archive, hiding_path))
            names = {n.get('Name') for n in hiding[0]}
            for row in existing[0]:
                if row.get('Name') not in names:
                    hiding[0].append(copy.deepcopy(row))
    assets = {p.relative_to(workspace).as_posix(): p.read_bytes()
              for p in (workspace / 'objects').rglob('*') if p.is_file()}
    with zipfile.ZipFile(source / 'Data/Levels/rataje/level.pak') as archive:
        mission = ET.fromstring(read(archive, 'objects_mission0.xml'))
    shop = next(e for e in mission.iter('Entity') if e.get('EntityClass') == 'Shop'
                and e.find('Properties') is not None and e.find('Properties').get('iShopId') == '130')
    authored = source_stash(source, shop)
    assets.update(stash_assets(source, authored, STASH_PREFIX))
    with zipfile.ZipFile(mod / paths[2]) as archive:
        mission = ET.fromstring(read(archive, 'objects_mission0.xml'))
    stash = next(e for e in mission if e.get('Name') == 'gm_neuhof_horse_stash')
    before = dict(stash.attrib)
    apply_stash_placement(stash, authored, STASH_PREFIX)
    package = output / 'package'
    rewrite(mod / paths[0], package / paths[0], {table: xml(components), hiding_path: xml(hiding)})
    rewrite(mod / paths[1], package / paths[1], assets)
    rewrite(mod / paths[2], package / paths[2], {'objects_mission0.xml': xml(mission)})
    validation = output / 'validation' / table
    validation.parent.mkdir(parents=True)
    validation.write_bytes(xml(components))
    (output / 'validation' / hiding_path).write_bytes(xml(hiding))
    report = dict(baseline=baseline, body=body, stash_before=before, stash_after=dict(stash.attrib),
                  runtime_verified=False, terrain_changed=False,
                  files={p: digest(package / p) for p in paths})
    (output / 'report.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('source', 'target', 'mod', 'output'):
        parser.add_argument('--' + name, type=Path, required=True)
    args = parser.parse_args()
    build(args.source, args.target, args.mod, args.output)
    print('Stable visual fix staged; installation and in-game verification pending.')
