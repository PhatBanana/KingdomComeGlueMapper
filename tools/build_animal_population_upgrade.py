"""Stage the general native animal conversion on an existing assembled world.

This writes an overlay for the same mod. It does not install it, run the game,
or change unrelated world records. Use --allow-partial only for a bounded test
of the supported ambient contracts; all unsupported records remain in report.json.
"""
import argparse
from collections import Counter
import json
from pathlib import Path
import xml.etree.ElementTree as E
import zipfile

from animal_population import LEVEL_FILES, MANIFEST, convert, validate
from area_geometry_contract import normalize
from build_horse_trader_test import rewrite
from upgrade_map import read, digest

LEVEL = 'Data/Levels/kcd1_travel/level.pak'
TRAVEL = 'Data/gluemappertravel.pak'


def plan(source, target, mod, profiles=()):
    """Shared planning API for a clean assembled build or an existing package."""
    source, target, mod = map(Path, (source, target, mod))
    modid = E.parse(mod/'mod.manifest').findtext('info/modid')
    if not modid: raise ValueError('Destination mod ID is missing')
    with zipfile.ZipFile(mod/LEVEL) as z:
        names = {n.lower(): n for n in z.namelist()}
        if len(names) != len(z.namelist()): raise ValueError('Ambiguous level archive paths')
        files = {n: read(z, names[n]) for n in LEVEL_FILES}
        if MANIFEST in names: files[MANIFEST] = read(z, names[MANIFEST])
        changed, report = convert(files, source, target, profiles)
        missions = [changed['objects_mission0.xml']] + [read(z,n) for n in z.namelist()
                   if n.lower().startswith('layers/') and n.lower().endswith('.xml')]
        normalize(changed['triggerareas.fubar'], missions, validate_only=True)
        level_changes = {names.get(n, n): b for n,b in changed.items() if b != files.get(n)}
    alias = f'Mods/{modid}/Data/Levels/kcd1_travel/tables/ai/scheduler.xml'
    with zipfile.ZipFile(mod/TRAVEL) as z:
        matches = [n for n in z.namelist() if n.lower() == alias.lower()]
        if len(matches) != 1: raise ValueError('Missing or ambiguous mounted animal scheduler alias')
        original = read(z, matches[0])
        if original != files['tables/ai/scheduler.xml']:
            raise ValueError('Mounted scheduler differs from the level; repair the baseline first')
        travel_changes = {matches[0]: changed['tables/ai/scheduler.xml']} if original != changed['tables/ai/scheduler.xml'] else {}
    return {LEVEL:level_changes, TRAVEL:travel_changes}, report


def verify_overlay(mod, package, replacements):
    """Verify every unchanged member, including quests, lighting and geometry."""
    evidence = {}
    for relative, changes in replacements.items():
        with zipfile.ZipFile(mod/relative) as src, zipfile.ZipFile(package/relative) as dst:
            if len(set(dst.namelist())) != len(dst.namelist()): raise ValueError('Duplicate staged archive member')
            if set(dst.namelist()) != set(src.namelist()) | set(changes):
                raise ValueError('Animal conversion removed archive members')
            untouched = 0
            for member in src.infolist():
                if member.filename not in changes:
                    actual = dst.getinfo(member.filename)
                    if (member.CRC, member.file_size) != (actual.CRC, actual.file_size):
                        raise ValueError('Animal conversion changed an unrelated resource: ' + member.filename)
                    untouched += 1
            for name, blob in changes.items():
                if read(dst, name) != blob: raise ValueError('Animal conversion replacement mismatch: ' + name)
            if dst.testzip(): raise ValueError('Staged animal archive failed CRC validation')
            evidence[relative] = dict(unchanged_members=untouched, changed_members=len(changes),
                                     sha256=digest(package/relative))
    return evidence


def build(source, target, mod, output, profiles=(), *, allow_partial=False):
    source, target, mod, output = map(Path, (source, target, mod, output))
    if output.exists(): raise FileExistsError('Choose a new animal staging directory')
    output.mkdir(parents=True)
    originals = {n:digest(mod/n) for n in (LEVEL,TRAVEL)}
    print('Resolving source animal placements and native KCD2 dependencies', flush=True)
    changes, report = plan(source,target,mod,profiles)
    (output/'report.json').write_text(json.dumps(report,indent=2), encoding='utf-8')
    if report['pending'] and not allow_partial:
        raise ValueError(f"{len(report['pending'])} source animal contracts require adapters; see report.json. "
                         'Use --allow-partial only to stage the supported ambient animals for testing.')
    package = output/'package'
    for relative, replacements in changes.items():
        print('Staging ' + relative, flush=True)
        rewrite(mod/relative, package/relative, replacements)
    with zipfile.ZipFile(package/LEVEL) as z:
        validate({n:read(z,n) for n in LEVEL_FILES}, report)
    report['archive_validation'] = verify_overlay(mod,package,changes)
    report['baseline_sha256'] = originals
    if {n:digest(mod/n) for n in originals} != originals:
        raise ValueError('Installed baseline changed during staging; discard this overlay')
    report['source_package_unchanged'] = True
    report['runtime_verified'] = False
    (output/'report.json').write_text(json.dumps(report,indent=2), encoding='utf-8')
    return report


if __name__ == '__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    for key in ('source','target','mod','output'): parser.add_argument('--'+key,type=Path,required=True)
    parser.add_argument('--profile',action='append',default=[])
    parser.add_argument('--allow-partial',action='store_true')
    args=parser.parse_args()
    report=build(args.source,args.target,args.mod,args.output,args.profile,allow_partial=args.allow_partial)
    print(json.dumps(dict(populations=dict(Counter(x['species'] for x in report['populations_added'])),
        dogs=len(report['dogs']), horses=len(report['horses']), flocks=len(report['flocks']),
        pending=len(report['pending']), runtime_verified=False),indent=2))
