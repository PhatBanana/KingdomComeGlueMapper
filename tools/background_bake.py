"""Light combine's inputs in the background while the gameplay recipe runs.

Combine and the gameplay recipe run on about one core for over half an hour, while
the lighting bake waits for their package. They change few brushes (KCD1: 4 of 1,291
lighting tiles), so the bake can start as soon as the converted world and the coach
travel package exist. The real bake still plans the final package as before; then
tile_reuse links every tile whose own inputs are unchanged and only the rest are baked.

Nothing here is required: a skipped, failed or stopped background bake only leaves
more tiles for the real bake. It runs at below-normal priority so the recipe keeps
its core, and only when the memory free at its start fits it beside the recipe, so
16 GB machines keep the serial order. GLUEMAPPER_BACKGROUND_BAKE: auto (default),
0 (never) or 1 (always, even when a lighting bake is already cached on this PC).
"""
import atexit
import json
import os
from pathlib import Path
import shutil
import time
import traceback

SETTING = 'GLUEMAPPER_BACKGROUND_BAKE'
GIB = 1024**3
# Measured on KCD1 (64 GB machine): the recipe peaks at about 16 GB beside its
# shader compiler; the bake's planner holds about 10 GB (world_surface_tiles.WORKER_RESERVE).
MIN_FREE = 32*GIB
RECIPE_RESERVE = 16*GIB
STOP = 'stop.requested'
_process = None


def folder(workspace):
    return Path(workspace).resolve()/'background'


def _status(root, **values):
    pending = root/'status.json.tmp'
    pending.write_text(json.dumps(values, indent=2)+'\n'); pending.replace(root/'status.json')


def _cached(preset, level):
    """Whether this PC already holds a published lighting bake for the level and preset.

    That bake is reused whole when the scene is unchanged, so a background bake
    would only compete with the recipe for the disk."""
    from setup_build_cache import root
    if root() is None: return False
    for manifest in (root()/'lighting').glob('*/manifest.json'):
        try: meta = json.loads(manifest.read_text())['metadata']
        except (OSError, ValueError, KeyError): continue
        if meta.get('preset') == preset and meta.get('level') == level: return True
    return False


def processes(free):
    """Tile processes that fit beside the recipe and the bake's own planner."""
    from world_surface_tiles import TILE_PROCESS, WORKER_RESERVE
    return max(1, min(6, int((free-RECIPE_RESERVE-WORKER_RESERVE)//TILE_PROCESS)))


def start(package, data_folders, game, workspace, preset, notify=lambda message: None):
    """Start baking the one terrain level of `package`, resolving assets from `data_folders`."""
    global _process
    from bounded_pool import available_memory
    mode = os.environ.get(SETTING, 'auto')
    if mode not in ('auto', '0', '1'): raise ValueError(SETTING+' must be auto, 0 or 1')
    if mode == '0' or preset not in ('buildings', 'all') or workspace is None: return None
    levels = sorted(p.parent for p in (Path(package)/'Data/Levels').glob('*/terrain.pak'))
    if len(levels) != 1:
        notify('Background lighting bake skipped: expected one converted terrain level'); return None
    level = levels[0]
    free = available_memory()
    if mode == 'auto':
        if free is not None and free < MIN_FREE:
            notify(f'Background lighting bake skipped: {free/GIB:.0f} GB free, {MIN_FREE//GIB} GB needed beside the recipe'); return None
        if _cached(preset, level.name):
            notify('Background lighting bake skipped: this PC already has a lighting bake for this level'); return None
    root = folder(workspace)
    if root.exists(): shutil.rmtree(root)  # an earlier attempt of this job; its tiles are proven again anyway
    root.mkdir(parents=True)
    # Same precedence as the final package: its archives sit in one Data folder, ordered by name.
    paks = sorted((p for data in data_folders for p in Path(data).glob('*.pak')), key=lambda p: p.name)
    count = processes(free) if free is not None else None
    import multiprocessing
    _process = multiprocessing.get_context('spawn').Process(target=_run, name='background-lighting-bake',
        args=(str(level), str(game), [str(p.resolve()) for p in paks], str(root), preset, count))
    _process.start()
    atexit.register(stop, workspace)
    notify(f'Background lighting bake started for {level.name}'+(f' with {count} tile process(es)' if count else ''))
    return _process


def _lower_priority():
    if os.name == 'nt':
        import ctypes
        kernel = ctypes.windll.kernel32
        kernel.SetPriorityClass(kernel.GetCurrentProcess(), 0x00004000)  # BELOW_NORMAL; tile processes inherit it
    else:
        try: os.nice(5)
        except OSError: pass


def _run(level, game, overrides, root, preset, count):
    import contextlib
    root = Path(root); started = time.time()
    stopped = lambda: (root/STOP).exists()
    _lower_priority()
    if count and 'GLUEMAPPER_BAKE_TILE_WORKERS' not in os.environ:
        os.environ['GLUEMAPPER_BAKE_TILE_WORKERS'] = str(count)
    with (root/'background.log').open('a', encoding='utf-8', buffering=1) as log, \
            contextlib.redirect_stdout(log), contextlib.redirect_stderr(log):
        _status(root, status='running', level=level)
        try:
            from world_surface_scene import plan
            from world_surface_landscape import augment as landscape
            from world_surface_coverage import augment as coverage
            from world_surface_tiles import build, mesh_records
            from setup_gpu import hybrid_environment
            from tile_reuse import record_identities
            plan(Path(level), Path(game)/'Data', root/'base', overrides)
            if stopped(): raise InterruptedError('Stopped after planning')
            landscape(root/'base', experimental_base_materials=True)
            coverage(root/'base', root/'scene', include_vegetation=preset == 'all')
            if json.loads((root/'scene/plan.json').read_text())['errors']:
                _status(root, status='failed', error='scene plan has errors', seconds=time.time()-started); return
            mesh_records(root/'scene', cancelled=stopped)
            with hybrid_environment():
                results = build(root/'scene', experimental_base_materials=True, backend='auto', workers='auto', cancelled=stopped)
            record_identities(root/'scene', stopped)
            _status(root, status='done', built=sum(r['status'] == 'built' for r in results), tiles=len(results),
                    seconds=time.time()-started)
        except InterruptedError as error:
            _status(root, status='stopped', error=str(error), seconds=time.time()-started)
        except BaseException as error:
            traceback.print_exc()
            _status(root, status='failed', error=f'{type(error).__name__}: {error}', seconds=time.time()-started)


def wait(workspace, progress=lambda *a: None, cancelled=lambda: False):
    """Let a running background bake finish; return its scene, or None when there is none to reuse.

    Its remaining tiles are the same work the real bake would do, so waiting costs nothing."""
    global _process
    root = folder(workspace)
    if _process is not None:
        while _process.is_alive():
            if cancelled():
                stop(workspace); raise InterruptedError('Cancelled while the background lighting bake finished')
            try:
                done = json.loads((root/'scene/build-progress.json').read_text())
                progress('Finish background lighting bake', done['processed_tiles'], done['selected_tiles'],
                         f"{done['processed_tiles']} of {done['selected_tiles']} background tiles")
            except (OSError, ValueError, KeyError):
                progress('Finish background lighting bake', 0, 0, 'Planning the background scene')
            _process.join(2)
        _process = None
    scene = root/'scene'
    if not (scene/'plan.json').is_file() or not (scene/'tiles').is_dir(): return None
    try: status = json.loads((root/'status.json').read_text())
    except (OSError, ValueError): status = {}
    print('Background lighting bake: '+str(status.get('status', 'unknown'))
          +(f" ({status['error']})" if status.get('error') else ''), flush=True)
    return scene


def stop(workspace, timeout=120):
    """Ask a running background bake to stop between tiles; end it if it does not."""
    global _process
    process, _process = _process, None
    if process is None or not process.is_alive(): return
    root = folder(workspace)
    try: (root/STOP).touch()
    except OSError: pass
    process.join(timeout)
    if process.is_alive(): process.terminate(); process.join(10)


def cleanup(workspace):
    """Remove the background scene (several GB) once the real bake has linked what it needed.

    Its status and log stay for the build report."""
    stop(workspace)
    for name in ('base', 'scene'): shutil.rmtree(folder(workspace)/name, ignore_errors=True)
