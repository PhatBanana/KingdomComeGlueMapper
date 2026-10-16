"""Install a validated slice receipt without creating mod backups."""
import argparse
import json
from pathlib import Path
import shutil
import subprocess
from build_playable_slice import digest,verify_baseline,audit


def install(receipt_path, mod):
    receipt_path=Path(receipt_path);mod=Path(mod).resolve()
    receipt=json.loads(receipt_path.read_text(encoding='utf-8'))
    if not receipt.get('ready_for_bounded_playtest') or receipt.get('installed'):
        raise ValueError('Receipt is not a fresh validated slice')
    process=subprocess.run(['tasklist','/FI','IMAGENAME eq KingdomCome.exe','/FO','CSV','/NH'],
                           capture_output=True,text=True,check=True)
    if 'kingdomcome.exe' in process.stdout.lower():raise ValueError('Close the game before installing')
    verify_baseline(mod,receipt['baseline'])
    package=Path(receipt['package']).resolve();prepared=[]
    for relative,expected in receipt['packages'].items():
        source=(package/relative).resolve();destination=(mod/relative).resolve()
        if not source.is_relative_to(package) or not destination.is_relative_to(mod) or source.suffix!='.pak':
            raise ValueError('Invalid package destination')
        if digest(source)!=expected:raise ValueError('Staged package changed: '+relative)
        prepared.append((source,destination,expected))
    audit(package,mod,receipt['people'])
    # This is an installation temp file, not a retained backup. Original mod
    # packages are regenerated from code, as requested by the user.
    for source,destination,expected in prepared:
        destination.parent.mkdir(parents=True,exist_ok=True)
        temp=destination.with_suffix('.installing')
        if temp.exists():raise FileExistsError('Inspect unfinished installation: '+str(temp))
        shutil.copyfile(source,temp)
        if digest(temp)!=expected:raise ValueError('Copy verification failed: '+str(temp))
        temp.replace(destination)
    receipt['installed']=True
    receipt['installed_mod']=str(mod)
    receipt['installed_hashes']={str(p.relative_to(mod)):digest(p) for _,p,_ in prepared}
    receipt_path.write_text(json.dumps(receipt,indent=2),encoding='utf-8')
    print(json.dumps(dict(installed=True,packages=len(prepared),mod=str(mod),runtime_verified=False)))


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--receipt',type=Path,required=True);p.add_argument('--mod',type=Path,required=True)
    a=p.parse_args();install(a.receipt,a.mod)
