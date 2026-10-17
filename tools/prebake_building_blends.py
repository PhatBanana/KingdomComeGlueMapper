"""Bake building blend atlases in parallel into the blend cache before the serial world build.

Each worker opens the same asset pack the buildings stage uses and converts every mesh whose root
materials have blend inputs through static_assets.mesh_bytes, so cache keys match the build exactly.
Meshes the stage converts with a material override, or that are missed here, bake normally later.
"""
import argparse
import os
import sys
import time
from multiprocessing import Pool
from pathlib import Path
from pathlib import PurePosixPath

_state = {}


def _init(library, cache):
    import contextlib
    os.environ['GLUEMAPPER_BLEND_CACHE'] = str(cache)
    from game_paths import GameLibrary
    from static_assets import asset_pack
    stack = contextlib.ExitStack()
    index, emitted, material, mesh_bytes = asset_pack(stack, GameLibrary(library), 'gluebuild/prebake/')
    _state.update(stack=stack, index=index, emitted=emitted, mesh_bytes=mesh_bytes)


def _root_materials(blob, name, index):
    """Root material files referenced by a CGF, resolved as static_assets.mesh_bytes does."""
    import struct
    count, table = struct.unpack_from('<II', blob, 8)
    found = []
    for i in range(count):
        kind, version, _, size, offset = struct.unpack_from('<HHIII', blob, table+i*16)
        if kind != 0x1014 or version != 0x802 or size < 128:
            continue
        resolved = bytes(blob[offset:offset+128]).split(b'\0', 1)[0].decode().replace('\\', '/').lower().removesuffix('.mtl')
        if '/' not in resolved and str(PurePosixPath(name).parent/resolved)+'.mtl' in index:
            resolved = str(PurePosixPath(name).parent/resolved)
        for candidate in (resolved, 'objects/'+resolved):
            if candidate+'.mtl' in index:
                found.append(candidate); break
    return found


def _work(name):
    import xml.etree.ElementTree as ET
    from building_materials import blend_inputs
    from upgrade_map import read
    index = _state['index']
    try:
        archive, entry = index[name]
        blob = read(archive, entry.filename)
        if blob[:4] != b'CrCh':
            return 'skipped'
        blended = False
        for root in _root_materials(blob, name, index):
            archive, entry = index[root+'.mtl']
            if list(blend_inputs(ET.fromstring(read(archive, entry.filename)))):
                blended = True; break
        if not blended:
            return 'skipped'
        _state['mesh_bytes'](name)
        return 'baked'
    except Exception:
        return 'failed'
    finally:
        _state['emitted'].clear()


def main():
    sys.path.insert(0, str(Path(__file__).parent))
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--library', required=True, help='game-paths.json used by the conversion stages')
    parser.add_argument('--cache', required=True, type=Path)
    parser.add_argument('--workers', type=int, default=max(1, (os.cpu_count() or 2)-2))
    args = parser.parse_args()
    args.cache.mkdir(parents=True, exist_ok=True)
    _init(args.library, args.cache)
    index = _state['index']
    names = sorted((n for n in index if n.endswith('.cgf')), key=lambda n: -index[n][1].file_size)
    start, counts = time.time(), {}
    print(f'Pre-baking building blends from {len(names)} meshes with {args.workers} workers', flush=True)
    with Pool(args.workers, initializer=_init, initargs=(args.library, args.cache)) as pool:
        for done, outcome in enumerate(pool.imap_unordered(_work, names, chunksize=8), 1):
            counts[outcome] = counts.get(outcome, 0)+1
            if done % 2000 == 0:
                print(f'  {done}/{len(names)} meshes checked in {time.time()-start:.0f} s: {counts}', flush=True)
    print(f'Pre-bake finished in {time.time()-start:.0f} s: {counts}', flush=True)


if __name__ == '__main__':
    main()
