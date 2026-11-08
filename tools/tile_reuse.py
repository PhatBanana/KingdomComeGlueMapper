"""Reuse lighting tiles of an earlier bake of the same level when each tile's own inputs are equal.

Successive builds change few brushes (KCD1: 4 of 1,291 lighting tiles between one
build's combine inputs and its final package), yet the shared lighting cache
(setup_bake_cache.py) reuses a bake whole or not at all: one moved brush bakes the
level again. Each bake now records, beside its shards, a fingerprint of every input
each tile reads: its placements in order (mesh cache key and transform), the
decoded-mesh records they use, the materials those meshes bind (file hash), every
texture member those materials name (ZIP CRC and size, split pieces included; an
absent or ambiguous texture is part of the identity too), its vegetation instances,
and the baker code, sources and settings. Like reuse_equivalent_world_tiles.py, a
tile is reused only when everything it reads is proven equal, but tile by tile and
from the cache entries this PC already holds. Archive paths and members no tile
reads (quests, NPCs, containers) are not inputs of a tile.

A reused tile gets a report with the current scene's signature, so build() verifies
and keeps it like a completed tile of its own; every other tile is baked as before.
"""
import hashlib
import json
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
IDENTITIES = 'tile_identities'  # cache manifest metadata: tile stem -> identity
MEMBER = 'terrain/svo/'


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
                # The tile fails to bake the same way; no built tile can match it.
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
    # Scene-wide counts (category_policy) are not read by a tile; its own inputs are below.
    common = settings()
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


def recorded_bakes(cache, preset, level):
    """(key, identities) of every cache entry of this level and preset that recorded them, newest first.

    Only pointers are read here; an entry's payload is checked when a tile of it is wanted."""
    rows = []
    for pointer in cache.folder.glob('*.json'):
        if not re.fullmatch('[a-f0-9]{64}', pointer.stem): continue
        try:
            entry = json.loads(pointer.read_text())['entry']
            if Path(entry).name != entry or not entry.startswith(pointer.stem+'-'): continue
            meta = json.loads((cache.folder/entry/'manifest.json').read_text())['metadata']
            if meta.get('preset') != preset or meta.get('level') != level: continue
            identities = meta.get(IDENTITIES)
            if not isinstance(identities, dict) or not identities: continue
            rows.append((pointer.stat().st_mtime, pointer.stem, identities))
        except (OSError, ValueError, KeyError, TypeError, AttributeError):
            continue
    rows.sort(key=lambda row: (row[0], row[1]), reverse=True)
    return [(key, identities) for _, key, identities in rows]


def reuse_cached(scene, cache, preset, level, identities=None, notify=lambda message: None, cancelled=lambda: False):
    """Take every tile of an earlier cached bake whose recorded identity equals the current tile's.

    Newer bakes are preferred; a tile absent from them may still come from an older
    one. A tile this scene already holds (a resumed bake) is left alone."""
    from world_surface_tiles import code_digest, gpu_configuration, tile_signature
    scene = Path(scene)
    plan = json.loads((scene/'plan.json').read_text())
    destination = scene/'tiles'; destination.mkdir(exist_ok=True)
    pending = {stem(job): job for job in plan['tiles'] if not (destination/(stem(job)+'.json')).exists()}
    result = {'tiles': len(plan['tiles']), 'reused': 0, 'rebuild': len(plan['tiles']), 'sources': {}, 'reused_tiles': []}
    bakes = recorded_bakes(cache, preset, level)
    if not bakes:
        notify('No earlier lighting bake of this level recorded per-tile inputs')
        (scene/'tile-reuse.json').write_text(json.dumps(result, indent=2)+'\n')
        return result
    if identities is None:
        notify("Fingerprinting each tile's placements, meshes, materials and textures")
        identities = tile_identities(scene, cancelled)
    version, config = code_digest(), gpu_configuration()
    reused = {}
    for key, previous in bakes:
        if cancelled(): raise InterruptedError('Cancelled while reusing cached lighting tiles')
        wanted = [name for name in pending if previous.get(name) == identities.get(name)]
        if not wanted: continue
        notify(f'Checking cached lighting archives {key[:12]} for {len(wanted)} matching tiles')
        hit = cache.lookup(key)  # every shard's bytes against the manifest
        if hit is None:
            notify('Skipping lighting cache '+key[:12]+': missing, incomplete or changed payload'); continue
        payload = hit[0]
        located = {}
        for shard in sorted(payload.glob('svo-part*.pak')):
            try:
                with zipfile.ZipFile(shard) as archive:
                    for member in archive.namelist():
                        located.setdefault(member.replace('\\', '/').lower(), (shard, member))
            except zipfile.BadZipFile:
                located = {}; break
        taken = []
        for name in wanted:
            locations = [located.get(MEMBER+name+suffix) for suffix in ('.idx', '.vox')]
            if None in locations: continue
            try:
                blobs = []
                for shard, member in locations:
                    with zipfile.ZipFile(shard) as archive: blobs.append(archive.read(member))
                idx, vox = blobs
                validate_pair(idx, vox)
            except (OSError, ValueError, KeyError, zipfile.BadZipFile):
                continue
            job = pending[name]
            for suffix, blob in (('.idx', idx), ('.vox', vox)):
                (destination/(name+suffix)).write_bytes(blob)
            report = dict(tile=name, origin=job['origin'], status='built', placements=len(job['placements']),
                          vegetation_instances=len(job.get('vegetation', [])), requested_backend=BACKEND,
                          gpu_config=config, sha256=hashlib.sha256(idx+vox).hexdigest(),
                          signature=tile_signature(version, plan['asset_catalog_digest'], plan, job,
                                                   SAMPLES, BASE_MATERIALS, BACKEND, config),
                          reuse=dict(cache_key=key, tile_identity=identities[name],
                                     basis='identical placements, decoded meshes, materials, textures and baker settings'))
            pending_report = destination/(name+'.json.tmp')
            pending_report.write_text(json.dumps(report, indent=2)+'\n'); pending_report.replace(destination/(name+'.json'))
            taken.append(name); reused[name] = key; del pending[name]
        if taken: result['sources'][key] = len(taken)
        if not pending: break
    result.update(reused=len(reused), rebuild=len(plan['tiles'])-len(reused), reused_tiles=sorted(reused))
    (scene/'tile-reuse.json').write_text(json.dumps(result, indent=2)+'\n')
    return result
