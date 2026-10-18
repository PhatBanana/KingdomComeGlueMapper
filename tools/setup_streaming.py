"""Validate the final packaged hierarchy and its referenced proxy resources."""
from contextlib import ExitStack
import copy
from pathlib import Path
import re
import struct
import xml.etree.ElementTree as ET
import zipfile

from campaign_package import references, PREFIXES, safe_name
from texture_streaming import validate_family
from spatial_hlod import read_groups, records
from upgrade_map import read
from compiled_terrain import parse


def family_gaps(packaged, generated):
    """Only require siblings of selected bases; unused source models are not gaps."""
    packaged, generated = set(packaged), set(generated)
    required = set()
    for name in generated:
        lod = re.fullmatch(r'(.+)_lod[1-6]\.cgf', name)
        mip = re.fullmatch(r'(.+\.dds)\.(?:a|\d+a?)', name)
        base = lod[1]+'.cgf' if lod else mip[1] if mip else None
        if base in packaged and name not in packaged: required.add(name)
    return required


def generated_names(converted_data):
    root = Path(converted_data)
    names = set()
    for path in root.glob('gluemapper_*.pak'):
        with zipfile.ZipFile(path) as archive:
            names.update(safe_name(n) for n in archive.namelist() if not n.endswith('/'))
    for prefix in PREFIXES:
        names.update(safe_name(p.relative_to(root).as_posix())
                     for p in (root/prefix).rglob('*') if p.is_file())
    if not names: raise ValueError('Converted world inventory is missing: '+str(root))
    return names


def texture_families(index):
    """Validate final assembled families across shards, including actor overlays."""
    families = {}
    for name in index:
        match = re.fullmatch(r'(.+\.dds)(\.(?:a|\d+a?))?', name)
        if match and not name.startswith(('libs/ui/', 'textures/cubemaps/')):
            families.setdefault(match[1], {})[match[2] or ''] = name
    checked = 0
    for base, members in families.items():
        if '' not in members: continue  # additive mip-only overlays
        def payload(suffix):
            archive, name = index[members[suffix]][-1]
            return read(archive, name)
        blob = payload('')
        if len(blob) >= 128 and struct.unpack_from('<I', blob, 112)[0] & 0xFE00: continue
        parts = {suffix: payload(suffix) if suffix == '.a' else
                 range(index[name][-1][0].getinfo(index[name][-1][1]).file_size)
                 for suffix, name in members.items() if suffix}
        try: validate_family(blob, parts)
        except ValueError as error: raise ValueError(base+': '+str(error)) from error
        checked += 1
    return checked


def validate(package, level='kcd1_travel', converted_data=None):
    package = Path(package)
    with ExitStack() as stack:
        index = {}
        for path in sorted((package/'Data').glob('*.pak')):
            archive = stack.enter_context(zipfile.ZipFile(path))
            for name in archive.namelist():
                key = name.replace('\\', '/').lower()
                index.setdefault(key, []).append((archive, name))
        with zipfile.ZipFile(package/'Data/Levels'/level/'level.pak') as z:
            tree = ET.fromstring(read(z, 'terrain/hlods.xml'))
            blob = read(z, 'terrain/hlods.dat')
        # Parse all detail groups as well as each referenced proxy record.
        ranges = copy.deepcopy(tree)
        for node in ranges.iter('HLod'): node.set('ProxyIndex', '-1')
        near = read_groups(ranges, blob)
        proxies = 0
        for node in tree.iter('HLod'):
            offset, size = int(node.get('DataOffset')), int(node.get('DataSize'))
            if offset < 0 or size < 4 or offset+size > len(blob):
                raise ValueError('Invalid packaged HLOD data range')
            own = records(blob[offset+4:offset+size])
            for child in node:
                i = int(child.get('ProxyIndex', '-1'))
                if i < 0: continue
                if i >= len(own) or len(own[i]) != 104:
                    raise ValueError('Invalid packaged HLOD proxy index')
                proxies += 1
        with zipfile.ZipFile(package/'Data/Levels'/level/'terrain.pak') as z:
            terrain = read(z, 'terrain/terrain.dat')
        parsed = parse(terrain)
        required = references(terrain)
        missing = sorted(n for n in required if n not in index and n+'.cgf' not in index and n+'.mtl' not in index)
        if missing: raise ValueError('Packaged terrain references missing assets: '+', '.join(missing[:20]))
        if not proxies: raise ValueError('Setup lost its spatial HLOD proxies')
        if converted_data is not None:
            gaps = family_gaps(index, generated_names(converted_data))
            if gaps: raise ValueError('Setup omitted generated LOD/mip siblings: '+', '.join(sorted(gaps)[:20]))
        families = texture_families(index)
        from mesh_lod_metadata import PREFIXES as STATIC_PREFIXES
        from mesh_streaming import validate_pair
        from clothing_regions import read_chunks
        mesh_families = 0
        for name in index:
            if not name.startswith(STATIC_PREFIXES) or not name.endswith('.cgf'):continue
            archive, original = index[name][-1]
            header = read(archive, original)
            if not any(c.kind == 0x1000 and struct.unpack_from('<I',c.data)[0] & 9 == 9
                       for c in read_chunks(header)):continue
            if name+'m' not in index:raise ValueError('Missing geometry companion: '+name+'m')
            archive, original = index[name+'m'][-1]
            validate_pair(header, read(archive, original))
            mesh_families += 1
        return dict(level=level, groups=sum(1 for _ in tree.iter('HLod')), proxies=proxies,
            detail_records=len(near)-proxies, mesh_table=len(parsed.tables['meshes']['paths']),
            referenced_resources=len(required), missing_resources=0, texture_families=families,
            mesh_streaming_families=mesh_families,
            external_lods=sum(bool(re.search(r'_lod[1-6]\.cgf$', n)) for n in index),
            numbered_mips=sum(bool(re.search(r'\.dds\.\d+a?$', n)) for n in index),
            source_siblings_checked=converted_data is not None, runtime_verified=False)
