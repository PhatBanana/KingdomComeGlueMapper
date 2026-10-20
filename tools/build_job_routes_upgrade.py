"""Stage native job point-navigation for every existing converted route job.

The installed mod is read-only. Replacement archives are written to --output
for a bounded test; no full world conversion or game launch is performed.
"""
import argparse
import json
from pathlib import Path
import zipfile

from build_horse_trader_test import rewrite
from character_sweeping_routes import resources, upgrade_installed
from upgrade_map import read, digest


def build(source, target, mod, output, source_level='rataje', level='kcd1_travel'):
    if output.exists(): raise FileExistsError('Choose a new staging directory')
    lp='Data/Levels/'+level+'/level.pak'
    travel='Data/gluemappertravel.pak'
    baseline={name:digest(mod/name) for name in (lp,travel)}
    with zipfile.ZipFile(source/'Data/Levels'/source_level/'level.pak') as z:
        graph=read(z,'ubernav.tmm')
    with zipfile.ZipFile(mod/lp) as z:
        files={name:read(z,name) for name in ('objects_mission0.xml','waitinglinks.xml')}
    updated, report=upgrade_installed(files,graph)
    again,_=upgrade_installed(updated,graph)
    if updated != again: raise ValueError('Work route upgrade is not repeatable')
    assets,contract=resources(source,target)
    output.mkdir(parents=True)
    rewrite(mod/lp,output/'package'/lp,updated)
    rewrite(mod/travel,output/'package'/travel,assets)
    changed={lp:set(updated),travel:set(assets)}
    for name in (lp,travel):
        if digest(mod/name)!=baseline[name]: raise ValueError('Baseline changed during staging')
        with zipfile.ZipFile(mod/name) as old,zipfile.ZipFile(output/'package'/name) as new:
            if new.testzip() is not None: raise ValueError('Corrupt staged archive')
            for info in old.infolist():
                if info.filename not in changed[name] and old.read(info)!=new.read(info.filename):
                    raise ValueError('Unrelated archive entry changed: '+info.filename)
    report.update(contract=contract,baseline=baseline,files={name:digest(output/'package'/name) for name in (lp,travel)},
                  other_archive_entries_unchanged=True,installed=False)
    (output/'report.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    return report


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ('source','target','mod','output'): parser.add_argument('--'+name,type=Path,required=True)
    parser.add_argument('--source-level',default='rataje');parser.add_argument('--level',default='kcd1_travel')
    args=parser.parse_args()
    print(json.dumps(build(**vars(args)),indent=2))
