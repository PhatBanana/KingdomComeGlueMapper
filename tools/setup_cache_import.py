"""Import completed older build outputs without claiming new input compatibility."""
import argparse
import json
import os
from pathlib import Path
import re

from setup_build_cache import Cache, file_hash, fingerprint, root
from setup_campaign import RECEIPT
from setup_resume import job_lock


def import_build(build, workspace, cancelled=lambda: False):
    """Verify saved output hashes and copy lighting/shaders; never copy world data."""
    with job_lock(Path(build).resolve()):
        return _import_build(build,workspace,cancelled)


def _import_build(build, workspace, cancelled):
    build=Path(build).resolve();workspace=Path(workspace).resolve()
    config=json.loads((build/'job.json').read_text(encoding='utf-8'))
    for game in ('kcd1','kcd2','mod_tools'):
        if config.get(game) and workspace.is_relative_to(Path(config[game]).resolve()):
            raise ValueError('Choose a cache workspace outside game/tool installations')
    package=build/'package/map'
    if not package.is_dir():package=build/'map-job/package'
    receipt=json.loads((package/RECEIPT).read_text(encoding='utf-8'))
    files={};levels={};bake=receipt.get('baking',{})

    def recorded(path):
        relative=path.relative_to(package).as_posix()
        expected=receipt['files'].get(relative)
        if not expected or file_hash(path)!=expected:
            raise ValueError('Older build output changed or is unrecorded: '+relative)
        return expected

    # Staging reports supply the vegetation conversion policy. The final receipt
    # supplies the authoritative installed shard set and hashes.
    staging=[]
    for path in (build/'baking').rglob('staging.json'):
        try:staging.append(json.loads(path.read_text(encoding='utf-8')))
        except (OSError,ValueError):continue
    for item in bake.get('levels',[]):
        name=item['level']
        if not re.fullmatch(r'[A-Za-z0-9_-]+',name):raise ValueError('Invalid saved level name')
        folder=package/'Data/Levels'/name
        shards=sorted(folder.glob('svo-part*.pak'))
        if not shards:raise ValueError('Saved lighting shards are missing: '+name)
        expected={p.name:recorded(p) for p in shards}
        recorded_names={Path(n).name for n in receipt['files']
                        if n.startswith('Data/Levels/'+name+'/svo-part') and n.endswith('.pak')}
        if set(expected)!=recorded_names:raise ValueError('Incomplete saved lighting shard set')
        candidates=[r for r in staging if Path(r.get('level_dir','')).name==name
                    and r.get('tiles')==item['tiles']
                    and {n:h for n,h in r.get('packages',{}).items() if n.startswith('svo-part')}==expected]
        if 'vegetation_gi_upgrade' in item:report=item
        elif candidates:report=candidates[-1]
        else:raise ValueError('No matching completed lighting staging report for '+name)
        levels[name]={k:report.get(k) for k in ('tiles','limitations','vegetation_gi_upgrade')}
        files.update({'lighting/'+name+'/'+p.name:p for p in shards})
    shaders=package/'ShaderCache'
    has_shaders=(shaders/'shader-build.json').is_file()
    if has_shaders:
        from setup_shaders import validate, ARCHIVES
        validate(shaders)
        for relative in ['shader-build.json',*('Engine/'+n for n in ARCHIVES)]:
            p=shaders/relative;recorded(p);files['shaders/'+relative]=p
    if not files:raise ValueError('This build has no completed lighting or shader outputs to import')
    metadata=dict(source=str(build),preset=bake.get('preset','none'),levels=levels,
                  shaders=has_shaders,input_compatibility='requires_user_choice')
    identity=fingerprint(dict(metadata=metadata,outputs={n:file_hash(p) for n,p in files.items()}))
    cache=Cache(workspace/'cache/imported')
    with job_lock(cache.folder):
        if not cache.lookup(identity):cache.publish(identity,files,metadata,cancelled)
    return dict(id=identity,**metadata)


def candidates(workspace, preset):
    """Cheap UI inventory. All output hashes are checked again before use."""
    folder=Path(workspace)/'cache/imported';result=[]
    for pointer in sorted(folder.glob('*.json')):
        if not re.fullmatch('[a-f0-9]{64}',pointer.stem):continue
        try:
            name=json.loads(pointer.read_text())['entry']
            if Path(name).name!=name or not name.startswith(pointer.stem+'-'):continue
            report=json.loads((folder/name/'manifest.json').read_text())
            meta=report['metadata']
            if report['key']!=pointer.stem:continue
            if meta.get('shaders') or (meta.get('levels') and meta.get('preset')==preset):
                result.append(dict(id=pointer.stem,**meta))
        except (OSError,ValueError,KeyError,TypeError):continue
    return result


def approved(kind, *, level=None, preset=None):
    identity=os.environ.get('GLUEMAPPER_IMPORTED_CACHE','')
    if not identity or root() is None:return None
    if not re.fullmatch('[a-f0-9]{64}',identity):raise ValueError('Invalid selected imported cache')
    hit=Cache(root()/'imported').lookup(identity)
    if hit is None:raise ValueError('Selected imported cache is missing or damaged; import it again or choose Rebuild')
    payload,meta=hit
    if kind=='shaders' and meta.get('shaders'):
        return payload/'shaders',meta
    if kind=='lighting' and meta.get('preset')==preset and level in meta.get('levels',{}):
        return payload/'lighting'/level,dict(meta['levels'][level],imported_from=meta['source'])
    return None


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--build',type=Path,required=True)
    parser.add_argument('--workspace',type=Path,required=True)
    args=parser.parse_args()
    print(json.dumps(import_build(args.build,args.workspace),indent=2))
