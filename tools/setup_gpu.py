"""Use the established hybrid baker from source and from the frozen setup."""
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import sys

GPU_FILES = ('voxel_raster_optix.dll', 'voxel_raster_optix.build.json', 'voxel_optix.ptx')
GPU_POLICY = {'GLUEMAPPER_GPU_BATCH': '64', 'GLUEMAPPER_GPU_PIPELINE': '1',
              'GLUEMAPPER_GPU_ASYNC': '0', 'GLUEMAPPER_GPU_GRAPHS': '0',
              'GLUEMAPPER_OPTIX_TRIANGLES': '0'}


def gpu_directory():
    if getattr(sys, 'frozen', False):
        return Path(sys._MEIPASS) / 'bake-gpu'
    return Path(__file__).resolve().parents[1] / 'outputs/cuda'


def validate_bundle(directory, sources=None):
    """Reject stale/missing GPU payloads before producing a setup executable."""
    directory = Path(directory)
    sources = Path(sources) if sources is not None else Path(__file__).parent
    for name in GPU_FILES:
        if not (directory / name).is_file():
            raise RuntimeError('Missing hybrid bake resource: ' + str(directory / name))
    metadata = json.loads((directory / GPU_FILES[1]).read_text(encoding='utf-8-sig'))
    checks = [(directory / GPU_FILES[0], metadata['dll_sha256']),
              (directory / GPU_FILES[2], metadata['ptx_sha256']),
              (sources / 'voxel_raster_cuda.cu', metadata['source_sha256'])]
    for name in ('voxel_optix_shared.h', 'voxel_optix_device.cu', 'voxel_optix_host.h'):
        checks.append((sources / name, metadata['extra_sources'][name]))
    for path, expected in checks:
        if hashlib.sha256(path.read_bytes()).hexdigest() != expected:
            raise RuntimeError('Stale or modified hybrid bake resource: ' + str(path))
    return metadata


@contextmanager
def hybrid_environment():
    """Installer uses the accepted policy, independent of developer experiments."""
    settings = dict(GPU_POLICY)
    directory = gpu_directory()
    settings.update(GLUEMAPPER_OPTIX_DLL=str(directory / GPU_FILES[0]),
                    GLUEMAPPER_OPTIX_PTX=str(directory / GPU_FILES[2]))
    previous = {key: os.environ.get(key) for key in settings}
    os.environ.update(settings)
    try:
        yield
    finally:
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def probe():
    """Actually rasterize a small OptiX scene; loading a DLL is insufficient."""
    import numpy as np
    from voxel_surfaces import Surface, build_tile
    triangle = np.array([[[1, 1, 1], [2, 1, 1], [1, 2, 1]]], dtype=np.float32)
    surface = Surface(np.ones((1, 1, 4), dtype=np.float32), [1, 1, 1])
    args = (triangle, np.zeros((1, 3, 2)), np.zeros(1, dtype=int), [surface], (0, 0, 0), 8, 8)
    try:
        validate_bundle(gpu_directory())
        with hybrid_environment():
            cpu = build_tile(*args, backend='compiled', workers=2)
            gpu = build_tile(*args, backend='optix')
        if cpu[:2] != gpu[:2]:
            raise RuntimeError('OptiX probe did not match CPU output')
        return {'available': True, 'backend': 'optix', 'byte_equivalent': True}
    except (RuntimeError, OSError, ValueError, KeyError) as error:
        return {'available': False, 'backend': 'compiled', 'reason': str(error)}
