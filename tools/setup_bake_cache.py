"""Reuse completed voxel shards while preserving the new package's quest data."""
from pathlib import Path
import zipfile

from setup_build_cache import fingerprint, file_hash, copy_payload

SOURCES = ('setup_bake_cache.py','setup_baking.py','world_surface_scene.py',
           'world_surface_landscape.py','stage_world_surfaces.py','vegetation_gi.py',
           'compiled_terrain.py','water_volumes.py','vegetation.py','world_voxels.py',
           'validate_world_surfaces.py','clothing_regions.py','voxel_lighting.py')


def key(level, game, overrides, preset):
    from geometry_opacity import Assets
    from world_surface_tiles import code_digest, gpu_configuration
    from upgrade_map import read
    assets = Assets(Path(game)/'Data', overrides)
    # Same effective precedence as the voxelizer. Archive names, timestamps and
    # job paths aren't content. ZIP CRC/size is its existing catalog contract.
    entries = {}
    try:
        for path in sorted({v[0] for v in assets.entries.values() if v is not None}):
            with zipfile.ZipFile(path) as z:
                for item in z.infolist():
                    name = item.filename.replace('\\','/').lower()
                    if name.startswith(('quests/','scripts/','ai/','libs/tables/')): continue
                    if assets.entries.get(name) == (path,item.filename):
                        entries[name] = [item.CRC,item.file_size]
        for name, value in assets.entries.items():
            if value is None: entries[name] = 'ambiguous'
    finally: assets.close()
    with zipfile.ZipFile(Path(level)/'level.pak') as z:
        import hashlib
        geometry = {n:hashlib.sha256(read(z,n)).hexdigest()
                    for n in ('terrain/hlods.dat','leveldata.xml')}
    # Terrain includes height, roads, vegetation transforms and their tables.
    with zipfile.ZipFile(Path(level)/'terrain.pak') as z:
        terrain = sorted((i.filename.replace('\\','/').lower(),i.CRC,i.file_size) for i in z.infolist())
    return fingerprint(dict(version=1,preset=preset,geometry=geometry,terrain=terrain,
        assets=entries,code=code_digest(),
        sources={n:file_hash(Path(__file__).with_name(n)) for n in SOURCES},
        backend='auto',samples=2,experimental_base_materials=True,gpu=gpu_configuration()))


def restore(hit, level, output):
    """Only immutable SVO shards are cached; reconstruct mutable world archives."""
    from build_horse_trader_test import rewrite
    from world_voxels import configure_environment
    from vegetation_gi import upgrade_terrain
    from upgrade_map import read
    payload, report = hit
    packages = Path(output)/'packages'
    copy_payload(payload, packages)
    with zipfile.ZipFile(Path(level)/'level.pak') as z:
        mission = read(z,'mission_mission0.xml')
    rewrite(Path(level)/'level.pak',packages/'level.pak',
            {'mission_mission0.xml':configure_environment(mission,surface_channels=True)})
    if report.get('vegetation_gi_upgrade') is not None:
        with zipfile.ZipFile(Path(level)/'terrain.pak') as z:
            data,_ = upgrade_terrain(read(z,'terrain/terrain.dat'))
        rewrite(Path(level)/'terrain.pak',packages/'terrain.pak',{'terrain/terrain.dat':data})
    return report


def publish(cache, identity, output, report, cancelled):
    files = {p.name:p for p in (Path(output)/'packages').glob('svo-part*.pak')}
    if not files: raise ValueError('No completed voxel shards to cache')
    metadata = {k:report.get(k) for k in ('tiles','limitations','vegetation_gi_upgrade')}
    cache.publish(identity, files, metadata, cancelled)
