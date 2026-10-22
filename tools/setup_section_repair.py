"""Repair stale derived sections without rerunning unrelated gameplay builders."""
import json
from pathlib import Path
import zipfile

from lod_ratio_metadata import MARKER, validate_marker, upgrade_package
from setup_campaign import RECEIPT, verify_package
from upgrade_map import read


def stale_sections(package):
    level = Path(package) / 'Data/Levels/kcd1_travel'
    with zipfile.ZipFile(level / 'level.pak') as archive:
        if MARKER not in archive.namelist():
            return []  # An older, unfinished encoding stage belongs to finalize.
        marker = json.loads(read(archive, MARKER))
        hlod = read(archive, 'terrain/hlods.dat')
    with zipfile.ZipFile(level / 'terrain.pak') as archive:
        terrain = read(archive, 'terrain/terrain.dat')
    try:
        validate_marker(terrain, hlod, marker)
    except ValueError:
        return ['lod_ratios']
    return []


def repair(package, *, repair_roots=(), notify=lambda *a: None, cancelled=lambda: False):
    """Run inside update_private_package; certify only the changed section files."""
    package = Path(package)
    receipt = verify_package(package)
    if not stale_sections(package):
        return receipt
    if cancelled():
        raise InterruptedError('Cancelled before section repair')
    notify('Repairing stale LOD validation', 0, 1, 'Reusing verified saved world section')
    files, report = upgrade_package(package, repair_roots=repair_roots)
    upgrade_package(package, validate_only=True)
    if cancelled():
        raise InterruptedError('Cancelled before recording section repair')
    receipt['files'].update(files)
    receipt['lod_ratio_metadata'] = report
    receipt['section_repairs'] = dict(lod_ratios=report['recovery'])
    pending = package / (RECEIPT + '.pending')
    pending.write_text(json.dumps(receipt, indent=2), encoding='utf-8')
    pending.replace(package / RECEIPT)
    result = verify_package(package)
    notify('Repaired stale LOD validation', 1, 1, 'Other completed sections retained')
    return result
