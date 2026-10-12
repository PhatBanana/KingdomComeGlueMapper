"""Translate authored HDR probe samples into the native KCD2 cube atlas format.

The source bake is retained: no sRGB conversion, tone mapping or new lighting
bake. Resample its prefiltered roughness levels and times in linear HDR space.
"""
from contextlib import ExitStack
import hashlib
import json
from pathlib import Path
import shutil
import struct
import subprocess
import threading
import urllib.request
import zipfile

import numpy as np
from PIL import Image

from audit_maps import texture_families
from upgrade_map import read

SOURCE_TIMES = (220, 280, 300, 480, 780, 1080, 1260, 1280, 1340)
TARGET_TIMES = (180, 240, 285, 345, 420, 780, 1140, 1215, 1275, 1320, 1380)
TEXCONV_URL = 'https://github.com/microsoft/DirectXTex/releases/download/may2026/texconv.exe'
TEXCONV_SHA256 = 'dcfdec10244e02cf5037fba089c55fb7e1326b1c8181742d77d15fa5cb5eef06'


def verify_native_contract(target):
    times=set();formats=set()
    for path in sorted((Path(target)/'Data').glob('*Textures*.pak')):
        with zipfile.ZipFile(path) as archive:
            for name in archive.namelist():
                key=name.replace('\\','/').lower()
                prefix='textures/cubemaps/trosecko/global_probe_trosecko/'
                if not key.startswith(prefix) or not key.endswith('_cm.dds'):continue
                label=key[len(prefix):].removesuffix('_cm.dds')
                hour,minute=map(int,label.split('_'));times.add(hour*60+minute)
                blob=read(archive,name)
                if blob[:4]!=b'DDS ' or blob[84:88]!=b'DX10':raise ValueError('Native cubemap encoding changed')
                formats.add((struct.unpack_from('<II',blob,12),struct.unpack_from('<I',blob,128)[0]))
    if tuple(sorted(times))!=TARGET_TIMES or formats!={((128,128),95)}:
        raise ValueError(f'Native probe atlas contract changed: {sorted(times)}, {formats}')
    return {'times_minutes':sorted(times),'size':128,'dxgi_format':95}


def compiler(cache):
    """Pinned Microsoft tool, cached beside the build, never inside game data."""
    bundled = Path(__file__).with_name('texconv.exe')
    path = bundled if bundled.is_file() else Path(cache) / 'texconv.exe'
    if not path.is_file():
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix('.download')
        urllib.request.urlretrieve(TEXCONV_URL, temporary)
        if hashlib.sha256(temporary.read_bytes()).hexdigest() != TEXCONV_SHA256:
            temporary.unlink()
            raise ValueError('DirectXTex download checksum mismatch')
        temporary.replace(path)
    if hashlib.sha256(path.read_bytes()).hexdigest() != TEXCONV_SHA256:
        raise ValueError('Unexpected DirectXTex binary')
    return path.resolve()


def time_bracket(times, minute):
    """Periodic interpolation, including midnight; times are minutes after 00:00."""
    minute %= 1440
    for i, start in enumerate(times):
        end = times[(i + 1) % len(times)] + (1440 if i == len(times)-1 else 0)
        value = minute + (1440 if minute < times[0] else 0)
        if start <= value < end:
            return i, (i+1) % len(times), (value-start)/(end-start)
    raise ValueError('Invalid time schedule')


def stamp(minute):
    return f'{minute//60:02d}_{minute%60:02d}'


def standard_cube(base, members):
    """Reassemble CryEngine face/mip chunks, and normalize DX10 arraySize."""
    header = bytearray(base[:148])
    if base[:4] != b'DDS ' or base[84:88] != b'DX10':
        raise ValueError('Expected a DX10 HDR cubemap')
    fmt, dim, flags, count, _ = struct.unpack_from('<5I', base, 128)
    if fmt != 95 or dim != 3 or not flags & 4 or count not in (1, 6):
        raise ValueError('Unsupported source HDR cubemap format')
    width, height = struct.unpack_from('<II', base, 12)
    mips = struct.unpack_from('<I', base, 28)[0] or 1
    if width != height: raise ValueError('Non-square cubemap')
    sizes = [max(1, (width >> i)//4)**2 * 16 for i in range(mips)]
    # Numbered chunks contain all six faces at one high-resolution mip.
    faces = [bytearray() for _ in range(6)]
    levels = len(members)
    if levels >= mips: raise ValueError('Invalid split cubemap mip count')
    for mip, chunk in enumerate(reversed(members)):
        if len(chunk) != 6*sizes[mip]: raise ValueError('Invalid split cubemap payload')
        for face in range(6): faces[face].extend(chunk[face*sizes[mip]:(face+1)*sizes[mip]])
    tail = sum(sizes[levels:])
    if len(base) != 148+6*tail: raise ValueError('Unexpected cubemap tail or missing mips')
    for face in range(6): faces[face].extend(base[148+face*tail:148+(face+1)*tail])
    struct.pack_into('<I', header, 140, 1)
    header[32:76] = bytes(44)  # CryEngine flags/range metadata, not DDS fields.
    struct.pack_into('<I', header, 116, 0)
    struct.pack_into('<I', header, 124, 0)
    return bytes(header)+b''.join(faces)


def float_mips(blob):
    if blob[:4] != b'DDS ' or blob[84:88] != b'DX10' or struct.unpack_from('<I', blob, 128)[0] != 10:
        raise ValueError('Expected RGBA16_FLOAT DX10 output')
    size = struct.unpack_from('<I', blob, 12)[0]
    count = struct.unpack_from('<I', blob, 28)[0] or 1
    levels = [np.empty((6,max(1,size>>i),max(1,size>>i),4),np.float32) for i in range(count)]
    offset = 148
    for face in range(6):
        for level in levels:
            n = level[face].size
            level[face] = np.frombuffer(blob, '<f2', n, offset).reshape(level[face].shape)
            offset += n*2
    if offset != len(blob): raise ValueError('Unexpected float cubemap payload')
    return levels


def resize_level(level, size):
    if level.shape[1] == size: return level
    result = np.empty((6,size,size,4), np.float32)
    for face in range(6):
        for channel in range(3):
            result[face,:,:,channel] = np.asarray(Image.fromarray(level[face,:,:,channel]).resize(
                (size,size),Image.Resampling.BILINEAR))
    result[:,:,:,3] = 1
    return result


def atlas_mips(levels, diffuse=False):
    """Preserve prefiltered roughness, rather than box-filtering the sharp mip."""
    count = 1 if diffuse else 6
    result = []
    for i in range(count):
        lod = i*(len(levels)-1)/max(1,count-1)
        a = int(lod); b = min(a+1,len(levels)-1); t = lod-a
        size = 128 >> i
        result.append(resize_level(levels[a],size)*(1-t)+resize_level(levels[b],size)*t)
    return result


def float_dds(levels):
    header = bytearray(148)
    header[:4] = b'DDS '
    struct.pack_into('<7I',header,4,124,0x2100F,128,128,1024,0,len(levels))
    struct.pack_into('<8I',header,76,32,4,0x30315844,0,0,0,0,0)
    struct.pack_into('<5I',header,108,0x401008,0xFE00,0,0,0)
    struct.pack_into('<5I',header,128,10,3,4,1,3)
    return bytes(header)+b''.join(np.clip(level[face],0,65504).astype('<f2').tobytes()
                                  for face in range(6) for level in levels)


def run_batch(executable, inputs, output, log, decode=False, diffuse=False):
    output.mkdir(parents=True,exist_ok=True)
    listing = output/'inputs.txt'
    listing.write_text('\n'.join(str(p.resolve()) for p in inputs)+'\n',encoding='utf-8')
    args = [str(executable),'-nologo','-y','-dx10','-f',
            'R16G16B16A16_FLOAT' if decode else 'BC6H_UF16', '-o',str(output.resolve()),'-flist',str(listing.resolve())]
    if diffuse: args += ['-m','1']
    with log.open('ab') as stream:
        subprocess.run(args,stdout=stream,stderr=subprocess.STDOUT,check=True,
                       creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    missing = [p.name for p in inputs if not (output/p.name).is_file()]
    if missing: raise ValueError(f'Texconv did not produce {missing[:3]}; see {log}')


class Cubemaps:
    def __init__(self, source, work):
        self.work = Path(work); self.work.mkdir(parents=True,exist_ok=True)
        self.stack = ExitStack(); self.index = {}; self.assets = {}; self.cache = {}; self.locks = {}
        # Resolve only base-world textures. DLC alternate-world bakes must not win.
        for path in sorted((Path(source)/'Data').glob('Textures*.pak')):
            if '_DLC' in path.name.upper(): continue
            archive = self.stack.enter_context(zipfile.ZipFile(path))
            for name in archive.namelist():
                key = name.replace('\\','/').lower()
                if key.startswith('textures/cubemaps/') and '.dds' in key:
                    self.index[key] = archive,name
        self.families = texture_families(self.index)
        self.executable = compiler(self.work/'compiler')

    def close(self): self.stack.close()

    def standard(self, name):
        family = self.families[name]
        numbers = sorted(int(suffix[1:]) for _,suffix in family if suffix[1:].isdigit())
        if numbers and numbers != list(range(1,max(numbers)+1)): raise ValueError('Incomplete cubemap family')
        return standard_cube(read(*self.index[name]),[read(*self.index[name+'.'+str(i)]) for i in numbers])

    def convert(self, source_paths, destination, dynamic):
        """Return packaged paths, deduplicating identical source schedules."""
        blobs = [self.standard(path) for path in source_paths]
        diffuse = source_paths[0].endswith('_diff.dds')
        key = hashlib.sha256(b'lighting-v1'+bytes((diffuse,dynamic))+b''.join(blobs)).hexdigest()
        with self.locks.setdefault(key,threading.Lock()):
            return self._convert(blobs,key,destination,dynamic,diffuse)

    def _convert(self,blobs,key,destination,dynamic,diffuse):
        if key not in self.cache:
            batch = self.work/key
            batch.mkdir(exist_ok=True)
            times = TARGET_TIMES if dynamic else (0,)
            names=[stamp(t)+('_cm_diff.dds' if diffuse else '_cm.dds') for t in times]
            if (batch/'complete.json').is_file():
                checks=json.loads((batch/'complete.json').read_text())
                if all((batch/'encoded'/n).is_file() and hashlib.sha256((batch/'encoded'/n).read_bytes()).hexdigest()==checks.get(n) for n in names):
                    self.cache[key]=[batch/'encoded'/n for n in names]
                    return self._register(key,destination)
            paths = []
            for i,blob in enumerate(blobs):
                p=batch/f'{i:02d}.dds'; p.write_bytes(blob); paths.append(p)
            log = batch/'texconv.log'
            run_batch(self.executable,paths,batch/'decoded',log,decode=True,diffuse=diffuse)
            samples = [atlas_mips(float_mips((batch/'decoded'/p.name).read_bytes()),diffuse) for p in paths]
            pending = batch/'linear'; pending.mkdir(exist_ok=True)
            inputs=[]
            for t in times:
                a,b,w = time_bracket(SOURCE_TIMES,t) if dynamic else (0,0,0)
                levels=[x*(1-w)+y*w for x,y in zip(samples[a],samples[b])]
                p=pending/(stamp(t)+('_cm_diff.dds' if diffuse else '_cm.dds'))
                p.write_bytes(float_dds(levels));inputs.append(p)
            run_batch(self.executable,inputs,batch/'encoded',log,diffuse=diffuse)
            converted=[]
            for p in inputs:
                out=batch/'encoded'/p.name
                blob=out.read_bytes()
                expected=1 if diffuse else 6
                if struct.unpack_from('<II',blob,12)!=(128,128) or struct.unpack_from('<I',blob,128)[0]!=95 or struct.unpack_from('<I',blob,28)[0]!=expected:
                    raise ValueError('Invalid native atlas texture')
                converted.append(out)
            self.cache[key]=converted
            (batch/'complete.json').write_text(json.dumps({p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in converted}))
            # Scratch can be several GiB; retain only encoded results and logs.
            for folder in ('decoded','linear'): shutil.rmtree(batch/folder)
            for p in paths:p.unlink()
        return self._register(key,destination)

    def _register(self,key,destination):
        result=[]
        for path in self.cache[key]:
            name=destination+'/'+path.name
            self.assets[name]=path;result.append(name)
        return result


def cry_cube_members(blob):
    """Match the native RC's DDS repack: three resident mips, six-face chunks.

    Pixel layout verified against KCD2Mod Tools/rc output for a 128px BC6H cube.
    Preserve the native probe flags as well: RC's generic DDS repack does not
    infer the cubemap preset's suppress-engine-reduction flag.
    This only changes the container/streaming layout, never compressed pixels.
    """
    if blob[:4]!=b'DDS ' or blob[84:88]!=b'DX10':raise ValueError('Expected native DDS')
    size=struct.unpack_from('<I',blob,12)[0]
    mips=struct.unpack_from('<I',blob,28)[0] or 1
    if size!=128 or struct.unpack_from('<5I',blob,128)[:4]!=(95,3,4,1):
        raise ValueError('Unexpected converted cubemap header')
    sizes=[max(1,(size>>i)//4)**2*16 for i in range(mips)]
    face_size=sum(sizes)
    if len(blob)!=148+6*face_size:raise ValueError('Invalid converted cubemap size')
    split=max(0,mips-3)
    header=bytearray(blob[:148])
    struct.pack_into('<I',header,36,0x200011)  # split | cubemap | suppress reduction
    struct.pack_into('<I',header,116,1)
    struct.pack_into('<I',header,124,0x43525946)
    tail=b''.join(blob[148+face*face_size+sum(sizes[:split]):148+(face+1)*face_size] for face in range(6))
    result={'':bytes(header)+tail}
    for i in range(split):
        result['.'+str(split-i)]=b''.join(blob[148+face*face_size+sum(sizes[:i]):148+face*face_size+sum(sizes[:i+1])] for face in range(6))
    return result


def pack_assets(directory, assets, limit=900*1024**2):
    """Stored, sub-1GiB, non-ZIP64 parts under the existing combined mod."""
    directory=Path(directory);directory.mkdir(parents=True,exist_ok=True)
    archive=None;size=0;part=0;paths=[]
    try:
        for name,path in sorted(assets.items()):
            blob=path.read_bytes()
            members=cry_cube_members(blob) if name.endswith('.dds') else {'':blob}
            for suffix,payload in members.items():
                length=len(payload)+len((name+suffix).encode())*2+128
                if length>limit:raise ValueError('Individual lighting asset exceeds shard limit')
                if archive is None or size+length>limit:
                    if archive:archive.close()
                    p=directory/f'gluemapper_lighting_{part:02d}.pak';part+=1;paths.append(p)
                    archive=zipfile.ZipFile(p,'x',zipfile.ZIP_STORED,allowZip64=False);size=0
                archive.writestr(name+suffix,payload);size+=length
    finally:
        if archive:archive.close()
    return paths
