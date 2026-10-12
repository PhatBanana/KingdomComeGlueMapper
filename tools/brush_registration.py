"""Repair legacy instancing flags in already-packaged imported static brushes."""
import os
from pathlib import Path
import struct
import tempfile
import zipfile

from building_brushes import LEGACY_STATIC_INSTANCING
from compiled_terrain import parse
from upgrade_map import read
from vegetation import verify_target_hlods


def repair_hlods(data, meshes):
    verify_target_hlods(data)
    result = bytearray(data)
    cursor, records = 4, []
    while cursor < len(data):
        end = cursor + 4 + struct.unpack_from('<I', data, cursor)[0]
        cursor += 4
        while cursor < end:
            kind = struct.unpack_from('<I', data, cursor)[0]
            if kind == 1:
                mesh = struct.unpack_from('<H', data, cursor + 40)[0]
                if mesh >= len(meshes):
                    raise ValueError('Brush mesh outside resource table')
                path = meshes[mesh].replace('\\', '/').lower()
                flags = struct.unpack_from('<Q', data, cursor + 32)[0]
                if path.startswith('gluebuild/') and flags & LEGACY_STATIC_INSTANCING:
                    struct.pack_into('<Q', result, cursor + 32, flags & ~LEGACY_STATIC_INSTANCING)
                    records.append({'offset': cursor, 'mesh': path})
            cursor += 104 if kind == 1 else 64
    verify_target_hlods(result)
    return bytes(result), records


def repair_package(mod):
    """Replace only the imported HLOD flag bytes; atomically detach hardlinks."""
    level = Path(mod) / 'Data/Levels/kcd1_travel/level.pak'
    terrain = level.with_name('terrain.pak')
    with zipfile.ZipFile(terrain) as z:
        meshes = parse(read(z, 'terrain/terrain.dat')).tables['meshes']['paths']
    with zipfile.ZipFile(level) as z:
        blob, records = repair_hlods(read(z, 'terrain/hlods.dat'), meshes)
        if records:
            fd, name = tempfile.mkstemp(suffix='.pak', dir=level.parent)
            os.close(fd)
            try:
                with zipfile.ZipFile(name, 'w', zipfile.ZIP_STORED) as out:
                    for entry in z.infolist():
                        out.writestr(entry, blob if entry.filename == 'terrain/hlods.dat' else read(z, entry.filename))
            except BaseException:
                Path(name).unlink(missing_ok=True)
                raise
    if records:
        os.replace(name, level)
    return {'changed_brushes': len(records), 'records': records}
