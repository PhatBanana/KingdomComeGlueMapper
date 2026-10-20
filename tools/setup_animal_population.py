"""Publish the verified ambient animal conversion in clean builds and resume."""
import json
from pathlib import Path
import zipfile

from animal_population import LEVEL_FILES, MANIFEST, VERSION, validate
from build_animal_population_upgrade import LEVEL, TRAVEL, plan
from upgrade_map import digest, read

MODE = 'supported_native_ambient'


def validate_package(package, profiles):
    """Validate the actual emitted graph, including the mounted scheduler alias."""
    package = Path(package)
    with zipfile.ZipFile(package/LEVEL) as archive:
        report = json.loads(read(archive, MANIFEST))
        if report.get('version') != VERSION or report.get('profiles') != list(profiles):
            raise ValueError('Animal conversion version or static world profiles differ')
        files = {name: read(archive, name) for name in LEVEL_FILES}
    validate(files, report)
    import xml.etree.ElementTree as ET
    modid = ET.parse(package/'mod.manifest').findtext('info/modid')
    if not modid:
        raise ValueError('Destination mod ID is missing')
    alias = f'mods/{modid}/data/levels/kcd1_travel/tables/ai/scheduler.xml'.lower()
    with zipfile.ZipFile(package/TRAVEL) as archive:
        matches = [name for name in archive.namelist() if name.lower() == alias]
        if len(matches) != 1 or read(archive, matches[0]) != files['tables/ai/scheduler.xml']:
            raise ValueError('Mounted animal scheduler differs from the level')
    return dict(version=VERSION, mode=MODE, profiles=list(profiles),
                source_signature=report['source_signature'], scheduler_validation=True,
                populations_added=len(report['populations_added']),
                populations_preserved=len(report['populations_preserved']),
                dogs=len(report['dogs']), horses=len(report['horses']), flocks=len(report['flocks']),
                pending=report['pending'], complete=report['complete'], runtime_verified=False)


def upgrade(package, source, target, profiles, notify=lambda *a: None, cancelled=lambda: False):
    """Only called on the private clean-build or transactional resume package.

    The shipped selection is supported ambient contracts, as tested in retail.
    Unsupported master/quest/service bindings remain in the manifest and receipt.
    Missing dependencies inside the selected contracts still stop installation.
    """
    from setup_package_upgrade import rewrite
    if cancelled():
        raise InterruptedError('Cancelled before animal population conversion')
    if source is None or target is None:
        raise ValueError('Both source games are required for animal population conversion')
    package = Path(package)
    notify('Convert native animal populations and schedules', 0, 1, '')
    replacements, _ = plan(source, target, package, profiles)
    # Resolve and validate all selected contracts before replacing either PAK.
    for relative, changes in replacements.items():
        if cancelled():
            raise InterruptedError('Cancelled before publishing animal population conversion')
        if changes:
            rewrite(package, relative, changes)
    report = validate_package(package, profiles)
    files = {relative: digest(package/relative) for relative in replacements}
    notify('Native animal populations and schedules complete', 1, 1,
           f"{len(report['pending'])} unsupported source contracts recorded")
    return files, report
