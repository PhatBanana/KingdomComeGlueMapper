"""Bounded migration of completed setup packages; never re-run world conversion."""
import copy
import json
import shutil
import zipfile
from pathlib import Path
import xml.etree.ElementTree as ET
from upgrade_map import read, xml
from setup_campaign import RECEIPT, MOD_ID, digest, verify_package


def eligible(receipt):
    from build_recipe import VERSION, require_current
    from campaign_start_policy import POLICY
    candidate = copy.deepcopy(receipt)
    report = candidate.get('build_recipe', {})
    if report.get('version') not in (3, 4, 5, 6, VERSION):
        raise ValueError('Saved gameplay recipe is not supported for migration')
    report['version'] = VERSION
    report.setdefault('content_validation', {})['start_policy'] = POLICY
    candidate['single_playable_world'] = True
    require_current(candidate)


def rewrite(package, relative, replacements, remove=lambda name: False):
    path = package/relative
    pending = path.with_suffix('.upgrade-pending')
    with zipfile.ZipFile(path) as source, zipfile.ZipFile(pending, 'x', zipfile.ZIP_STORED, allowZip64=False) as out:
        for entry in source.infolist():
            if not remove(entry.filename):
                out.writestr(entry, replacements.get(entry.filename, read(source, entry.filename)))
    with zipfile.ZipFile(pending) as check:
        if check.testzip() is not None:
            raise ValueError('Package migration archive verification failed')
    pending.replace(path)


def finalize(package):
    """Called only on a private build or the transactional resume staging copy."""
    from campaign_start_policy import gate_start
    from region_travel_companions import remove_horse_recovery
    from smart_area_registration import reconcile
    from setup_gameplay import PROJECT, OPENING, validate
    from build_recipe import VERSION
    package = Path(package).resolve()
    receipt = verify_package(package)
    eligible(receipt)
    if receipt.get('travel_bridge', {}).get('destination') != 'kcd1_travel':
        raise ValueError('Expected the established playable travel world')
    changes = {}
    travel = 'Data/gluemappertravel.pak'
    with zipfile.ZipFile(package/travel) as z:
        player = 'Scripts/Entities/actor/player.lua'
        changes = {PROJECT: gate_start(read(z, PROJECT), OPENING), player: remove_horse_recovery(read(z, player))}
    rewrite(package, travel, changes)
    level = 'Data/Levels/kcd1_travel/level.pak'
    with zipfile.ZipFile(package/level) as z:
        metadata, added = reconcile(read(z, 'whdata_0'), read(z, 'objects_mission0.xml'))
        from area_geometry_contract import normalize
        missions = [read(z, n) for n in z.namelist() if n.lower() == 'objects_mission0.xml'
                    or n.lower().startswith('layers/') and n.lower().endswith('.xml')]
        geometry, removed = normalize(read(z, 'triggerareas.fubar'), missions)
        normalize(geometry, missions, validate_only=True)
        from skalitz_outer_gates import normalize as correct_gates
        gates, gate_report = correct_gates({n:read(z,n) for n in ('terrain/hlods.dat','terrain/hlods.xml')})
    rewrite(package, level, {'whdata_0': metadata, 'triggerareas.fubar': geometry, **gates})
    runtime = f'Data/{MOD_ID}.pak'
    table = f'Libs/Tables/level__{MOD_ID}.xml'
    with zipfile.ZipFile(package/runtime) as z:
        root = ET.fromstring(read(z, table))
    playable = [row for row in root.iter() if row.get('LevelName') == 'kcd1_travel']
    if len(playable) != 1 or playable[0].get('LevelId') != '1001':
        raise ValueError('Playable travel level identity is missing or changed')
    for parent in root.iter():
        for row in list(parent):
            if row.get('LevelName') == 'kcd1_rataje':
                if row.get('LevelId') != '1000':
                    raise ValueError('Unexpected intermediate level identity')
                parent.remove(row)
    rewrite(package, runtime, {table: xml(root)}, lambda n: '/data/levels/kcd1_rataje/' in n.lower())
    intermediate = (package/'Data/Levels/kcd1_rataje').resolve()
    if not intermediate.is_relative_to(package) or intermediate == package:
        raise ValueError('Intermediate world is outside the private package')
    if intermediate.exists():
        shutil.rmtree(intermediate)
    receipt['single_playable_world'] = True
    receipt['build_recipe']['content_validation'] = validate(package)
    receipt['build_recipe']['version'] = VERSION
    receipt['package_upgrade'] = dict(version=2, registered_smart_areas=added,
        removed_duplicate_smart_geometry=removed, skalitz_outer_gates=gate_report, runtime_verified=False)
    if 'baking' in receipt:
        receipt['baking']['levels'] = [r for r in receipt['baking'].get('levels', []) if r.get('level') == 'kcd1_travel']
    receipt['files'] = {n:h for n,h in receipt['files'].items() if not n.startswith('Data/Levels/kcd1_rataje/')}
    for name in (travel, level, runtime):
        receipt['files'][name] = digest(package/name)
    pending = package/(RECEIPT+'.pending')
    pending.write_text(json.dumps(receipt, indent=2), encoding='utf-8')
    pending.replace(package/RECEIPT)
    verify_package(package)
    return receipt
