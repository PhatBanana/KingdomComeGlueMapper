"""Shared setup migration for the source-selected new-game starting hour."""
import hashlib
from pathlib import Path
import zipfile
from campaign_opening_clock import source_clock, bind
from upgrade_map import read


def upgrade(package, source):
    from setup_gameplay import PROJECT, OPENING, OPENING_CLOCK
    from setup_package_upgrade import rewrite
    from setup_campaign import digest
    if source is None:raise ValueError('KCD1 is required to resolve the opening clock')
    package, source = Path(package), Path(source)
    controller=OPENING_CLOCK['controller']
    with zipfile.ZipFile(source/'Data/Scripts.pak') as z: original=read(z,controller)
    plan=source_clock(original,OPENING_CLOCK['tree'])
    path='Data/gluemappertravel.pak'
    with zipfile.ZipFile(package/path) as z: blob=read(z,PROJECT)
    updated=bind(blob,plan,OPENING)
    changes={}
    if updated!=blob:
        rewrite(package,path,{PROJECT:updated});changes[path]=digest(package/path)
    return changes,dict(**plan,controller=controller,source_sha256=hashlib.sha256(original).hexdigest(),
                        new_game_only=True,runtime_verified=False)
