"""Optional CUDA backend. Textures stay on-device for the lifetime of one tile."""
import ctypes as ct
import hashlib
import json
import os
from pathlib import Path
import numpy as np


def library(optix=False):
    path=Path(os.environ.get('GLUEMAPPER_OPTIX_DLL' if optix else 'GLUEMAPPER_CUDA_DLL',Path(__file__).resolve().parents[1]/('outputs/cuda/voxel_raster_optix.dll' if optix else 'outputs/cuda/voxel_raster_cuda.dll')))
    if not path.is_file():raise RuntimeError('Build CUDA backend with tools/build_voxel_cuda.ps1 first')
    metadata=path.with_suffix('.build.json')
    if not metadata.is_file():raise RuntimeError('CUDA build metadata missing; rebuild tools/build_voxel_cuda.ps1')
    build=json.loads(metadata.read_text(encoding='utf-8-sig'))
    if build['source_sha256']!=hashlib.sha256(Path(__file__).with_suffix('.cu').read_bytes()).hexdigest() or build['dll_sha256']!=hashlib.sha256(path.read_bytes()).hexdigest():
        raise RuntimeError('CUDA binary is stale or modified; rebuild tools/build_voxel_cuda.ps1')
    if optix:
        for name,digest in build.get('extra_sources',{}).items():
            if hashlib.sha256(Path(__file__).with_name(name).read_bytes()).hexdigest()!=digest:raise RuntimeError('OptiX source changed; rebuild')
        ptx=Path(os.environ.get('GLUEMAPPER_OPTIX_PTX',path.with_name('voxel_optix.ptx')))
        if hashlib.sha256(ptx.read_bytes()).hexdigest()!=build.get('ptx_sha256'):raise RuntimeError('OptiX PTX changed; rebuild')
        os.environ['GLUEMAPPER_OPTIX_PTX']=str(ptx.resolve())
    dll=ct.CDLL(str(path))
    ptr=ct.c_void_p
    dll.vr_create.argtypes=[ptr,ct.c_int64,ptr,ptr,ptr,ct.c_int,ct.c_int];dll.vr_create.restype=ptr
    dll.vr_destroy.argtypes=[ptr];dll.vr_destroy.restype=None
    dll.vr_error.restype=ct.c_char_p
    dll.vr_raster.argtypes=[ptr,ptr,ptr,ptr,ct.c_int,ptr,ptr,ct.c_double,ct.c_int,ptr]
    dll.vr_raster.restype=ct.c_int
    dll.vr_scene_upload.argtypes=[ptr,ptr,ptr,ptr,ct.c_int];dll.vr_scene_upload.restype=ct.c_int
    dll.vr_batch.argtypes=[ptr,ptr,ct.c_int,ct.c_int,ptr];dll.vr_batch.restype=ct.c_int
    return dll


class Prepared:
    def __init__(self,materials,optix=False):
        self.handle=None;self.dll=library(optix);self.material_count=len(materials)
        from voxel_raster_fast import texture_dtype
        dtype=texture_dtype(materials)
        textures=[];sizes=[];starts=[];params=[];seen={};pixels=0
        for m in materials:
            key=id(m.texture)
            if key not in seen:
                seen[key]=pixels;textures.append(np.asarray(m.texture,dtype=dtype).reshape(-1,4));pixels+=textures[-1].shape[0]
            starts.append(seen[key]);sizes.append(m.texture.shape[:2])
            params.append([*m.diffuse,m.opacity,m.alpha_test,m.coverage,*m.tile,*m.offset,*m.repeat])
        arrays=[np.ascontiguousarray(np.concatenate(textures) if textures else np.empty((0,4))),
                np.ascontiguousarray(sizes,dtype=np.int64),np.ascontiguousarray(starts,dtype=np.int64),np.ascontiguousarray(params,dtype=np.float64)]
        self.handle=self.dll.vr_create(arrays[0].ctypes.data,pixels,*[a.ctypes.data for a in arrays[1:]],len(materials),int(dtype==np.float32))
        if not self.handle:raise RuntimeError(self.dll.vr_error().decode())

    def close(self):
        if self.handle:self.dll.vr_destroy(self.handle);self.handle=None

    def set_scene(self,triangles,uv,ids):
        t=np.ascontiguousarray(triangles,dtype=np.float64);u=np.ascontiguousarray(uv,dtype=np.float64);i=np.ascontiguousarray(ids,dtype=np.int64)
        if t.shape!=(len(t),3,3) or u.shape!=(len(t),3,2) or i.shape!=(len(t),):raise ValueError('Invalid scene shapes')
        if not np.isfinite(t).all() or not np.isfinite(u).all():raise ValueError('Nonfinite scene')
        if len(i) and (i.min()<0 or i.max()>=self.material_count):raise ValueError('Invalid scene material index')
        if self.dll.vr_scene_upload(self.handle,t.ctypes.data,u.ctypes.data,i.ctypes.data,len(t)):raise RuntimeError(self.dll.vr_error().decode())

    def raster_scene(self,origin,shape,cell_size,samples):
        if not self.handle:raise RuntimeError('CUDA context is closed')
        if samples not in (1,2,4,8) or len(shape)!=3 or any(int(v)!=v or v<=0 for v in shape) or np.prod(shape)>2**24:raise ValueError('Invalid CUDA brick shape or samples')
        if not np.isfinite(cell_size) or cell_size<=0 or np.shape(origin)!=(3,) or not np.isfinite(origin).all():raise ValueError('Invalid CUDA brick coordinates')
        o=np.ascontiguousarray(origin,dtype=np.float64);s=np.ascontiguousarray(shape,dtype=np.int64)
        output=np.empty((int(np.prod(shape)),9),dtype=np.float64)
        if self.dll.vr_raster(self.handle,None,None,None,0,o.ctypes.data,s.ctypes.data,float(cell_size),samples,output.ctypes.data):raise RuntimeError(self.dll.vr_error().decode())
        return {key:output[:,start:start+3].reshape(*shape[::-1],3) for key,start in [('opacity',0),('albedo',3),('normals',6)]}

    def raster_batch(self,bricks,samples=2):
        """Packed (x,y,z,cell) records; output order is input order."""
        if not self.handle:raise RuntimeError('CUDA context is closed')
        b=np.ascontiguousarray(bricks,dtype=np.float64)
        if b.ndim!=2 or b.shape[1]!=4 or not 1<=len(b)<=64 or not np.isfinite(b).all() or np.any(b[:,3]<=0):raise ValueError('Invalid batch coordinates')
        if samples not in (1,2,4,8):raise ValueError('Invalid samples')
        output=np.empty((len(b),16,16,16,9),dtype=np.float64)
        if self.dll.vr_batch(self.handle,b.ctypes.data,len(b),samples,output.ctypes.data):
            message=self.dll.vr_error().decode()
            if len(b)>1 and any(s in message.lower() for s in ('out of memory','memory allocation','vram budget')):
                # Retry only resource exhaustion, never arithmetic/runtime faults.
                # Each failed native call releases its temporary device buffers.
                import sys
                middle=len(b)//2
                print(f'OptiX batch memory limit: splitting {len(b)} bricks into {middle} and {len(b)-middle}',file=sys.stderr,flush=True)
                del output
                return np.concatenate((self.raster_batch(b[:middle],samples),self.raster_batch(b[middle:],samples)))
            raise RuntimeError(message)
        return output

    def __del__(self):
        self.close()


prepare=Prepared


def prepare_optix(materials):return Prepared(materials,optix=True)


def rasterize(triangles,uv,ids,packed,origin,shape,cell_size,samples):
    if samples not in (1,2,4,8):raise ValueError('CUDA samples must be 1, 2, 4 or 8')
    if len(shape)!=3 or any(int(v)!=v or v<=0 for v in shape) or np.prod(shape)>2**24:raise ValueError('Invalid CUDA brick shape')
    if not np.isfinite(cell_size) or cell_size<=0:raise ValueError('Invalid cell size')
    arrays=[np.ascontiguousarray(triangles,dtype=np.float64),np.ascontiguousarray(uv,dtype=np.float64),np.ascontiguousarray(ids,dtype=np.int64),
            np.ascontiguousarray(origin,dtype=np.float64),np.ascontiguousarray(shape,dtype=np.int64)]
    output=np.empty((int(np.prod(shape)),9),dtype=np.float64)
    t,u,i,o,s=arrays
    if t.shape!=(len(t),3,3) or u.shape!=(len(t),3,2) or i.shape!=(len(t),) or o.shape!=(3,):raise ValueError('Invalid CUDA geometry arrays')
    if not np.isfinite(t).all() or not np.isfinite(u).all() or not np.isfinite(o).all():raise ValueError('Nonfinite CUDA geometry')
    if len(i) and (i.min()<0 or i.max()>=packed.material_count):raise ValueError('CUDA material index outside table')
    if not packed.handle:raise RuntimeError('CUDA context is closed')
    if packed.dll.vr_raster(packed.handle,t.ctypes.data,u.ctypes.data,i.ctypes.data,len(t),o.ctypes.data,s.ctypes.data,float(cell_size),samples,output.ctypes.data):
        raise RuntimeError(packed.dll.vr_error().decode())
    return {key:output[:,start:start+3].reshape(*shape[::-1],3) for key,start in [('opacity',0),('albedo',3),('normals',6)]}
