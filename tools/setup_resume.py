"""Resume saved jobs at verified package boundaries; retain every attempt's logs."""
import json
import os
import shutil
import uuid
from pathlib import Path
from contextlib import contextmanager


def load_job(folder):
    from setup_mods import checked_config
    root=Path(folder).resolve()
    raw=json.loads((root/'job.json').read_text(encoding='utf-8'))
    if raw.get('resume_from'):
        root=Path(raw['resume_from']).resolve()
        raw=json.loads((root/'job.json').read_text(encoding='utf-8'))
    config=checked_config(raw)
    config['resume_from']=str(root)
    return config


@contextmanager
def job_lock(root):
    """OS lock is released even after a crash; a leftover file is harmless."""
    path=Path(root)/'setup.lock'
    with path.open('a+b') as stream:
        if stream.tell()==0:stream.write(b'0');stream.flush()
        stream.seek(0)
        try:
            if os.name=='nt':
                import msvcrt
                msvcrt.locking(stream.fileno(),msvcrt.LK_NBLCK,1)
            else:
                import fcntl
                fcntl.flock(stream,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except OSError as e:
            raise ValueError('This setup job is already running. Wait for it to stop before resuming.') from e
        try:yield
        finally:
            stream.seek(0)
            if os.name=='nt':msvcrt.locking(stream.fileno(),msvcrt.LK_UNLCK,1)
            else:fcntl.flock(stream,fcntl.LOCK_UN)


def restore_swap(package):
    """Recover an interrupted atomic bake-directory swap before verification."""
    package=Path(package)
    previous=package.with_name(package.name+'-before-bake')
    if not package.exists() and previous.is_dir():previous.rename(package)
    previous=package.with_name(package.name+'-before-update')
    if not package.exists() and previous.is_dir():previous.rename(package)


def update_private_package(package,operation,cancelled):
    """Optional stages cannot invalidate the last verified package on failure."""
    from setup_campaign import verify_package
    package=Path(package)
    replacement=package.with_name(package.name+'-update-'+uuid.uuid4().hex[:12])
    def link_or_copy(src,dst):
        try:os.link(src,dst)
        except OSError:shutil.copy2(src,dst)
    shutil.copytree(package,replacement,copy_function=link_or_copy)
    operation(replacement)
    verify_package(replacement)
    if cancelled():raise InterruptedError('Cancelled before applying optional package update')
    previous=package.with_name(package.name+'-before-update')
    if previous.exists():previous.rename(previous.with_name(previous.name+'-'+uuid.uuid4().hex[:12]))
    package.rename(previous)
    try:replacement.rename(package)
    except BaseException:
        previous.rename(package)
        raise


def map_receipt(root, hashes=True):
    from setup_campaign import verify_package, RECEIPT
    package=Path(root)/'package/map'
    restore_swap(package)
    if not (package/RECEIPT).exists():return None
    receipt=verify_package(package,hashes=hashes)
    if not receipt.get('travel_bridge') or receipt.get('build_recipe',{}).get('status')!='complete':
        raise ValueError('Saved map package is incomplete. Its build recipe must finish before it can be reused.')
    from build_recipe import require_current
    require_current(receipt)
    return receipt


def preflight(config):
    import desktop_setup as legacy
    from setup_mods import preflight as fresh_preflight
    root=Path(config['resume_from'])
    receipt=map_receipt(root) if 'map' in config['mods'] and config['action']!='install' else None
    if receipt is None:return fresh_preflight(config)
    target=Path(config['kcd2']).resolve();workspace=Path(config['workspace']).resolve()
    if workspace.is_relative_to(target) or target.is_relative_to(workspace):
        raise ValueError('Choose a build folder outside the game.')
    if legacy.validate_games(Path(config['kcd1']),target)!='1.5.6':raise ValueError('KCD2 1.5.6 is required.')
    from setup_shaders import tool_root
    tool_root(target,config.get('mod_tools'))
    extra=1
    if config['baking']!='none' and receipt.get('baking',{}).get('preset')!=config['baking']:
        import numba
        extra+=30 if config['baking']=='buildings' else 60
    if config['cutscenes']=='opening' and not receipt.get('opening_movie'):
        from setup_cutscenes import check_tools
        check_tools(config['converter']);extra+=10
    stage=0
    if config['action']!='build_only':
        if legacy.game_running():raise ValueError('Close Kingdom Come before installing.')
        stage=sum(p.stat().st_size for p in (root/'package/map').rglob('*') if p.is_file())+legacy.GIB
        if legacy.free_space(target)<stage:raise ValueError('Not enough free space to stage the saved package for installation.')
    required=extra*legacy.GIB+(stage if workspace.anchor.lower()==target.anchor.lower() else 0)
    if legacy.free_space(workspace)<required:raise ValueError(f'Resuming needs {required/legacy.GIB:.1f} GiB free for remaining work and staging.')
    if 'fishing' in config['mods']:
        fish=dict(config,mods=['fishing']);fresh_preflight(fish)
    return dict(ok=True,config=config,messages=['Verified completed KCD1 Map. Resume will reuse it and retry unfinished optional stages.'])
