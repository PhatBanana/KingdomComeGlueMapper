"""Retail reference statistics, derived from the installed KCD2 data at run time.

Nothing here is a hard-coded truth about the engine: every threshold the checks use is
measured from the supplied retail install and labelled ``observed-not-proven``.
"""
import hashlib
import json
from pathlib import Path
import xml.etree.ElementTree as ET

from . import cgf, hlod, materials, textures
from .archives import Archives, native_paks

SCHEMA = 4
TOP_PIECES = 20
MIN_SLOT_OBSERVATIONS = 20
SHADER_EXT_PREFIX = 'shaders/'


def fingerprint(archives):
    digest = hashlib.sha256()
    for row in archives.fingerprints: digest.update((row['path'] + row['directory_sha256']).encode())
    return digest.hexdigest()


def _dds(arch, stats):
    families = dict(total=0, modelled=0, unsupported={}, malformed={}, violations={}, by_prefix={},
                    implied_over_max=0)
    slots, top = {}, []
    biggest = (0, '', '')
    members = 0
    pieces = []
    for record in textures.analyze(arch):
        families['total'] += 1
        prefix = record['prefix']
        families['by_prefix'][prefix] = families['by_prefix'].get(prefix, 0) + 1
        members += len(record['sizes'])
        for suffix, size in record['sizes'].items():
            if size > biggest[0]: biggest = (size, record['pak'], record['base'] + ('.' + suffix if suffix else ''))
        pieces.append((record['piece_bytes'], record['base'], record['pak']))
        info = record['info']
        if record['error']: families['malformed'][record['error'][0]] = families['malformed'].get(record['error'][0], 0) + 1
        elif info is not None:
            if 'unsupported' in info: families['unsupported'][info['unsupported']] = families['unsupported'].get(info['unsupported'], 0) + 1
            else: families['modelled'] += 1
            slots.setdefault(record['slot'], {})
            slots[record['slot']][info['format']] = slots[record['slot']].get(info['format'], 0) + 1
        for severity, code, _ in record['problems']:
            bucket = families['violations'].setdefault(code, {})
            bucket[prefix] = bucket.get(prefix, 0) + 1
    pieces.sort(reverse=True)
    top = [dict(bytes=b, family=k, pak=p) for b, k, p in pieces[:TOP_PIECES]]
    members_max = biggest[0]
    families['implied_over_max'] = sum(1 for b, _, _ in pieces if b > members_max)
    stats['dds'] = dict(members=members, max_member_bytes=members_max, max_member=dict(
        pak=biggest[1], name=biggest[2]), top_pieces=top, families=families, slot_formats=slots)


def _shaders(arch, stats):
    ext, hides, names = {}, {}, set()
    for key in arch.names('shaders/'):
        if key.endswith('.ext'):
            name = key.rsplit('/', 1)[1][:-4]
            ext[name], hides[name] = materials.parse_ext(arch.read(key).decode('latin1'))
            hides[name] = {k: [v[0], v[1]] for k, v in hides[name].items()}
        elif key.endswith('.cfx'):
            names.add(key.rsplit('/', 1)[1][:-4])
    stats['shaders'] = dict(names=sorted(names), ext_flags=ext, ext_hides=hides)


def _materials(arch, stats):
    flag_tables = stats['shaders']['ext_flags']
    hide_tables = stats['shaders']['ext_hides']
    shader_counts, observed, perms, surfaces, hidden = {}, {}, {}, {}, {}
    agreement = dict(match=0, mismatch=0, unresolved=0, absent=0)
    proxy_textures, no_shader, leaves, refs, unresolved = {}, 0, 0, 0, 0
    proxy_named = dict(total=0, nodraw=0)
    files = 0
    for key in arch.keys():
        if not key.endswith('.mtl'): continue
        files += 1
        try: parsed = materials.parse_materials(arch.read(key), key)
        except ET.ParseError: continue
        for m in parsed:
            leaves += 1
            shader = materials.shader_key(m['shader'])
            if not shader: no_shader += 1
            shader_counts[shader] = shader_counts.get(shader, 0) + 1
            surfaces.setdefault(m['surface'] or '', {})
            surfaces[m['surface'] or ''][shader] = surfaces[m['surface'] or ''].get(shader, 0) + 1
            mask = materials.genmask_value(m['genmask'])
            observed.setdefault(shader, set()).update(m['flags'])
            combo = '|'.join(sorted(m['flags']))
            perms.setdefault(shader, {})
            perms[shader][combo] = perms[shader].get(combo, 0) + 1
            hide_table = {k: (v[0], v[1]) for k, v in hide_tables.get(shader.split('.')[0], {}).items()}
            for flag in m['flags']:
                row = hidden.setdefault(shader, {}).setdefault(flag, [0, 0])
                row[1] += 1
            for flag in materials.hidden_flags(m['flags'], hide_table): hidden[shader][flag][0] += 1
            table = flag_tables.get(shader.split('.')[0])
            if mask is None: agreement['absent'] += 1
            elif table is None or not m['flags'] and mask: agreement['unresolved'] += 1
            else:
                computed = materials.mask_from_flags(m['flags'], table)
                if computed is None: agreement['unresolved'] += 1
                elif computed == mask: agreement['match'] += 1
                else: agreement['mismatch'] += 1
            if materials.is_proxy_name(m['name']) and not m['textures']:
                proxy_named['total'] += 1
                proxy_named['nodraw'] += shader == 'nodraw'
            for slot, reference in m['textures']:
                if materials.is_builtin(reference): continue
                refs += 1
                if materials.resolve_texture(reference, arch, key) is None: unresolved += 1
                if materials.is_proxy_texture(reference):
                    proxy_textures[shader] = proxy_textures.get(shader, 0) + 1
    stats['materials'] = dict(files=files, leaves=leaves, no_shader=no_shader, shader_counts=shader_counts,
                              observed_flags={k: sorted(v) for k, v in observed.items()}, permutations=perms,
                              surface_shaders=surfaces, genmask_agreement=agreement, hidden_flag_uses=hidden, proxy_named=proxy_named,
                              proxy_texture_shaders=proxy_textures, texture_refs=refs, texture_unresolved=unresolved)


def _cgf(arch, stats):
    files, failed, codes = 0, 0, {}
    biggest = 0.0
    for key in arch.keys():
        if not key.endswith('.cgf'): continue
        files += 1
        result = cgf.check(arch.read(key))
        biggest = max(biggest, result['max_position'])
        if result['problems']:
            failed += 1
            for code, _ in result['problems']: codes[code] = codes.get(code, 0) + 1
    stats['cgf'] = dict(files=files, failed=failed, codes=codes, max_position=biggest)


def _hlod(arch, root, stats):
    levels = {}
    for level in sorted((root / 'Data' / 'Levels').glob('*/level.pak')):
        sub = Archives([level])
        if 'terrain/hlods.dat' not in sub: continue
        result = hlod.scan(sub.read('terrain/hlods.dat'), sub.read('terrain/hlods.xml'))
        levels[level.parent.name] = dict(stats=result['stats'], ranges=result['ranges'], bad=result['bad'])
        sub.close()
    ranges = [v['ranges'] for v in levels.values()]
    stats['hlod'] = dict(levels=levels,
                         scale_min=min((r['scale_min'] for r in ranges if r['scale_min'] is not None), default=None),
                         scale_max=max((r['scale_max'] for r in ranges), default=None),
                         extent_max=max((r['extent_max'] for r in ranges), default=None),
                         duplicate_max=max((r['duplicate_max'] for r in ranges), default=None))


def collect(root, archives=None, progress=lambda *_: None):
    """Scan the retail install at ``root``. ``archives`` may be supplied for synthetic data."""
    root = Path(root)
    arch = archives or Archives(native_paks(root), 'native')
    stats = dict(schema=SCHEMA, root=root.as_posix(), fingerprint=fingerprint(arch),
                 paks=len(arch.paths), members=len(arch.members))
    for name, step in (('dds', lambda: _dds(arch, stats)), ('shaders', lambda: _shaders(arch, stats)),
                       ('materials', lambda: _materials(arch, stats)), ('cgf', lambda: _cgf(arch, stats)),
                       ('hlod', lambda: _hlod(arch, root, stats))):
        progress(name)
        step()
    return stats


def load(root, cache=None, progress=lambda *_: None):
    """Return ``(stats, archives, from_cache)`` for a retail install."""
    root = Path(root)
    arch = Archives(native_paks(root), 'native')
    if cache and Path(cache).is_file():
        try:
            saved = json.loads(Path(cache).read_text(encoding='utf-8'))
            if saved.get('schema') == SCHEMA and saved.get('fingerprint') == fingerprint(arch):
                return saved, arch, True
        except (OSError, ValueError): pass
    stats = collect(root, arch, progress)
    if cache:
        Path(cache).parent.mkdir(parents=True, exist_ok=True)
        Path(cache).write_text(json.dumps(stats), encoding='utf-8')
    return stats, arch, False


def synthetic(max_member_bytes=67108864, **sections):
    """Explicit retail contract for tests and scenarios; every section is caller-supplied or empty."""
    stats = dict(schema=SCHEMA, root='<contract>', fingerprint='contract', paks=0, members=0,
                 dds=dict(members=0, max_member_bytes=max_member_bytes, max_member=dict(pak='<contract>', name=''),
                          top_pieces=[], families=dict(total=0, modelled=0, unsupported={}, malformed={}, violations={},
                                                        by_prefix={}, implied_over_max=0), slot_formats={}),
                 shaders=dict(names=[], ext_flags={}, ext_hides={}),
                 materials=dict(files=0, leaves=0, no_shader=0, shader_counts={}, observed_flags={}, permutations={},
                                surface_shaders={}, genmask_agreement=dict(match=0, mismatch=0, unresolved=0, absent=0),
                                hidden_flag_uses={}, proxy_named=dict(total=0, nodraw=0), proxy_texture_shaders={}, texture_refs=0, texture_unresolved=0),
                 cgf=dict(files=0, failed=0, codes={}, max_position=0.0),
                 hlod=dict(levels={}, scale_min=None, scale_max=0.0, extent_max=0.0, duplicate_max=1))
    for name, value in sections.items(): stats[name] = {**stats[name], **value} if isinstance(value, dict) else value
    return stats
