"""EXPERIMENTAL: rejected after a converted-level load crash; not a build stage.

Lossless CGF header/CGFM payload separation for compiled static meshes.

RC's source-export pass is not a safe round-trip for legacy packed stream 15.
Keep the compiled payload intact instead. Stream loading pairs meshes by node
name; IDs, transforms, materials and physics remain unchanged in both files.
"""
import struct
from clothing_regions import read_chunks, write_chunks
from mesh_lod_metadata import normalize, PREFIXES


def restore_package(package):
    """Remove our experimental split using its preserved complete payloads."""
    from pathlib import Path
    import zipfile
    from setup_campaign import digest
    package = Path(package).resolve()
    changed = {}; removed = []
    for companion in sorted((package/'Data').glob('kingdomcomegluemapper_world_*_meshes.pak')):
        source = companion.with_name(companion.name.removesuffix('_meshes.pak')+'.pak')
        pending = source.with_suffix('.restore-pending')
        replacements = {}
        with zipfile.ZipFile(companion) as payloads, zipfile.ZipFile(source) as headers:
            for name in payloads.namelist():
                if not name.endswith('.cgfm') or not name.lower().startswith(PREFIXES):
                    raise ValueError('Unexpected entry in experimental companion archive')
                base = name[:-1]
                data = payloads.read(name)
                old = headers.read(base)
                # Also support resuming after the restored shard was replaced
                # but before its companion was deleted.
                if old != data:
                    validate_split(old, data)
                replacements[base] = data
            try:
                with zipfile.ZipFile(pending,'x',zipfile.ZIP_STORED,allowZip64=False) as out:
                    for entry in headers.infolist():
                        out.writestr(entry,replacements[entry.filename] if entry.filename in replacements else headers.read(entry))
                with zipfile.ZipFile(pending) as check:
                    if check.testzip() is not None:raise ValueError('Restored archive CRC failed')
                    for name, data in replacements.items():
                        if check.read(name) != data:raise ValueError('Restored mesh differs from preserved payload')
            except Exception:
                pending.unlink(missing_ok=True)
                raise
        pending.replace(source)
        changed[source.relative_to(package).as_posix()] = digest(source)
        removed.append(companion.relative_to(package).as_posix())
        companion.unlink()
    return changed, removed


def split(blob):
    payload = normalize(blob)
    chunks = read_chunks(payload)
    by_id = {c.id: c for c in chunks}
    replacements, removed = {}, set()
    meshes = set()
    for mesh in chunks:
        if mesh.kind != 0x1000:
            continue
        if mesh.version != 0x801 or len(mesh.data) != 264:
            raise ValueError('Unsupported static mesh header')
        flags, _, vertices, indices, _, subset = struct.unpack_from('<6I', mesh.data)
        if flags & 1 or not vertices or not indices:
            continue
        if not flags & 8:
            # Tiny/degenerate-only surfaces have no valid area statistic. Do not
            # turn them into apparently valid empty streaming headers.
            return payload, None
        streams = struct.unpack_from('<16I', mesh.data, 28)
        if flags & 4 or streams[9] or streams[13]:
            raise ValueError('Skinned meshes require the character converter')
        for ident in (subset, *streams):
            if ident:
                if ident not in by_id or by_id[ident].kind not in (0x1016, 0x1017):
                    raise ValueError('Invalid render stream/subset reference')
                removed.add(ident)
        data = bytearray(mesh.data)
        struct.pack_into('<I', data, 0, flags | 1)
        struct.pack_into('<I', data, 20, 0)
        data[28:92] = bytes(64)
        replacements[mesh.id] = bytes(data)
        meshes.add(mesh.id)
    if not meshes:
        return payload, None
    for mesh in chunks:
        if mesh.kind == 0x1000 and mesh.id not in meshes:
            refs = {struct.unpack_from('<I', mesh.data, 20)[0],
                    *struct.unpack_from('<16I', mesh.data, 28)}
            if refs & removed:
                raise ValueError('Render streams are shared with a resident mesh')
    names = []
    referenced = set()
    for node in chunks:
        if node.kind == 0x100b:
            if node.version not in (0x823, 0x824) or len(node.data) < 204:
                raise ValueError('Unsupported static node layout')
            ident = struct.unpack_from('<i', node.data, 64)[0]
            if ident in meshes:
                names.append(node.data[:64].split(b'\0', 1)[0])
                referenced.add(ident)
    if referenced != meshes or (len(names) > 1 and not all(names)) or len(names) != len(set(names)):
        raise ValueError('Render meshes need unique named nodes for streaming')
    header = write_chunks([c for c in chunks if c.id not in removed], replacements)
    validate_split(header, payload)
    return header, payload


def validate_split(header, payload):
    """Check our lossless contract, not merely the presence of two filenames."""
    heads = {c.id: c for c in read_chunks(header)}
    bodies = {c.id: c for c in read_chunks(payload)}
    if not heads.keys() <= bodies.keys():
        raise ValueError('Header references an unrelated payload')
    for ident, h in heads.items():
        b = bodies[ident]
        if (h.kind, h.version) != (b.kind, b.version):
            raise ValueError('Header/payload chunk type mismatch')
        if h.kind == 0x1000 and h.data != b.data:
            expected = bytearray(b.data)
            struct.pack_into('<I', expected, 0, struct.unpack_from('<I', expected)[0] | 1)
            struct.pack_into('<I', expected, 20, 0)
            expected[28:92] = bytes(64)
            if h.data != expected:
                raise ValueError('Header changed mesh bounds, area or physics')
        elif h.data != b.data:
            raise ValueError('Header changed node/material/physics data')
    if any(bodies[i].kind not in (0x1016, 0x1017) for i in bodies.keys() - heads.keys()):
        raise ValueError('Header lost a non-render chunk')


def generated_entries(entries):
    for name, payload in entries:
        lower = name.replace('\\', '/').lower()
        if lower.startswith(PREFIXES) and lower.endswith('.cgf'):
            header, geometry = split(payload)
            yield name, header
            if geometry is not None:
                yield name + 'm', geometry
        else:
            yield name, payload


def validate_pair(header, payload):
    """Validate node-based pairing even when native RC has renumbered chunks."""
    def render_nodes(blob):
        chunks = read_chunks(blob); by_id = {c.id:c for c in chunks}; result = {}
        for node in chunks:
            if node.kind != 0x100b:continue
            mesh = by_id.get(struct.unpack_from('<i',node.data,64)[0])
            if mesh is None or mesh.kind != 0x1000:continue
            flags = struct.unpack_from('<I',mesh.data)[0]
            if not flags & 8:continue
            name = node.data[:64].split(b'\0',1)[0]
            if name in result:raise ValueError('Ambiguous streamed node name')
            result[name] = mesh
        return result, by_id
    heads, _ = render_nodes(header); bodies, chunks = render_nodes(payload)
    if not heads or heads.keys() != bodies.keys():
        raise ValueError('Geometry companion has different render nodes')
    from mesh_lod_metadata import face_area
    for name, head in heads.items():
        body = bodies[name]
        if not struct.unpack_from('<I',head.data)[0] & 1 or struct.unpack_from('<I',body.data)[0] & 1:
            raise ValueError('Expected resident header and loaded geometry payload')
        if head.data[4:20] != body.data[4:20] or head.data[108:140] != body.data[108:140]:
            raise ValueError('Streamed mesh counts/bounds/LOD metadata differ')
        if face_area(body,chunks) is None:
            raise ValueError('Geometry companion has no renderable triangle area')


def upgrade_package(package):
    """Migrate private setup staging with one bounded companion shard per source."""
    from pathlib import Path
    import zipfile
    from setup_campaign import digest
    from setup_progress import progress
    package = Path(package)
    paths = sorted((package/'Data').glob('kingdomcomegluemapper_world_*.pak'))
    available = set()
    for path in paths:
        with zipfile.ZipFile(path) as z:
            available.update(n.lower().replace('\\','/') for n in z.namelist())
    changed = {}; count = 0
    for i, path in enumerate(paths):
        replacements = {}; companions = {}
        with zipfile.ZipFile(path) as source:
            for entry in source.infolist():
                name = entry.filename.replace('\\','/').lower()
                if not name.startswith(PREFIXES) or not name.endswith('.cgf'):
                    continue
                old = source.read(entry)
                header, payload = split(old)
                if payload is not None:
                    if name+'m' in available:
                        raise ValueError('Conflicting geometry companion: '+name+'m')
                    companions[entry.filename+'m'] = payload
                else:
                    needs_payload = any(c.kind == 0x1000 and
                        struct.unpack_from('<I', c.data)[0] & 9 == 9
                        for c in read_chunks(header))
                    if needs_payload and name+'m' not in available:
                        raise ValueError('Missing geometry companion: '+name+'m')
                if header != old:
                    replacements[entry.filename] = header
            if not replacements:
                continue
            pending = path.with_suffix('.stream-pending')
            companion = path.with_name(path.stem+'_meshes.pak')
            companion_pending = companion.with_suffix('.stream-pending')
            if companions and companion.exists():
                raise ValueError('Unexpected existing companion archive: '+str(companion))
            try:
                if companions:
                    with zipfile.ZipFile(companion_pending,'x',zipfile.ZIP_STORED,allowZip64=False) as out:
                        for name, data in companions.items():out.writestr(name,data)
                with zipfile.ZipFile(pending,'x',zipfile.ZIP_STORED,allowZip64=False) as out:
                    for entry in source.infolist():
                        out.writestr(entry,replacements[entry.filename] if entry.filename in replacements else source.read(entry))
                for candidate in [pending]+([companion_pending] if companions else []):
                    if candidate.stat().st_size > 1024**3:
                        raise ValueError('Streaming migration exceeds shard limit; rebuild package')
                    with zipfile.ZipFile(candidate) as check:
                        if check.testzip() is not None:raise ValueError('Streaming archive CRC failed')
            except Exception:
                pending.unlink(missing_ok=True)
                companion_pending.unlink(missing_ok=True)
                raise
        if companions:
            companion_pending.replace(companion)
            changed[companion.relative_to(package).as_posix()] = digest(companion)
            available.update(n.lower().replace('\\','/') for n in companions)
        pending.replace(path)
        changed[path.relative_to(package).as_posix()] = digest(path)
        count += len(companions)
        progress('Separating static mesh streaming payloads',i+1,len(paths),path.name)
    return changed,dict(version=2,split_mesh_files=count,runtime_verified=False)
