"""Optional compiled equivalent of the reference surface rasterizer.

Install numba to use this backend. No fast-math: edge ownership, alpha tests
and overlap ordering must agree with the reference implementation.
"""
import math
import numpy as np
from numba import njit
from numba.typed import List


@njit(cache=True,nogil=True)
def decode_rgba_bytes(raw,linear,alpha):
    """Fuse four byte lookups and stores without gathered RGB temporaries."""
    output=np.empty(raw.shape,np.float32)
    for y in range(raw.shape[0]):
        for x in range(raw.shape[1]):
            for channel in range(3):
                output[y,x,channel]=linear[raw[y,x,channel]]
            output[y,x,3]=alpha[raw[y,x,3]]
    return output


@njit(cache=True,nogil=True)
def filter_bounds(lo,hi,candidates,pos,edge):
    """Stable conservative intersection without gathered Nx3 temporaries."""
    result=np.empty(len(candidates),np.int64)
    count=0
    for index in candidates:
        if (hi[index,0]>=pos[0] and lo[index,0]<pos[0]+edge and
            hi[index,1]>=pos[1] and lo[index,1]<pos[1]+edge and
            hi[index,2]>=pos[2] and lo[index,2]<pos[2]+edge):
            result[count]=index
            count+=1
    return result[:count].copy()


@njit(cache=True,nogil=True)
def _raster(triangles, uv, ids, textures, sizes, starts, params, origin, shape, cell, samples):
    count = shape[0]*shape[1]*shape[2]
    colours=np.zeros((count,3)); normals=np.zeros((count,3)); weights=np.zeros(count)
    opacity=np.zeros((count,3))
    for axis in range(3):
        u=1 if axis==0 else 0
        v=1 if axis==2 else 2
        rays=np.zeros((count,samples*samples),np.float32)
        for ti in range(len(triangles)):
            mi=ids[ti]; p=params[mi]
            if p[3]==0 or p[5]==0:continue
            a=(triangles[ti,0]-origin)/cell
            b=(triangles[ti,1]-origin)/cell
            c=(triangles[ti,2]-origin)/cell
            det=(b[u]-a[u])*(c[v]-a[v])-(c[u]-a[u])*(b[v]-a[v])
            if abs(det)<1e-12:continue
            low_u=max(0,int(math.ceil(min(a[u],b[u],c[u])*samples-.5)))
            low_v=max(0,int(math.ceil(min(a[v],b[v],c[v])*samples-.5)))
            high_u=min(shape[u]*samples-1,int(math.floor(max(a[u],b[u],c[u])*samples-.5)))
            high_v=min(shape[v]*samples-1,int(math.floor(max(a[v],b[v],c[v])*samples-.5)))
            n=np.cross(triangles[ti,1]-triangles[ti,0],triangles[ti,2]-triangles[ti,0])
            length=math.sqrt(np.sum(n*n))
            n/=max(length,1e-30)
            h,w=sizes[mi]; start=starts[mi]
            for iv in range(low_v,high_v+1):
                for iu in range(low_u,high_u+1):
                    du=(iu+.5)/samples-a[u]; dv=(iv+.5)/samples-a[v]
                    beta=(du*(c[v]-a[v])-dv*(c[u]-a[u]))/det
                    gamma=((b[u]-a[u])*dv-(b[v]-a[v])*du)/det
                    depth=a[axis]+beta*(b[axis]-a[axis])+gamma*(c[axis]-a[axis])
                    if beta < -1e-10 or gamma < -1e-10 or beta+gamma > 1+1e-10 or depth<0 or depth>=shape[axis]:continue
                    xyz=np.empty(3,np.int64)
                    xyz[u]=iu//samples; xyz[v]=iv//samples; xyz[axis]=int(math.floor(depth))
                    flat=(xyz[2]*shape[1]+xyz[1])*shape[0]+xyz[0]
                    ray=iu%samples+samples*(iv%samples)
                    s=(uv[ti,0,0]+beta*(uv[ti,1,0]-uv[ti,0,0])+gamma*(uv[ti,2,0]-uv[ti,0,0]))*p[6]+p[8]
                    t=(uv[ti,0,1]+beta*(uv[ti,1,1]-uv[ti,0,1])+gamma*(uv[ti,2,1]-uv[ti,0,1]))*p[7]+p[9]
                    qx=s*w-.5; qy=t*h-.5
                    lx=int(math.floor(qx)); ly=int(math.floor(qy)); fx=qx-lx; fy=qy-ly
                    rgba=np.zeros(4)
                    for dy in range(2):
                        for dx in range(2):
                            weight=(fx if dx else 1-fx)*(fy if dy else 1-fy)
                            ix=(lx+dx)%w if p[10] else min(max(lx+dx,0),w-1)
                            iy=(ly+dy)%h if p[11] else min(max(ly+dy,0),h-1)
                            rgba+=textures[start][iy*w+ix]*weight
                    alpha=rgba[3]*p[3]*p[5] if rgba[3]>=p[4] else 0.
                    gain=max(0.,alpha-rays[flat,ray])
                    rays[flat,ray]+=gain
                    weights[flat]+=gain
                    for ch in range(3):
                        colours[flat,ch]+=rgba[ch]*p[ch]*gain
                        normals[flat,ch]+=n[ch]*gain
        for i in range(count):opacity[i,axis]=np.mean(rays[i])
    for i in range(count):
        colours[i]/=max(weights[i],1e-30)
        normals[i]/=max(weights[i],1e-30)
    return opacity,colours,normals


def prepare(materials):
    # Share texture storage when several subsets bind the same texture.
    dtype=texture_dtype(materials)
    textures=List(); sizes=[]; starts=[]; params=[]; seen={}
    for m in materials:
        key=id(m.texture)
        if key not in seen:
            seen[key]=len(textures); textures.append(np.asarray(m.texture,dtype=dtype).reshape(-1,4))
        starts.append(seen[key]); sizes.append(m.texture.shape[:2])
        params.append([*m.diffuse,m.opacity,m.alpha_test,m.coverage,*m.tile,*m.offset,*m.repeat])
    return (textures,np.asarray(sizes),np.asarray(starts),np.asarray(params))


def texture_dtype(materials):
    # Preserve authored precision. Native DDS textures are already float32;
    # promoting their entire storage does not improve double sampling arithmetic.
    for m in materials:
        if m.texture.dtype!=np.float32 and not np.array_equal(m.texture,m.texture.astype(np.float32)):
            return np.float64
    return np.float32


def rasterize(triangles,uv,ids,packed,origin,shape,cell_size,samples):
    result=_raster(np.asarray(triangles,dtype=float),np.asarray(uv,dtype=float),np.asarray(ids,dtype=np.int64),
                   *packed,np.asarray(origin,dtype=float),np.asarray(shape,dtype=np.int64),float(cell_size),samples)
    return {k:v.reshape(*shape[::-1],3) for k,v in zip(('opacity','albedo','normals'),result)}
