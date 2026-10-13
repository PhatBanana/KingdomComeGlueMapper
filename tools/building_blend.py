"""Translate legacy two-UV building masks into native second-UV alpha."""
import io
import struct
import subprocess
import tempfile
from pathlib import Path

import numpy as np
from PIL import Image



def decode_texture(base, chunks):
    """Read the mip chain described by the selected header, not stale HD tails."""
    if base[:4] != b'DDS ' or base[84:88] != b'DX10':
        raise ValueError('Expected DX10 building texture')
    h, w = struct.unpack_from('<II', base, 12)
    mips = struct.unpack_from('<I', base, 28)[0]
    fmt = struct.unpack_from('<I', base, 128)[0]
    if fmt not in (71, 72, 77, 78, 80):
        raise ValueError(f'Unsupported building mask compression: DXGI {fmt}')
    block = 8 if fmt in (71, 72, 80) else 16
    sizes = [max(1, (w >> i)+3 >> 2)*max(1, (h >> i)+3 >> 2)*block for i in range(mips)]
    resident = len(base)-148
    split = next((i for i in range(mips) if sum(sizes[i:]) == resident), None)
    if split is None:
        raise ValueError('Building DDS resident mip sizes do not match header')
    payload = bytearray()
    for i in range(split):
        part = chunks.get(str(split-i))
        if part is None or len(part) != sizes[i]:
            raise ValueError('Missing or incompatible building texture mip')
        payload.extend(part)
    payload.extend(base[148:])
    header = bytearray(base[:148]);header[32:76] = bytes(44)
    header[116:128] = bytes(12)
    # Pillow supports the UNORM variants; decoding returns the same stored
    # channel values. Colour-space conversion belongs to the shader sampler.
    struct.pack_into('<I', header, 128, {72:71,78:77}.get(fmt,fmt))
    return np.array(Image.open(io.BytesIO(bytes(header)+payload)).convert('RGBA'))


def sample_wrap(image, uv):
    h,w = image.shape[:2]
    p = np.mod(uv,1)*[w,h]-.5
    base = np.floor(p).astype(np.int64);f = p-base
    x,y = base[:,0],base[:,1]
    return ((image[y%h,x%w]*(1-f[:,0])+image[y%h,(x+1)%w]*f[:,0])*(1-f[:,1])
            +(image[(y+1)%h,x%w]*(1-f[:,0])+image[(y+1)%h,(x+1)%w]*f[:,0])*f[:,1])


def rgba_dds(image):
    """RGBA8 sRGB, with independent linear-light RGB and linear-alpha mips."""
    h,w=image.shape[:2];levels=[]
    linear=image.astype(np.float32)/255
    rgb=linear[:,:,:3]
    linear[:,:,:3]=np.where(rgb<=.04045,rgb/12.92,((rgb+.055)/1.055)**2.4)
    while True:
        encoded=linear.copy();rgb=linear[:,:,:3]
        encoded[:,:,:3]=np.where(rgb<=.0031308,rgb*12.92,1.055*np.maximum(rgb,0)**(1/2.4)-.055)
        levels.append(np.rint(encoded.clip(0,1)*255).astype('u1').tobytes())
        ih,iw=linear.shape[:2]
        if (iw,ih)==(1,1):break
        linear=np.stack([np.array(Image.fromarray(linear[:,:,i]).resize((max(1,iw//2),max(1,ih//2)),Image.Resampling.BOX)) for i in range(4)],axis=2)
    header=bytearray(148);header[:4]=b'DDS '
    struct.pack_into('<7I',header,4,124,0x2100f,h,w,w*4,0,len(levels))
    struct.pack_into('<II4s',header,76,32,4,b'DX10')
    struct.pack_into('<I',header,108,0x401008)
    struct.pack_into('<5I',header,128,29,3,0,1,0) # RGBA8 sRGB, linear alpha
    return bytes(header)+b''.join(levels)


def compressed_dds(image):
    """Use the project's pinned DirectXTex compiler for native BC3 data."""
    from lighting_cubemaps import compiler
    cache=Path('outputs/BuildingBlendCache')
    cache.mkdir(parents=True,exist_ok=True)
    executable=compiler(cache)
    with tempfile.TemporaryDirectory(dir=cache,prefix='atlas-') as directory:
        root=Path(directory).resolve();source=root/'source.dds';dest=root/'compressed'
        dest.mkdir();source.write_bytes(rgba_dds(image))
        result=subprocess.run([str(executable),'-nologo','-y','-dx10','-f','BC3_UNORM_SRGB',
                               '-o',str(dest),str(source)],capture_output=True,text=True,
                              creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        if result.returncode:
            raise ValueError('Building atlas compression failed: '+result.stdout+result.stderr)
        payload=(dest/'source.dds').read_bytes()
        if payload[84:88]!=b'DX10' or struct.unpack_from('<I',payload,128)[0]!=78:
            raise ValueError('Unexpected building atlas encoding')
        return payload


def bake_atlas(second, mask, triangles, size, primary_tiling=1, secondary_tiling=(1,1), factor=0):
    """Sample both source UV sets into the non-overlapping native atlas.

    RGB interpolation is in linear light. The two alpha inputs are linear.
    A negative source factor is folded into alpha to avoid KCD2's new inversion.
    """
    w,h=size
    output=np.zeros((h,w,4),np.float32)
    covered=np.zeros((h,w),bool)
    rgb=second[:,:,:3].astype(np.float64)/255
    rgb=np.where(rgb<=.04045,rgb/12.92,((rgb+.055)/1.055)**2.4)
    rgba=np.concatenate((rgb,second[:,:,3:4]/255),axis=2)
    for uv0,uv2,uv_new in triangles:
        p=uv_new*[w,h]-.5
        lo=np.maximum(0,np.ceil(p.min(0)).astype(int));hi=np.minimum([w-1,h-1],np.floor(p.max(0)).astype(int))
        if np.any(hi<lo):continue
        a,b,c=p
        den=(b[1]-c[1])*(a[0]-c[0])+(c[0]-b[0])*(a[1]-c[1])
        if abs(den)<1e-9:continue
        yy,xx=np.mgrid[lo[1]:hi[1]+1,lo[0]:hi[0]+1]
        wa=((b[1]-c[1])*(xx-c[0])+(c[0]-b[0])*(yy-c[1]))/den
        wb=((c[1]-a[1])*(xx-c[0])+(a[0]-c[0])*(yy-c[1]))/den;wc=1-wa-wb
        inside=(wa>=-1e-7)&(wb>=-1e-7)&(wc>=-1e-7)
        weights=np.column_stack((wa[inside],wb[inside],wc[inside]))
        x=xx[inside];y=yy[inside]
        src=weights@uv2*secondary_tiling
        color=np.column_stack([sample_wrap(rgba[:,:,i],src) for i in range(4)])
        color[:,3]*=sample_wrap(mask,weights@uv0*primary_tiling)
        if factor<0:
            if factor < -1:raise ValueError('Undefined legacy negative blend power')
            color[:,3]*=1+factor
        if np.any(covered[y,x] & (np.max(np.abs(output[y,x]-color),axis=1)>2/255)):
            raise ValueError(f'Generated building atlas overlaps: {np.count_nonzero(covered[y,x])} pixels, difference {np.max(np.abs(output[y,x][covered[y,x]]-color[covered[y,x]]))}')
        output[y,x]=color;covered[y,x]=True
    if not covered.any():raise ValueError('Empty building atlas')
    count=int(covered.sum())
    for _ in range(8):
        old=covered.copy()
        for axis,shift in ((0,1),(0,-1),(1,1),(1,-1)):
            neighbor=np.roll(old,shift,axis);take=~covered & neighbor
            if axis==0:take[0 if shift==1 else -1,:]=False
            else:take[:,0 if shift==1 else -1]=False
            output[take]=np.roll(output,shift,axis)[take];covered[take]=True
    rgb=output[:,:,:3]
    output[:,:,:3]=np.where(rgb<=.0031308,rgb*12.92,1.055*np.maximum(rgb,0)**(1/2.4)-.055)
    return np.rint(output.clip(0,1)*255).astype(np.uint8),{'covered_pixels':count,'width':w,'height':h}
