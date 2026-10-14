"""Install a verified complete lighting package set with recoverable rollback."""
import argparse
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import zipfile
from validate_world_surfaces import digest


def game_running():
    if os.name!='nt':return False
    result=subprocess.run(['powershell.exe','-NoProfile','-Command',
        'if (Get-Process KingdomCome -ErrorAction SilentlyContinue) { exit 1 }'],capture_output=True)
    return result.returncode!=0


def install(staging,recovery):
    staging,recovery=Path(staging),Path(recovery)
    report=json.loads((staging/'staging.json').read_text());level=Path(report['level_dir'])
    if game_running():raise RuntimeError('Close KingdomCome before installing lighting')
    if report.get('installed'):raise ValueError('Already marked installed')
    packages=report['packages'];baseline=report['baseline_files']
    if not {'level.pak','terrain.pak'}.issubset(packages):raise ValueError('Missing mission/vegetation settings')
    if any(not re.fullmatch(r'(level|terrain|svo-part\d+)\.pak',name) for name in packages):raise ValueError('Unexpected package name')
    expected={Path(p).name for p in baseline}
    if any(Path(p).parent.resolve()!=level.resolve() for p in baseline):raise ValueError('Baseline outside level')
    if {p.name for p in level.glob('svo-part*.pak')}!={n for n in expected if n.startswith('svo-part')}:
        raise ValueError('Installed shard set changed')
    for path,sha in baseline.items():
        if digest(path)!=sha:raise ValueError('Installed package changed: '+path)
    entries=set()
    for name,sha in packages.items():
        path=staging/'packages'/name
        if digest(path)!=sha:raise ValueError('Staged checksum mismatch: '+name)
        with zipfile.ZipFile(path) as z:
            if z.testzip():raise ValueError('Staged CRC failure: '+name)
            if name.startswith('svo-part'):
                for member in z.namelist():
                    if member in entries:raise ValueError('Duplicate SVO tile entry')
                    entries.add(member)
    if len(entries)!=report['tiles']*2:raise ValueError('Incomplete tile entry count')
    recovery.mkdir(parents=True,exist_ok=False)
    backup=recovery/'previous';backup.mkdir()
    for path in baseline:
        target=backup/Path(path).name
        try:target.hardlink_to(Path(path))
        except OSError:shutil.copy2(path,target)
    journal={'status':'prepared','level_dir':str(level),'staging':str(staging.resolve()),
             'baseline_files':baseline,'installed_files':packages,'runtime_verified':False}
    receipt=recovery/'installation.json';receipt.write_text(json.dumps(journal,indent=2)+'\n')
    incoming=level/('.lighting-install-'+recovery.name)
    incoming.mkdir(exist_ok=False)
    changed=[]
    try:
        for name,sha in packages.items():
            shutil.copy2(staging/'packages'/name,incoming/name)
            if digest(incoming/name)!=sha:raise ValueError('Copy verification failed')
        if game_running():raise RuntimeError('Game started during preparation; installation cancelled')
        for path,sha in baseline.items():
            if digest(path)!=sha:raise ValueError('Installed package changed during preparation')
        for name in packages:
            (incoming/name).replace(level/name);changed.append(name)
        for name in expected-set(packages):
            if not name.startswith('svo-part'):raise ValueError('Refusing to remove non-shard')
            (level/name).unlink();changed.append(name)
        for name,sha in packages.items():
            if digest(level/name)!=sha:raise ValueError('Installed verification failed')
        journal['status']='installed_verified'
    except Exception:
        for name in reversed(changed):
            if (backup/name).exists():
                shutil.copy2(backup/name,incoming/name);(incoming/name).replace(level/name)
            elif name in packages:(level/name).unlink(missing_ok=True)
        journal['status']='rolled_back'
        receipt.write_text(json.dumps(journal,indent=2)+'\n')
        raise
    finally:
        # Only the exact directory created above, containing our staged copies.
        for path in incoming.iterdir():path.unlink()
        incoming.rmdir()
    receipt.write_text(json.dumps(journal,indent=2)+'\n')
    return journal


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--staging',type=Path,required=True);p.add_argument('--recovery',type=Path,required=True)
    a=p.parse_args();print(json.dumps(install(a.staging,a.recovery),indent=2),flush=True)
