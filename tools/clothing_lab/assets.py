"""Read packaged assets without extracting or modifying an installation."""
from functools import lru_cache
import hashlib
import io
from pathlib import Path, PurePosixPath
import struct
import zipfile

import numpy as np
from PIL import Image
from texture_streaming import layout, validate_family


def key(name):
    name = name.replace('\\', '/').lower()
    if name.startswith('/') or ':' in name or '..' in PurePosixPath(name).parts:
        raise ValueError('Asset reference must stay inside its package')
    return name


class Assets:
    def __init__(self, root, overlay=None):
        self.root = Path(root).resolve()
        if not (self.root / 'Data').is_dir():
            raise ValueError('Choose a built mod folder containing Data, or the installed mod folder.')
        self.index, self.collisions = {}, []
        for path in sorted((self.root / 'Data').glob('*.pak')):
            with zipfile.ZipFile(path) as archive:
                for info in archive.infolist():
                    if info.is_dir(): continue
                    name = key(info.filename)
                    if name in self.index:
                        old = self.index[name]
                        if old[2:] != (info.CRC, info.file_size): self.collisions.append(name)
                    self.index[name] = (path, info.filename, info.CRC, info.file_size)
        if not self.index: raise ValueError('No packaged assets found')
        self.overlay = Path(overlay).resolve() if overlay else None
        if self.overlay:
            if self.overlay == self.root:
                raise ValueError('The developer overlay must be separate from the game package')
            replacements = Assets(self.overlay)
            if replacements.collisions:
                raise ValueError('Conflicting developer overlay entries')
            self.index.update(replacements.index)
            self.collisions = [n for n in self.collisions if n not in replacements.index]
        self.dds_members = {}
        for name in self.index:
            base,separator,suffix=name.rpartition('.')
            if separator and base.endswith('.dds') and suffix.isdigit():
                self.dds_members.setdefault(base,{})['.'+suffix]=name

    def read(self, name):
        name = key(name)
        if name in self.collisions: raise ValueError('Conflicting archive entries: ' + name)
        if name not in self.index: raise FileNotFoundError('Missing asset: ' + name)
        path, member, crc, size = self.index[name]
        if size > 256 * 1024 * 1024: raise ValueError('Asset exceeds inspection size limit: ' + name)
        with zipfile.ZipFile(path) as archive:
            current=archive.getinfo(member)
            if (current.CRC,current.file_size)!=(crc,size):
                raise ValueError('Package changed during inspection; reopen it: '+name)
            return archive.read(member)

    def provenance(self, name):
        path, member, crc, size = self.index[key(name)]
        return dict(archive=path.name, member=member, crc32=f'{crc:08x}', bytes=size)

    def dds(self, name):
        name = key(name)
        base = self.read(name)
        info = layout(base)
        members = {suffix:self.read(member) for suffix,member in self.dds_members.get(name,{}).items()}
        checked = validate_family(base, members)
        data = base[:info['header']] + b''.join(members['.'+str(i)] for i in range(checked['streamed_mips'], 0, -1))
        data += base[info['header']:-8] if base.endswith(b'CExtCEnd') else base[info['header']:]
        return data, info

    def pixels(self, name):
        data, info = self.dds(name)
        fmt = struct.unpack_from('<I', data, 128)[0] if data[84:88] == b'DX10' else None
        if fmt in (2, 10):
            dtype = '<f2' if fmt == 10 else '<f4'
            image = np.frombuffer(data, dtype, count=info['width']*info['height']*4, offset=148).reshape(info['height'], info['width'], 4).astype(np.float32)
            if not np.isfinite(image).all(): raise ValueError('Non-finite texture pixels')
            return image, True
        # Pillow's DDS reader supports the generated BC and byte-channel formats.
        if fmt in (72,75,78,99):
            data=bytearray(data)
            struct.pack_into('<I',data,128,{72:71,75:74,78:77,99:98}[fmt])
        image = np.asarray(Image.open(io.BytesIO(data)).convert('RGBA'), np.float32) / 255
        return image, False

    @lru_cache(maxsize=32)
    def texture(self, name, macro=False):
        pixels, linear = self.pixels(name)
        if linear:
            rgb = np.clip(pixels[:, :, :3], 0, 1)
            # npc_effects.bake_macro_diffuse encodes this inverse for native cloth.
            if macro: rgb = rgb ** (1/2.2)
            pixels[:, :, :3] = np.where(rgb <= .0031308, rgb*12.92, 1.055*rgb**(1/2.4)-.055)
        image = Image.fromarray(np.uint8(np.clip(pixels, 0, 1)*255))
        image.thumbnail((1024, 1024))
        out = io.BytesIO(); image.save(out, format='PNG')
        return out.getvalue()

    def signature(self):
        digest = hashlib.sha256()
        for name, row in sorted(self.index.items()):
            digest.update(f'{name}:{row[2]}:{row[3]}\n'.encode())
        return digest.hexdigest()
