"""Shared, versioned recipe for clean launcher and development builds.

Run against a private freshly combined world/travel package. The historical
builders remain the implementation; this module supplies their order and applies
their verified outputs without mutating an installed mod or a hard-linked base.
"""
import argparse
import json
from pathlib import Path
import re
import shutil

from setup_campaign import RECEIPT, digest, verify_package

VERSION = 1
STAGE_LABELS = ('Open Talburg and Skalitz test gates', 'World containers, loot and keys', 'Neuhof horse shop and starter dialogue', 'Test supplies and getting started', 'Rattay smithing stations and coal repair', 'Smithing warning dialogue', 'Church altar prayer', 'Workshop recipes and resources', 'KCD1 New Game menu')
REVIEWED_BLEND_MODELS = (
    'objects/buildings/houses/modular/6x15/6x15_roof_p_03_flipped.cgf',
    'objects/buildings/houses/modular/6x15/6x15_basefloor_p_2_flipped.cgf',
)


def reviewed_blend_mesh(name):
    return re.sub(r'_lod[1-6](?=\.cgf$)', '', (name or '').replace('\\', '/').lower()) in REVIEWED_BLEND_MODELS


def apply_overlay(package, overlay):
    """Replace files, never write through links to an older build."""
    package, overlay = Path(package).resolve(), Path(overlay).resolve()
    files = sorted(p for p in overlay.rglob('*') if p.is_file())
    if not files:
        raise ValueError('Builder produced no package: ' + str(overlay))
    changed = {}
    for source in files:
        relative = source.relative_to(overlay)
        destination = (package / relative).resolve()
        if source.is_symlink() or not destination.is_relative_to(package):
            raise ValueError('Unsafe builder output: ' + str(relative))
        destination.parent.mkdir(parents=True, exist_ok=True)
        pending = destination.with_name(destination.name + '.recipe-pending')
        shutil.copy2(source, pending)
        expected = digest(source)
        if digest(pending) != expected:
            raise ValueError('Builder output copy failed: ' + str(relative))
        pending.replace(destination)
        changed[relative.as_posix()] = expected
    return changed


def build_containers(source, target, package, output):
    """Connect the existing loot importer and full-world container builder."""
    from container_audit import audit
    from container_items import build as items
    from build_world_containers import build as containers
    from build_horse_trader_test import rewrite
    import zipfile
    from upgrade_map import read

    output.mkdir(parents=True)
    inventory = audit(source, target)
    identifiers = {item for group in inventory['inventories'].values()
                   for item in group.get('item_dependencies', [])}
    items(source, target, package, output/'items', identifiers)
    staged = output/'containers'
    containers(source, target, package/'Data/Levels/kcd1_travel/level.pak', output/'items', staged)
    overlay = output/'package';overlay.mkdir()
    (staged/'Data').rename(overlay/'Data')
    # The container builder's localization PAK contains an additional table.
    # Merge that table; never replace the menu, travel, or smithing strings.
    with zipfile.ZipFile(staged/'Localization/English_xml.pak') as archive:
        strings = {n:read(archive,n) for n in archive.namelist()}
    rewrite(package/'Localization/English_xml.pak', overlay/'Localization/English_xml.pak', strings)


def run(source, target, package, work, notify=lambda *a: None, cancelled=lambda: False):
    from game_paths import GameLibrary
    from build_open_test_gates import build as gates
    from build_horse_trader_test import build as horses
    from build_debug_supplies import build as supplies
    from build_rattay_smithery import build as smithery
    from build_smithing_voice import build as voice
    from build_church_prayer import build as prayer
    from build_workshop_test import build as workshop
    from campaign_menu_stage import add_to_package

    source, target, package, work = map(lambda p: Path(p).resolve(), (source, target, package, work))
    receipt = verify_package(package, hashes=False)
    if receipt.get('build_recipe'):
        raise ValueError('Recipe already applied; start a new clean build or install this package.')
    if package.is_relative_to(source) or package.is_relative_to(target):
        raise ValueError('Build recipe requires a private package outside the game installations.')
    work.mkdir(parents=True, exist_ok=False)
    paths = work / 'game-paths.json'
    paths.write_text(json.dumps(dict(schema=1, kcd1=str(source), kcd2=str(target), build=str(work/'conversion'))))
    library = GameLibrary(paths)
    steps = (
        (STAGE_LABELS[0], lambda out: gates(package, out, source=source), '.'),
        (STAGE_LABELS[1], lambda out: build_containers(source, target, package, out), 'package'),
        (STAGE_LABELS[2], lambda out: horses(source, target, package, out), 'package'),
        (STAGE_LABELS[3], lambda out: supplies(source, target, package, out), 'package'),
        (STAGE_LABELS[4], lambda out: smithery(library, package, out), 'package'),
        (STAGE_LABELS[5], lambda out: voice(target, package, out), 'package'),
        (STAGE_LABELS[6], lambda out: prayer(library, package, out, game=target), 'package'),
        (STAGE_LABELS[7], lambda out: workshop(target, package, out), 'package'),
    )
    report = dict(version=VERSION, status='building', steps=[], runtime_verified=False)
    if cancelled():
        raise InterruptedError('Build cancelled before gameplay recipe')
    # Mark the private package before changing it: a failed/interrupted recipe
    # must not be applied again on top of its own partially modified output.
    receipt['build_recipe'] = report
    pending = package / (RECEIPT+'.pending')
    pending.write_text(json.dumps(receipt, indent=2))
    pending.replace(package/RECEIPT)
    for index, (label, build, folder) in enumerate(steps):
        if cancelled():
            raise InterruptedError('Build cancelled before ' + label)
        notify(label, index, len(steps)+1, '')
        output = work / f'{index+1:02d}'
        build(output)
        overlay = output / folder
        # Gate builder also writes its evidence next to Data, not into the mod.
        if folder == '.':
            staged = output / 'package'
            staged.mkdir()
            (output/'Data').rename(staged/'Data')
            overlay = staged
        changed = apply_overlay(package, overlay)
        receipt['files'].update(changed)
        report['steps'].append(dict(name=label, files=changed))
        pending = package / (RECEIPT+'.pending')
        pending.write_text(json.dumps(receipt, indent=2))
        pending.replace(package/RECEIPT)
    if cancelled():
        raise InterruptedError('Build cancelled before menu registration')
    notify(STAGE_LABELS[8], len(steps), len(steps)+1, '')
    add_to_package(target, package)
    report['status'] = 'complete'
    report['steps'].append(dict(name='KCD1 New Game menu'))
    receipt = verify_package(package, hashes=False)
    receipt['build_recipe'] = report
    pending = package / (RECEIPT+'.pending')
    pending.write_text(json.dumps(receipt, indent=2))
    pending.replace(package/RECEIPT)
    (work/'report.json').write_text(json.dumps(report, indent=2))
    notify('Gameplay recipe complete', len(steps)+1, len(steps)+1, '')
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    for key in ('source', 'target', 'package', 'work'):
        parser.add_argument('--'+key, type=Path, required=True)
    run(**vars(parser.parse_args()))
