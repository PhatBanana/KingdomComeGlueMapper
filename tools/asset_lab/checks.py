"""The contract checks. Every threshold comes from retail statistics, never from a constant."""
import xml.etree.ElementTree as ET

from . import ERROR, FAIL, PASS, REVIEW, UNSUPPORTED, cgf, hlod, materials, textures
from .native import MIN_SLOT_OBSERVATIONS

# Policy parameters (how to read retail evidence), not claims about the engine.
RETAIL_EXCEPTION_RATE = 0.01
PROXY_SURFACE_MIN = 20
PROXY_SURFACE_SHARE = 0.95
HOT_SPOTS = 25
MIB = 1048576


class Result:
    """Findings are counted exactly; only the first ``limit`` details are retained."""

    def __init__(self, ident, title, scope, limit=200):
        self.id, self.title, self.scope, self.limit = ident, title, scope, limit
        self.findings, self.counts, self.skipped = [], {}, []
        self.details, self.thresholds, self._listed = {}, [], {}

    def add(self, severity, code, subject, detail):
        key = (severity, code)
        self.counts[key] = self.counts.get(key, 0) + 1
        if self._listed.get(severity, 0) < self.limit:
            self._listed[severity] = self._listed.get(severity, 0) + 1
            self.findings.append(dict(severity=severity, code=code, subject=subject, detail=detail))

    def status(self):
        severities = {sev for sev, _ in self.counts}
        if 'error' in severities: return FAIL
        if 'review' in severities: return REVIEW
        return UNSUPPORTED if self.skipped else PASS

    def report(self):
        return dict(id=self.id, title=self.title, status=self.status(), scope=self.scope,
                    counts=[dict(severity=s, code=c, count=n) for (s, c), n in sorted(self.counts.items())],
                    findings=sorted(self.findings, key=lambda f: f['severity'] != 'error'), findings_truncated=sum(self.counts.values()) - len(self.findings),
                    skipped=self.skipped, thresholds=self.thresholds, details=self.details)


class Context:
    def __init__(self, package, native_archives=None, native_stats=None, limit=200):
        self.package, self.native_archives, self.native, self.limit = package, native_archives, native_stats, limit
        self.view = package.merged(native_archives) if native_archives is not None else package
        self._families = None

    def families(self):
        if self._families is None: self._families = list(textures.analyze(self.package))
        return self._families

    def result(self, ident, title, scope):
        return Result(ident, title, scope, self.limit)

    def need_native(self, result, what):
        if self.native is None:
            result.skipped.append(f'{what}: needs retail statistics (--target); not evaluated')
            return False
        return True


def _retail_rate(stats, code, prefix):
    families = stats['dds']['families']
    total = families['by_prefix'].get(prefix, 0)
    return (families['violations'].get(code, {}).get(prefix, 0) / total) if total else 0.0


def piece_budget(ctx):
    r = ctx.result('dds_piece_budget', 'Stream piece budget',
                   'Largest DDS stream piece (pak member or header-implied top level) against the largest retail piece observed. '
                   'Observed, not proven to be the engine limit.')
    records = ctx.families()
    ranked = sorted(records, key=lambda x: -x['piece_bytes'])
    r.details.update(families=len(records), mod_max_bytes=ranked[0]['piece_bytes'] if ranked else 0,
                     hot_spots=[dict(bytes=x['piece_bytes'], mib=round(x['piece_bytes'] / MIB, 2), family=x['base'],
                                     pak=x['pak'], piece=x['piece_member'] or 'base', slot=x['slot'])
                                for x in ranked[:HOT_SPOTS]])
    if not ctx.need_native(r, 'retail piece maximum'): return r
    top = ctx.native['dds']['max_member_bytes']
    r.thresholds.append(dict(id='retail_max_stream_piece_bytes', value=top, mib=top / MIB,
                             basis='observed-not-proven', derived_from=ctx.native['dds']['max_member'],
                             retail_paks=ctx.native['paks']))
    r.details.update(pieces_at_least_half_of_retail_max=sum(1 for x in records if x['piece_bytes'] * 2 >= top),
                     pieces_at_least_three_quarters_of_retail_max=sum(1 for x in records if x['piece_bytes'] * 4 >= top * 3),
                     retail_top_pieces=ctx.native['dds']['top_pieces'][:10],
                     headroom=round(top / ranked[0]['piece_bytes'], 3) if ranked and ranked[0]['piece_bytes'] else None)
    for x in ranked:
        if x['piece_bytes'] <= top: break
        r.add('error', 'piece_over_retail_max', x['base'],
              f'{x["piece_bytes"] / MIB:.1f} MiB piece ({x["piece_member"] or "base"}) exceeds the largest retail piece '
              f'{top / MIB:.1f} MiB; pak {x["pak"]}')
    return r


def dds_structure(ctx):
    r = ctx.result('dds_structure', 'DDS header and streaming-family structure',
                   'Header sanity and base/part completeness for 2D texture families. Cubemaps, arrays and unknown formats are '
                   'counted but their family structure is not modelled.')
    unsupported, modelled = {}, 0
    for x in ctx.families():
        info = x['info']
        if info is not None and 'unsupported' in info:
            unsupported[info['unsupported']] = unsupported.get(info['unsupported'], 0) + 1
        elif info is not None: modelled += 1
        for severity, code, detail in x['problems']:
            if code == 'dds_orphan_parts' and x['base'] in ctx.view.members:
                severity, code, detail = 'review', 'dds_override_parts_only', detail + ' (base found in retail data)'
            elif ctx.native is not None and severity == 'error' and \
                    _retail_rate(ctx.native, code, x['prefix']) > RETAIL_EXCEPTION_RATE:
                severity = 'review'
                detail += f' (retail breaks this rule in {_retail_rate(ctx.native, code, x["prefix"]):.1%} of {x["prefix"]}/ families)'
            r.add(severity, code, x['base'], detail)
    r.details.update(families=len(ctx.families()), modelled=modelled, unsupported_layouts=unsupported)
    if ctx.native is None:
        r.skipped.append('retail baseline for rule severity: not evaluated without --target')
    if unsupported:
        r.skipped.append(f'{sum(unsupported.values())} family layouts not modelled: ' + ', '.join(
            f'{n} {k}' for k, n in sorted(unsupported.items())))
    return r


def slot_formats(ctx):
    r = ctx.result('dds_slot_format', 'Texture slot format against retail usage',
                   f'Base-texture format per name suffix (_diff, _ddna, ...) for suffixes with at least {MIN_SLOT_OBSERVATIONS} '
                   'retail observations. A format retail never uses for that suffix is a review finding.')
    if not ctx.need_native(r, 'retail slot/format histogram'): return r
    retail = ctx.native['dds']['slot_formats']
    seen, judged = {}, 0
    for x in ctx.families():
        info = x['info']
        if info is None: continue
        counts = retail.get(x['slot'], {})
        if sum(counts.values()) < MIN_SLOT_OBSERVATIONS: continue
        judged += 1
        if info['format'] not in counts:
            key = (x['slot'], info['format'])
            seen.setdefault(key, []).append(x['base'])
    for (slot, fmt), names in sorted(seen.items()):
        top = sorted(retail[slot].items(), key=lambda kv: -kv[1])[:3]
        r.add('review', 'slot_format_unobserved', names[0],
              f'{len(names)} families named *{slot} use {fmt}, never seen in retail for this suffix '
              f'(retail mostly: {", ".join(f"{k} x{v}" for k, v in top)}); first {names[0]}')
    r.details.update(judged=judged, min_observations=MIN_SLOT_OBSERVATIONS,
                     unobserved={f'{s}:{f}': len(n) for (s, f), n in seen.items()})
    return r


def cgf_structure(ctx):
    r = ctx.result('cgf_structure', 'CGF mesh structure',
                   'Chunk table, stream sizes, index ranges, subset ranges and finite positions for every .cgf member. '
                   'Does not pair split .cgfm payloads or evaluate material binding.')
    files = meshes = verts = companions = 0
    biggest = 0.0
    rate_note = None
    baseline = (ctx.native or {}).get('cgf')
    for key in ctx.package.keys():
        if key.endswith('.cgfm'): companions += 1
        if not key.endswith('.cgf'): continue
        files += 1
        out = cgf.check(ctx.package.read(key))
        meshes += len(out['meshes'])
        verts += sum(m['verts'] for m in out['meshes'])
        biggest = max(biggest, out['max_position'])
        for code, detail in out['problems']:
            severity = 'error'
            if baseline and baseline['files'] and baseline['codes'].get(code, 0) / baseline['files'] > RETAIL_EXCEPTION_RATE:
                severity = 'review'
            r.add(severity, code, key, detail)
    r.details.update(files=files, meshes=meshes, vertices=verts, max_float_position=biggest, companions_cgfm=companions,
                     retail_files_checked=baseline['files'] if baseline else None,
                     retail_files_failing=baseline['failed'] if baseline else None)
    if baseline is None: r.skipped.append('retail baseline for rule severity: not evaluated without --target')
    if companions: r.skipped.append(f'{companions} .cgfm companion payloads are not paired with their .cgf')
    return r


def _materials(ctx):
    if not hasattr(ctx, '_materials'):
        out, broken = [], []
        for key in ctx.package.keys():
            if not key.endswith('.mtl'): continue
            try: out += materials.parse_materials(ctx.package.read(key), key)
            except ET.ParseError as exc: broken.append((key, str(exc)))
        ctx._materials = (out, broken)
    return ctx._materials


def material_contract(ctx):
    r = ctx.result('material_contract', 'Material shader, generation flags and texture references',
                   'Shader exists in retail data; every StringGenMask flag is declared by the shader extension or observed '
                   'with that shader in retail; flags hidden by DependencyHide; permutations absent from retail; texture '
                   'references resolve in the package or retail data. Numeric GenMask is not judged (see details).')
    mats, broken = _materials(ctx)
    for key, message in broken: r.add('error', 'mtl_xml', key, message)
    r.details.update(files_with_xml_errors=len(broken), materials=len(mats))
    if not ctx.need_native(r, 'shader, permutation and texture-reference contract'): return r
    native = ctx.native
    known = set(native['shaders']['names']) | set(native['materials']['shader_counts'])
    known_base = {k.split('.')[0] for k in known}
    tables, hides = native['shaders']['ext_flags'], native['shaders']['ext_hides']
    observed = native['materials']['observed_flags']
    retail_perms = native['materials']['permutations']
    hidden_uses = native['materials']['hidden_flag_uses']
    novel, shaders, agree, hidden_groups = {}, {}, dict(match=0, mismatch=0, unresolved=0, absent=0), {}
    refs = missing = 0
    for m in mats:
        shader = materials.shader_key(m['shader'])
        shaders[shader] = shaders.get(shader, 0) + 1
        subject = f'{m["path"]}#{m["name"] or m["index"]}'
        if not shader:
            r.add('review', 'material_no_shader', subject, 'Leaf material has no Shader attribute')
            continue
        base = shader.split('.')[0]
        if shader not in known and base not in known_base:
            r.add('error', 'shader_unknown', subject, f'Shader {m["shader"]!r} is not in retail Shaders.pak or retail materials')
        table = tables.get(base, {})
        for flag in m['flags']:
            if flag not in table and flag not in observed.get(shader, ()):
                r.add('error', 'genmask_flag_unknown', subject,
                      f'%{flag} is not declared by {base}.ext and never observed with {m["shader"]} in retail')
        hide_table = {k: tuple(v) for k, v in hides.get(base, {}).items()}
        for flag in materials.hidden_flags(m['flags'], hide_table):
            uses, total = (hidden_uses.get(shader, {}).get(flag) or [0, 0])
            rate = uses / total if total else 0.0
            if rate <= RETAIL_EXCEPTION_RATE:
                hidden_groups.setdefault((shader, flag), dict(rate=rate, total=total, subjects=[]))['subjects'].append(subject)
        combo = '|'.join(sorted(m['flags']))
        if combo not in retail_perms.get(shader, {}):
            novel.setdefault((shader, combo), []).append(subject)
        mask = materials.genmask_value(m['genmask'])
        if mask is None: agree['absent'] += 1
        else:
            computed = materials.mask_from_flags(m['flags'], table) if table and m['flags'] else None
            if computed is None: agree['unresolved'] += 1
            else: agree['match' if computed == mask else 'mismatch'] += 1
        for slot, ref in m['textures']:
            if materials.is_builtin(ref): continue
            refs += 1
            if materials.resolve_texture(ref, ctx.view, m['path']) is None:
                missing += 1
                r.add('error', 'texture_unresolved', subject, f'{slot} texture {ref!r} is in neither the package nor retail data')
    for (shader, flag), g in sorted(hidden_groups.items()):
        r.add('review', 'genmask_flag_hidden', g['subjects'][0],
              f'%{flag} on {shader} is hidden by DependencyHide in {len(g["subjects"])} materials; retail has it hidden in '
              f'{g["rate"]:.1%} of {g["total"]} uses')
    for (shader, combo), subjects in sorted(novel.items()):
        r.add('review', 'permutation_not_in_retail', subjects[0],
              f'{shader} with %{combo.replace("|", "%") or "(no flags)"} is used by {len(subjects)} materials and by no retail '
              'material; the engine builds or loads this permutation without retail precedent')
    r.details.update(shaders=dict(sorted(shaders.items())), distinct_permutations=len({(m["shader"] or "").lower() + '|' + '|'.join(sorted(m["flags"])) for m in mats}),
                     novel_permutations=len(novel), texture_references=refs, texture_references_unresolved=missing,
                     retail_texture_unresolved_rate=round(native['materials']['texture_unresolved'] / max(1, native['materials']['texture_refs']), 4),
                     genmask_numeric_vs_extension=dict(package=agree, retail=native['materials']['genmask_agreement']))
    return r


def material_proxy(ctx):
    r = ctx.result('material_proxy', 'Collision-proxy and Nodraw materials',
                   'Materials that bind the authored collision_proxy texture must use Nodraw (red planes, bug 38). Surface '
                   'types that retail renders only through Nodraw are flagged when a package material draws them. Which '
                   'geometry uses each material is not resolved.')
    mats, _ = _materials(ctx)
    nodraw = proxy = 0
    for m in mats:
        shader = materials.shader_key(m['shader'])
        if shader == 'nodraw': nodraw += 1
        subject = f'{m["path"]}#{m["name"] or m["index"]}'
        for slot, ref in m['textures']:
            if materials.is_proxy_texture(ref) and shader != 'nodraw':
                proxy += 1
                r.add('error', 'proxy_texture_rendered', subject,
                      f'{slot} texture {ref!r} is the collision-proxy texture but the shader is {m["shader"]!r}, not Nodraw')
    r.details.update(materials=len(mats), nodraw_materials=nodraw, proxy_textures_drawn=proxy)
    if not ctx.need_native(r, 'retail-derived proxy surface classes'): return r
    surfaces = ctx.native['materials']['surface_shaders']
    classes = {}
    for surface, counts in surfaces.items():
        total = sum(counts.values())
        if surface and total >= PROXY_SURFACE_MIN and counts.get('nodraw', 0) / total >= PROXY_SURFACE_SHARE:
            classes[surface] = dict(retail_materials=total, nodraw_share=round(counts['nodraw'] / total, 3))
    r.details.update(proxy_surface_classes=classes,
                     retail_proxy_texture_shaders=ctx.native['materials']['proxy_texture_shaders'])
    named = ctx.native['materials'].get('proxy_named', dict(total=0, nodraw=0))
    named_share = named['nodraw'] / named['total'] if named['total'] else 0.0
    r.details['retail_proxy_named_textureless'] = dict(named, nodraw_share=round(named_share, 3))
    by_surface, by_name = {}, {}
    for m in mats:
        surface = (m['surface'] or '')
        shader = materials.shader_key(m['shader'])
        subject = f'{m["path"]}#{m["name"] or m["index"]}'
        if surface in classes and shader != 'nodraw':
            by_surface.setdefault((surface, shader), []).append(subject)
        if named['total'] >= PROXY_SURFACE_MIN and named_share >= PROXY_SURFACE_SHARE and shader != 'nodraw'                 and materials.is_proxy_name(m['name']) and not m['textures']:
            by_name.setdefault((shader, surface), []).append(subject)
    for (surface, shader), subjects in sorted(by_surface.items()):
        r.add('review', 'proxy_surface_drawn', subjects[0],
              f'{len(subjects)} materials use SurfaceType {surface} with {shader}; retail uses Nodraw for '
              f'{classes[surface]["nodraw_share"]:.0%} of {classes[surface]["retail_materials"]} materials with it')
    for (shader, surface), subjects in sorted(by_name.items()):
        r.add('review', 'proxy_named_drawn', subjects[0],
              f'{len(subjects)} texture-less materials named *proxy* (surface {surface or "none"}) use {shader}; retail uses Nodraw '
              f'for {named_share:.0%} of {named["total"]} such materials. Whether their geometry is drawn is not resolved')
    folders = {}
    for subjects in by_name.values():
        for subject in subjects:
            folder = '/'.join(subject.split('#')[0].split('/')[:-1])
            folders[folder] = folders.get(folder, 0) + 1
    r.details['proxy_named_drawn_by_folder'] = dict(sorted(folders.items(), key=lambda kv: -kv[1])[:15])
    r.details['proxy_named_drawn_materials'] = sum(map(len, by_name.values()))
    r.details['proxy_surface_drawn_materials'] = sum(map(len, by_surface.values()))
    return r


def _hlod_levels(ctx):
    if not hasattr(ctx, '_hlod'):
        out = []
        for which, (index, name, size) in enumerate(ctx.package.members.get('terrain/hlods.dat', [])):
            try: xml = ctx.package.read('terrain/hlods.xml', which)
            except (KeyError, IndexError): out.append((which, name, None, 'no terrain/hlods.xml in the same position')); continue
            count = None
            for terrain, row in enumerate(ctx.package.members.get('terrain/terrain.dat', [])):
                if ctx.package.same_folder('terrain/terrain.dat', terrain, 'terrain/hlods.dat', which):
                    count = hlod.terrain_mesh_count(lambda n: ctx.package.read_head('terrain/terrain.dat', n, terrain))
            out.append((which, ctx.package.label_of('terrain/hlods.dat', which),
                        hlod.scan(ctx.package.read('terrain/hlods.dat', which), xml, count), count))
        ctx._hlod = out
    return ctx._hlod


def hlod_structure(ctx):
    r = ctx.result('hlod_structure', 'HLOD placement records',
                   'Block sizes against hlods.xml, finite values, non-degenerate matrices, ordered boxes and mesh ids inside the '
                   'terrain mesh table. Placement correctness is not evaluated.')
    levels = _hlod_levels(ctx)
    if not levels: r.skipped.append('no terrain/hlods.dat in the package')
    for which, pak, result, count in levels:
        if result is None:
            r.add('error', 'hlod_xml_missing', pak, str(count))
            continue
        if count is None: r.skipped.append(f'{pak}: mesh-id range not checked (terrain/terrain.dat absent or unfamiliar)')
        r.details.setdefault('levels', []).append(dict(pak=pak, mesh_table=count, **result['stats'], **result['ranges']))
        for code, n in sorted(result['bad'].items()):
            severity = 'review' if code == 'hlod_far_outside_node' else 'error'
            r.add(severity, code, pak, f'{n} records; first: ' + '; '.join(result['samples'].get(code, [])[:3]))
            r.counts[(severity, code)] = n
    return r


def hlod_ranges(ctx):
    r = ctx.result('hlod_retail_ranges', 'HLOD scale, extent and duplicate placement ranges',
                   'Matrix scale, bounding-box extent and duplicate-placement counts against the ranges present in retail level '
                   'data. A value outside that range is a review finding, not evidence of a fault.')
    levels = _hlod_levels(ctx)
    if not ctx.need_native(r, 'retail hlod ranges'): return r
    retail = ctx.native['hlod']
    r.thresholds.append(dict(id='retail_hlod_ranges', basis='observed-not-proven', value={k: retail[k] for k in
                        ('scale_min', 'scale_max', 'extent_max', 'duplicate_max')}, levels=sorted(retail['levels'])))
    for which, pak, result, _ in levels:
        if result is None: continue
        got = result['ranges']
        if retail['scale_min'] is not None and got['scale_min'] is not None and got['scale_min'] < retail['scale_min']:
            r.add('review', 'hlod_scale_below_retail', pak, f'smallest scale {got["scale_min"]:.4g} < retail {retail["scale_min"]:.4g}')
        if got['scale_max'] > retail['scale_max']:
            r.add('review', 'hlod_scale_above_retail', pak, f'largest scale {got["scale_max"]:.4g} > retail {retail["scale_max"]:.4g}')
        if got['extent_max'] > retail['extent_max']:
            r.add('review', 'hlod_extent_above_retail', pak, f'largest box {got["extent_max"]:.0f} m > retail {retail["extent_max"]:.0f} m')
        if got['duplicate_max'] > retail['duplicate_max']:
            r.add('review', 'hlod_duplicates_above_retail', pak,
                  f'{got["duplicate_max"]} copies of one placement > retail {retail["duplicate_max"]}')
        r.details.setdefault('levels', []).append(dict(pak=pak, **got, wide_boxes=[
            dict(mesh=a, extent_m=b, at=c) for a, b, c in result['samples'].get('_wide', [])][:10]))
    if not levels: r.skipped.append('no terrain/hlods.dat in the package')
    return r


CHECKS = (piece_budget, dds_structure, slot_formats, cgf_structure, material_contract, material_proxy,
          hlod_structure, hlod_ranges)
CHECK_IDS = {'dds_piece_budget': piece_budget, 'dds_structure': dds_structure, 'dds_slot_format': slot_formats,
             'cgf_structure': cgf_structure, 'material_contract': material_contract, 'material_proxy': material_proxy,
             'hlod_structure': hlod_structure, 'hlod_retail_ranges': hlod_ranges}

CONTRACTS = (
    ('engine_stream_limit', 'The true engine page or stream limit is unknown. 64 MiB is only the largest retail piece observed; '
     'a piece below it is not proven safe and a piece above it is a conservative gate.'),
    ('memory_residency', 'Aggregate streaming memory, GPU residency and how many valid pieces load together are not modelled.'),
    ('shader_compile', 'Shader source compilation and the presence of a precompiled permutation in ShaderCache are not checked; '
     'setup_shaders.validate owns compilation.'),
    ('mesh_material_binding', 'Which mesh draws which material is not resolved, so a proxy material on visible geometry is inferred from '
     'materials alone.'),
    ('cubemap_array_families', 'Cubemap, texture-array and unknown-format DDS families are checked by member size only.'),
    ('cgfm_pairing', 'Split .cgf/.cgfm mesh payloads are not paired or validated.'),
    ('terrain_and_svo_data', 'terrain.dat sectors, vegetation tables, SVO and navigation data are not inspected beyond the mesh-table count.'),
    ('render_correctness', 'Colour space, mip content, normal-map encoding and how a texture looks in game are not verified. '
     'This tool is not native-runtime verification.'),
)
