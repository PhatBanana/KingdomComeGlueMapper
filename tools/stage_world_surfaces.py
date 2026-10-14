"""Stage a complete experimental surface bake; never overwrite installed files."""
import argparse
import hashlib
import json
from pathlib import Path
import zipfile
from validate_world_surfaces import validate,stem,digest
from world_voxels import configure_environment
from vegetation_gi import POLICY,upgrade_terrain


def stage(scene,output):
    scene,output=Path(scene),Path(output);plan=json.loads((scene/'plan.json').read_text())
    if plan['errors'] or plan['pending_categories']:raise ValueError('Unresolved geometry/category coverage')
    validation=validate(scene)
    if validation['failed'] or validation['validated']!=validation['expected']:raise ValueError('Tile validation failed')
    for name,sha in plan['source_packages'].items():
        if digest(name)!=sha:raise ValueError('Installed source package changed: '+name)
    if output.exists():raise FileExistsError('Use a fresh staging directory')
    output.mkdir(parents=True);packages=output/'packages';packages.mkdir()
    files=[];archive=None
    try:
        for job in plan['tiles']:
            name=stem(job);idx=(scene/'tiles'/(name+'.idx')).read_bytes();vox=(scene/'tiles'/(name+'.vox')).read_bytes()
            if archive is None or archive.fp.tell()+len(idx)+len(vox)>800*1024**2:
                if archive is not None:archive.close()
                path=packages/f'svo-part{len(files)}.pak';files.append(path)
                archive=zipfile.ZipFile(path,'x',compression=zipfile.ZIP_STORED,allowZip64=False)
            archive.writestr('terrain/svo/'+name+'.idx',idx);archive.writestr('terrain/svo/'+name+'.vox',vox)
    finally:
        if archive is not None:archive.close()
    level=Path(plan['level'])/'level.pak';path=packages/'level.pak'
    found=False
    with zipfile.ZipFile(level) as src,zipfile.ZipFile(path,'x',compression=zipfile.ZIP_STORED) as dst:
        for entry in src.infolist():
            blob=src.read(entry)
            if entry.filename.lower()=='mission_mission0.xml':
                blob=configure_environment(blob,surface_channels=True);found=True
            dst.writestr(entry.filename,blob)
    if not found:raise ValueError('Mission configuration missing')
    files.append(path)
    terrain_path=Path(plan['level'])/'terrain.pak'
    terrain_report=None
    if plan.get('vegetation',{}).get('policy')==POLICY:
        path=packages/'terrain.pak'
        with zipfile.ZipFile(terrain_path) as src,zipfile.ZipFile(path,'x',compression=zipfile.ZIP_STORED) as dst:
            for entry in src.infolist():
                blob=src.read(entry)
                if entry.filename.replace('\\','/').lower()=='terrain/terrain.dat':
                    blob,terrain_report=upgrade_terrain(blob)
                dst.writestr(entry.filename,blob)
        if terrain_report is None:raise ValueError('Terrain data missing')
        files.append(path)
    for path in files:
        with zipfile.ZipFile(path) as z:
            if z.testzip():raise ValueError('Package CRC failure: '+path.name)
    report={'scope':'Experimental full static-surface GI with converted vegetation participation',
            'vegetation_gi_upgrade':terrain_report,
            'scene':str(scene.resolve()),'level_dir':plan['level'],'tiles':validation['validated'],
            'installed':False,'runtime_verified':False,'category_policy':plan.get('category_policy',{}),
            'limitations':plan.get('landscape_limitations',[])+['base-material shader approximation; native filtering/vegetation translucency parity not established'],
            'baseline_files':{str(p):digest(p) for p in [level,*([terrain_path] if terrain_report is not None else []),*sorted(Path(plan['level']).glob('svo-part*.pak'))]},
            'packages':{p.name:digest(p) for p in files},
            'installation_note':'Replace the entire previous svo-part package set together with level.pak, after backing it up and closing the game; do not merge shard sets.'}
    (output/'staging.json').write_text(json.dumps(report,indent=2)+'\n')
    return report


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--scene',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    a=p.parse_args();r=stage(a.scene,a.output);print(json.dumps(r,indent=2),flush=True)
