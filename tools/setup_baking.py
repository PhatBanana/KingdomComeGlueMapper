"""Optional audited surface baking inside a newly built, private map package."""
import json
import hashlib
import os
import uuid
from pathlib import Path
import shutil
from setup_campaign import RECEIPT,digest,verify_package

PRESETS={'none':'No Baking','buildings':'Buildings','all':'All (Forest)'}

def bake_package(package,game,workspace,preset,progress,cancelled):
    if preset not in PRESETS:raise ValueError('Unknown baking preset')
    if preset=='none':return
    from world_surface_scene import plan
    from world_surface_landscape import augment as landscape
    from world_surface_coverage import augment as coverage
    from world_surface_tiles import build
    from stage_world_surfaces import stage
    package=Path(package).resolve();workspace=Path(workspace).resolve()
    from setup_resume import restore_swap
    restore_swap(package)
    receipt=verify_package(package)
    if receipt.get('baking',{}).get('preset')==preset:return
    from world_surface_tiles import code_digest
    # Separate incompatible plans, while retaining interrupted work for inspection.
    policy=[preset,receipt['files'],code_digest()]
    for name in ('world_surface_scene.py','world_surface_landscape.py','stage_world_surfaces.py'):
        policy.append(hashlib.sha256(Path(__file__).with_name(name).read_bytes()).hexdigest())
    policy.append([(str(p),p.stat().st_size,p.stat().st_mtime_ns) for p in sorted(Path(game).glob('Data/**/*.pak'))])
    engine=Path(game)/'Engine/Engine.pak'
    if engine.exists():policy.append((str(engine),engine.stat().st_size,engine.stat().st_mtime_ns))
    signature=hashlib.sha256(json.dumps(policy,sort_keys=True).encode()).hexdigest()
    workspace=workspace/signature
    workspace.mkdir(parents=True,exist_ok=True)
    overrides=[str(p.resolve()) for p in sorted((package/'Data').glob('*.pak'))]
    reports=[];staged=[]
    for level in sorted((package/'Data/Levels').iterdir()):
        if not (level/'terrain.pak').exists():continue
        if cancelled():raise InterruptedError('Cancelled before baking '+level.name)
        levelwork=workspace/level.name;levelwork.mkdir(exist_ok=True)
        ready=levelwork/'ready.json'
        if ready.exists():
            attempt=json.loads(ready.read_text())['attempt']
            if Path(attempt).name!=attempt:raise ValueError('Invalid saved bake attempt')
            root=levelwork/attempt
            progress('Inspect bake geometry',0,0,level.name+' · Reusing completed scene plan')
        else:
            root=levelwork/('plan-'+uuid.uuid4().hex[:12])
            progress('Inspect bake geometry',0,0,level.name+' · '+PRESETS[preset])
            plan(level,Path(game)/'Data',root/'base',overrides)
            landscape(root/'base',experimental_base_materials=True)
            coverage(root/'base',root/'scene',include_vegetation=preset=='all')
            scene_plan=json.loads((root/'scene/plan.json').read_text())
            if not scene_plan['errors']:
                pending=ready.with_suffix('.tmp');pending.write_text(json.dumps(dict(attempt=root.name)))
                pending.replace(ready)
        from setup_gpu import hybrid_environment
        print('Hybrid bake: compiled CPU below 1,000,000 triangles (2 workers); '
              'OptiX for dense tiles, 64-brick batches with CPU overlap. '
              'GPU failures are logged and fall back to CPU.',flush=True)
        with hybrid_environment():
            results=build(root/'scene',experimental_base_materials=True,backend='auto',workers=2,
                          progress=progress,cancelled=cancelled)
        counts={name:sum(r.get('backend')==name for r in results) for name in ('compiled','optix')}
        print(f'Hybrid bake results: {counts["compiled"]} CPU tiles, {counts["optix"]} OptiX tiles, '
              f'{sum(bool(r.get("gpu_fallback_reason")) for r in results)} GPU fallbacks.',flush=True)
        if any(r['status']!='built' for r in results):raise ValueError('Lighting tile failed; see bake reports. Nothing installed.')
        if cancelled():raise InterruptedError('Cancelled before staging bake')
        output=root/('staged-'+uuid.uuid4().hex[:12])
        report=stage(root/'scene',output)
        staged.append((level.name,output/'packages'))
        reports.append(dict(level=level.name,tiles=report['tiles'],limitations=report['limitations']))
    if not reports:raise ValueError('No converted levels to bake')
    if cancelled():raise InterruptedError('Cancelled before applying complete bake')
    # Construct a replacement privately. Hardlinks are only read; every changed
    # file is replaced, so failure cannot corrupt the verified input package.
    replacement=package.with_name(package.name+'-baked-'+uuid.uuid4().hex[:12])
    def link_or_copy(src,dst):
        try:os.link(src,dst)
        except OSError:shutil.copy2(src,dst)
    shutil.copytree(package,replacement,copy_function=link_or_copy)
    for name,files in staged:
        level=replacement/'Data/Levels'/name
        for old in level.glob('svo-part*.pak'):old.unlink()
        for source in files.iterdir():
            target=level/source.name
            target.unlink(missing_ok=True);shutil.copy2(source,target)
    receipt['baking']=dict(preset=preset,experimental=True,runtime_verified=False,levels=reports)
    receipt['files']={p.relative_to(replacement).as_posix():digest(p) for p in sorted(replacement.rglob('*')) if p.is_file() and p.name!=RECEIPT}
    (replacement/RECEIPT).unlink()
    (replacement/RECEIPT).write_text(json.dumps(receipt,indent=2))
    verify_package(replacement)
    if cancelled():raise InterruptedError('Cancelled before applying complete bake; outputs retained')
    previous=package.with_name(package.name+'-before-bake')
    if previous.exists():previous.rename(package.with_name(package.name+'-before-bake-'+uuid.uuid4().hex[:12]))
    package.rename(previous)
    try:replacement.rename(package)
    except BaseException:
        previous.rename(package)
        raise
