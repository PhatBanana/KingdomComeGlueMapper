"""Reuse lighting tiles of an earlier scene of the same level when each tile's own inputs are equal.

The background bake (background_bake.py) lights combine's inputs while the gameplay
recipe runs, and the recipe then edits only a handful of brushes (KCD1: 4 of 1,291
tiles change). Like reuse_equivalent_world_tiles.py, a tile is reused only when
everything it reads is proven equal, but tile by tile: its placements in order (mesh
cache key and transform), the decoded-mesh records they use, the materials those
meshes bind (file hash), every texture member those materials name (ZIP CRC and size,
split pieces included; an absent or ambiguous texture is part of the identity too),
its vegetation instances, and the baker code, sources and settings. These are the
inputs setup_bake_cache.scene_identity fingerprints for a whole scene. Archive paths
and members no tile reads (quests, NPCs, containers) are not inputs of a tile.

A reused tile gets a report with the current scene's signature, so build() verifies
and keeps it like a completed tile of its own; every other tile is baked as before.
"""
import hashlib
import json
import os
from pathlib import Path
import re
import xml.etree.ElementTree as ET
import zipfile

import numpy as np

from setup_build_cache import file_hash, fingerprint
from validate_world_surfaces import stem
from voxel_lighting import validate_pair

VERSION = 1
# What setup_baking bakes; a tile baked with other settings is never reused.
SAMPLES, BASE_MATERIALS, BACKEND = 2, True, 'auto'
SPLIT = re.compile(r'\.(?:\d+a?|a)$')
IDENTITIES = 'tile-identities.json'


def settings():
    from setup_bake_cache import SOURCES
    from world_surface_tiles import code_digest, gpu_configuration
    tools = Path(__file__).resolve().parent
    return dict(version=VERSION, code=code_digest(), gpu=gpu_configuration(), samples=SAMPLES,
                experimental_base_materials=BASE_MATERIALS, backend=BACKEND,
                sources={n: file_hash(tools/n) for n in SOURCES if n not in ('setup_bake_cache.py', 'setup_baking.py')})


def _material(name):
    return name if name.endswith('.mtl') else name+'.mtl'


def _vegetation(scene, plan):
    """(group cache key, transform digest) per vegetation instance, as reuse_equivalent_world_tiles reads them."""
    if not plan.get('vegetation'): return []
    with np.load(scene/'vegetation.npz') as data:
        matrices, groups = data['transforms'], data['groups']
    keys = []
    for matrix, group in zip(matrices, groups):
        cache = plan['vegetation']['groups'][str(int(group))]['cache_key']
        keys.append((cache, hashlib.sha256(np.ascontiguousarray(matrix).tobytes()).hexdigest()))
    return keys


def tile_identities(scene, cancelled=lambda: False):
    """Fingerprint of every input each tile reads, by tile stem."""
    from geometry_opacity import Assets
    from world_surface_tiles import mesh_records
    scene = Path(scene)
    plan = json.loads((scene/'plan.json').read_text())
    records = json.loads((scene/'placements.json').read_text())
    meshes = mesh_records(scene, cancelled=cancelled)
    vegetation = _vegetation(scene, plan)
    names = {_material(name) for record in meshes.values() for name, _ in record.get('bindings', [])}
    materials, named = {}, {}
    assets = Assets(plan['pak_root'], plan['overrides'])
    try:
        for name in sorted(names):
            try:
                blob = assets.get(name)
                materials[name] = hashlib.sha256(blob).hexdigest()
                named[name] = sorted({t.get('File').replace('\\', '/').lower()
                                      for t in ET.fromstring(blob).iter('Texture') if t.get('File')})
            except (ValueError, ET.ParseError) as error:
                # The tile fails to bake the same way; no built reference tile can match it.
                materials[name] = 'unavailable: '+str(error); named[name] = []
        wanted = {texture for textures in named.values() for texture in textures}
        members, by_archive = {}, {}
        for name, location in assets.entries.items():
            base = SPLIT.sub('', name)
            texture = name if name in wanted else base if base in wanted else None
            if texture is None: continue
            if location is None:
                members.setdefault(texture, {})[name] = 'ambiguous'
            else:
                by_archive.setdefault(location[0], []).append((texture, name, location[1]))
        for path, rows in sorted(by_archive.items()):
            if cancelled(): raise InterruptedError('Cancelled while fingerprinting tile textures')
            with zipfile.ZipFile(path) as archive:
                for texture, name, member in rows:
                    info = archive.getinfo(member)
                    members.setdefault(texture, {})[name] = [info.CRC, info.file_size]
    finally:
        assets.close()
    common = dict(settings(), category_policy=plan.get('category_policy'))
    identities = {}
    for job in plan['tiles']:
        placed = [records[i] for i in job['placements']]
        instances = [list(vegetation[i]) for i in job.get('vegetation', [])]
        used = {r['cache_key'] for r in placed} | {key for key, _ in instances}
        meta = {key: meshes.get(key) for key in sorted(used)}
        mtls = sorted({_material(name) for record in meta.values() if record for name, _ in record.get('bindings', [])})
        textures = sorted({t for m in mtls for t in named.get(m, [])})
        identities[stem(job)] = fingerprint(dict(common, origin=job['origin'],
            placements=[[r['cache_key'], r['transform']] for r in placed], vegetation=instances, meshes=meta,
            materials={m: materials.get(m) for m in mtls},
            textures={t: dict(sorted(members.get(t, {}).items())) for t in textures}))
    return identities


def record_identities(scene, cancelled=lambda: False):
    """Store a finished scene's identities beside it, so a later reuse need not recompute them."""
    identities = tile_identities(scene, cancelled)
    path = Path(scene)/IDENTITIES
    pending = path.with_suffix('.tmp'); pending.write_text(json.dumps(identities)); pending.replace(path)
    return identities


def _link(source, target):
    target.unlink(missing_ok=True)
    try: os.link(source, target)
    except OSError:
        import shutil
        shutil.copy2(source, target)


def reuse(scene, reference, notify=lambda message: None, cancelled=lambda: False):
    """Link every built reference tile whose identity equals the current tile's."""
    from world_surface_tiles import code_digest, gpu_configuration, tile_signature
    scene, reference = Path(scene), Path(reference)
    plan = json.loads((scene/'plan.json').read_text())
    old = json.loads((reference/'plan.json').read_text())
    notify('Fingerprinting each tile of the final scene')
    current = tile_identities(scene, cancelled)
    try:
        previous = json.loads((reference/IDENTITIES).read_text())
    except (OSError, ValueError):
        notify('Fingerprinting each tile of the background scene')
        previous = tile_identities(reference, cancelled)
    old_jobs = {stem(job): job for job in old['tiles']}
    version, config = code_digest(), gpu_configuration()
    source, destination = reference/'tiles', scene/'tiles'
    destination.mkdir(exist_ok=True)
    reused, changed = [], []
    for job in plan['tiles']:
        name = stem(job)
        if (destination/(name+'.json')).exists(): continue  # this scene's own (resumed) tile
        if name not in old_jobs or current.get(name) != previous.get(name):
            changed.append(name); continue
        try:
            report = json.loads((source/(name+'.json')).read_text())
            if report.get('status') != 'built': continue
            # The reference tile was built by this code and settings from that job.
            expected = tile_signature(version, old['asset_catalog_digest'], old, old_jobs[name],
                                      SAMPLES, BASE_MATERIALS, BACKEND, config)
            if report.get('signature') != expected: continue
            idx = (source/(name+'.idx')).read_bytes(); vox = (source/(name+'.vox')).read_bytes()
            validate_pair(idx, vox)
            if hashlib.sha256(idx+vox).hexdigest() != report['sha256']: continue
        except (OSError, ValueError, KeyError):
            continue
        for suffix in ('.idx', '.vox'): _link(source/(name+suffix), destination/(name+suffix))
        report['reuse'] = {'source': str(source/(name+'.json')), 'source_signature': report['signature'],
                           'tile_identity': current[name],
                           'basis': 'identical placements, decoded meshes, materials, textures and baker settings'}
        report['signature'] = tile_signature(version, plan['asset_catalog_digest'], plan, job,
                                             SAMPLES, BASE_MATERIALS, BACKEND, config)
        report['vegetation_instances'] = len(job.get('vegetation', []))
        pending = destination/(name+'.json.tmp')
        pending.write_text(json.dumps(report, indent=2)+'\n'); pending.replace(destination/(name+'.json'))
        reused.append(name)
    result = {'reference': str(reference), 'tiles': len(plan['tiles']), 'reused': len(reused),
              'rebuild': len(plan['tiles'])-len(reused), 'changed': changed, 'reused_tiles': reused}
    (scene/'tile-reuse.json').write_text(json.dumps(result, indent=2)+'\n')
    return result
