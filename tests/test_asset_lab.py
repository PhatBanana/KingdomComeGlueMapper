"""Render/stream contract gate: structure rules, retail-derived thresholds and honest verdicts."""
import contextlib
import io
import json
import math
from pathlib import Path
import struct
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from asset_lab import cgf, checks, dds, hlod, materials, native, synth
from asset_lab.archives import Archives
from asset_lab.audit import exit_code, run as run_audit, verdict
from asset_lab.__main__ import main as cli
from asset_lab.scenario import run_scenario

MIB = 1048576


def main(argv):
    with contextlib.redirect_stdout(io.StringIO()): return cli(argv)


def context(blobs, stats=None, retail=None):
    package = Archives.blobs(blobs, 'package')
    view = Archives.blobs(retail or {}, 'retail') if stats is not None else None
    return checks.Context(package, view, stats)


def codes(result):
    return {f['code'] for f in result.report()['findings']}


def mtl(shader='Illum', flags='', name='m', surface='mat_wood', textures=(), mask=''):
    tex = ''.join(f'<Texture Map="{m}" File="{f}"/>' for m, f in textures)
    return (f'<Material Name="{name}" Shader="{shader}" GenMask="{mask}" StringGenMask="{flags}" SurfaceType="{surface}">'
            f'<Textures>{tex}</Textures></Material>').encode()


def cgf_blob(verts=4, indices=(0, 1, 2), subsets=((0, 3, 0, 4),), positions=None, break_chunk=False):
    """Smallest CrCh file with one mesh chunk, position/index streams and a subset chunk."""
    positions = positions or [0.0] * (verts * 3)
    chunks = []

    def add(kind, ident, data): chunks.append((kind, 0, ident, bytes(data)))
    mesh = bytearray(92)
    struct.pack_into('<6I', mesh, 0, 0, 0, verts, len(indices), len(subsets), 12)
    struct.pack_into('<I', mesh, 28 + 0 * 4, 10)
    struct.pack_into('<I', mesh, 28 + 5 * 4, 11)
    add(0x1000, 1, mesh)
    add(0x1016, 10, struct.pack('<4I', 0, 0, verts, 12) + bytes(8) + struct.pack(f'<{verts * 3}f', *positions))
    add(0x1016, 11, struct.pack('<4I', 0, 5, len(indices), 2) + bytes(8) + struct.pack(f'<{len(indices)}H', *indices))
    sub = bytearray(16 + 36 * len(subsets))
    struct.pack_into('<2I', sub, 0, 0, len(subsets))
    for i, (first, size, fv, nv) in enumerate(subsets): struct.pack_into('<5I', sub, 16 + 36 * i, first, size, fv, nv, 0)
    add(0x1017, 12, sub)
    body = bytearray()
    table_offset = 16
    offset = table_offset + 16 * len(chunks)
    table = bytearray()
    for kind, ver, ident, data in chunks:
        table += struct.pack('<HHIII', kind, ver, ident, len(data) + (10 ** 6 if break_chunk and ident == 10 else 0), offset + len(body))
        body += data
    return b'CrCh' + struct.pack('<III', 0x746, len(chunks), table_offset) + bytes(table) + bytes(body)


def hlod_files(brushes, size_delta=0):
    """hlods.dat/xml with one block holding brush records: ``(box, mesh, matrix)`` tuples."""
    records = bytearray()
    for box, mesh, matrix in brushes:
        rec = bytearray(104)
        struct.pack_into('<I6f', rec, 0, 1, *box)
        struct.pack_into('<H', rec, 40, mesh)
        struct.pack_into('<12f', rec, 44, *matrix)
        records += rec
    dat = struct.pack('<I', 0) + struct.pack('<I', len(records)) + bytes(records)
    xml = (f'<HLod DataOffset="4" DataSize="{len(records) + 4 + size_delta}" Type="Layer" Pos="0,0,0" Radius="1000" Name="Main"/>').encode()
    return dat, xml


IDENTITY = (1, 0, 0, 5, 0, 1, 0, 5, 0, 0, 1, 5)
BOX = (4, 4, 4, 6, 6, 6)


class DdsTests(unittest.TestCase):
    def test_streamed_family_is_consistent_and_detects_damage(self):
        family = synth.make_family(256, 256, 'BC7', streamed=3)
        info = dds.parse_header(family[''])
        parts = {k: len(v) for k, v in family.items() if k}
        self.assertEqual(dds.family_problems(info, len(family['']), b'', parts, 'x'), [])
        broken = dict(parts)
        del broken['2']
        self.assertEqual(dds.family_problems(info, len(family['']), b'', broken, 'x')[0][1], 'dds_part_missing')
        broken = dict(parts, **{'1': parts['1'] + 16})
        self.assertEqual(dds.family_problems(info, len(family['']), b'', broken, 'x')[0][1], 'dds_part_size')
        extra = dict(parts, **{'9': 4})
        self.assertEqual(dds.family_problems(info, len(family['']), b'', extra, 'x')[0][:2], ('review', 'dds_part_stale'))
        short = len(family['']) - 8
        self.assertEqual(dds.family_problems(info, short, b'', parts, 'x')[0][1], 'dds_resident_mismatch')

    def test_header_rules(self):
        head = bytes(synth.make_family(64, 64, 'BC1')[''])
        for offset, value, code in ((0, b'XXXX', 'dds_magic'), (4, struct.pack('<I', 100), 'dds_header_size'),
                                    (16, struct.pack('<I', 32768), 'dds_dimensions'), (28, struct.pack('<I', 40), 'dds_mip_count')):
            blob = bytearray(head)
            blob[offset:offset + len(value)] = value
            with self.assertRaises(dds.Malformed) as caught: dds.parse_header(bytes(blob))
            self.assertEqual(caught.exception.code, code)

    def test_unmodelled_layouts_are_reported_not_passed(self):
        cube = synth.header(64, 64, 95, 7, cube=True)
        info = dds.parse_header(bytes(cube))
        self.assertEqual(info['unsupported'], 'cubemap')
        self.assertEqual(info['sizes'], [])
        result = checks.dds_structure(context({'t/cube_cm.dds': bytes(cube) + bytes(10)}))
        self.assertEqual(result.report()['status'], 'UNSUPPORTED')
        self.assertEqual(result.details['unsupported_layouts'], {'cubemap': 1})

    def test_slot_class(self):
        self.assertEqual(dds.slot_class('a/b/wall_ddna.dds.3'), '_ddna')
        self.assertEqual(dds.slot_class('a/b/plain.dds'), '')


class PieceBudgetTests(unittest.TestCase):
    def test_pre_fix_float_texture_fails_and_the_capped_one_passes(self):
        # 793bdfb: a 4096 RGBA16F level is a 134 MB piece; the capped 2048 chain tops out at 42.7 MB.
        blobs = {}
        blobs.update(synth.blobs('o/old_diff.dds', synth.make_family(4096, 4096, 'R16G16B16A16_FLOAT', payload=False)))
        blobs.update(synth.blobs('o/new_diff.dds', synth.make_family(2048, 2048, 'R16G16B16A16_FLOAT', payload=False)))
        result = checks.piece_budget(context(blobs, native.synthetic(64 * MIB)))
        report = result.report()
        self.assertEqual(report['status'], 'FAIL')
        self.assertEqual([f['subject'] for f in report['findings']], ['o/old_diff.dds'])
        self.assertEqual(report['thresholds'][0]['value'], 64 * MIB)
        self.assertEqual(report['thresholds'][0]['basis'], 'observed-not-proven')
        self.assertAlmostEqual(report['details']['hot_spots'][0]['mib'], 170.67, places=1)
        self.assertEqual(report['details']['hot_spots'][1]['family'], 'o/new_diff.dds')

    def test_member_size_is_checked_against_the_supplied_retail_maximum_only(self):
        blobs = synth.blobs('o/a_diff.dds', synth.make_family(512, 512, 'BC7', streamed=2))
        biggest = max(len(v) for v in blobs.values())
        self.assertEqual(checks.piece_budget(context(blobs, native.synthetic(biggest))).report()['status'], 'PASS')
        self.assertEqual(checks.piece_budget(context(blobs, native.synthetic(biggest - 1))).report()['status'], 'FAIL')

    def test_without_retail_statistics_the_gate_is_unsupported_not_passed(self):
        blobs = synth.blobs('o/a_diff.dds', synth.make_family(64, 64, 'BC7'))
        report = checks.piece_budget(context(blobs)).report()
        self.assertEqual(report['status'], 'UNSUPPORTED')
        self.assertIn('retail', report['skipped'][0])
        self.assertTrue(report['details']['hot_spots'])

    def test_orphan_parts_are_pieces_too(self):
        blobs = {'o/x_diff.dds.1': bytes(2 * MIB)}
        result = checks.dds_structure(context(blobs))
        self.assertIn('dds_orphan_parts', codes(result))
        self.assertEqual(result.report()['status'], 'FAIL')
        self.assertEqual(checks.piece_budget(context(blobs, native.synthetic(MIB))).report()['status'], 'FAIL')


class SlotFormatTests(unittest.TestCase):
    def test_format_is_judged_only_against_well_observed_suffixes(self):
        stats = native.synthetic()
        stats['dds']['slot_formats'] = {'_diff': {'DX10:BC7_UNORM_SRGB': 40}, '_rare': {'DX10:BC1_UNORM': 3}}
        blobs = {}
        blobs.update(synth.blobs('o/a_diff.dds', synth.make_family(64, 64, 'BC7_SRGB')))
        blobs.update(synth.blobs('o/b_diff.dds', synth.make_family(64, 64, 'R16G16B16A16_FLOAT')))
        blobs.update(synth.blobs('o/c_rare.dds', synth.make_family(64, 64, 'BC7')))
        report = checks.slot_formats(context(blobs, stats)).report()
        self.assertEqual(report['status'], 'REVIEW')
        self.assertEqual(len(report['findings']), 1)
        self.assertIn('R16G16B16A16_FLOAT', report['findings'][0]['detail'])
        self.assertEqual(report['details']['judged'], 2)


class CgfTests(unittest.TestCase):
    def test_clean_mesh(self):
        out = cgf.check(cgf_blob())
        self.assertEqual(out['problems'], [])
        self.assertEqual(out['meshes'][0]['verts'], 4)

    def test_damage_is_named(self):
        self.assertEqual(cgf.check(b'nope' * 8)['problems'][0][0], 'cgf_magic')
        self.assertIn('cgf_index_range', {c for c, _ in cgf.check(cgf_blob(indices=(0, 1, 9)))['problems']})
        self.assertIn('cgf_index_triangles', {c for c, _ in cgf.check(cgf_blob(indices=(0, 1, 2, 3)))['problems']})
        self.assertIn('cgf_position_nonfinite', {c for c, _ in cgf.check(cgf_blob(positions=[math.inf] + [0.0] * 11))['problems']})
        self.assertIn('cgf_subset_range', {c for c, _ in cgf.check(cgf_blob(subsets=((0, 3, 0, 40),)))['problems']})
        self.assertIn('cgf_subset_indices', {c for c, _ in cgf.check(cgf_blob(subsets=((0, 3, 2, 2),)))['problems']})
        self.assertIn('cgf_chunk_truncated', {c for c, _ in cgf.check(cgf_blob(break_chunk=True))['problems']})

    def test_check_scans_every_cgf_member(self):
        blobs = {'a/ok.cgf': cgf_blob(), 'a/bad.cgf': cgf_blob(indices=(0, 1, 9)), 'a/ok.cgfm': b'x'}
        report = checks.cgf_structure(context(blobs)).report()
        self.assertEqual(report['status'], 'FAIL')
        self.assertEqual(report['details']['files'], 2)
        self.assertEqual({f['subject'] for f in report['findings']}, {'a/bad.cgf'})
        self.assertTrue(any('cgfm' in s for s in report['skipped']))

    def test_retail_baseline_downgrades_a_rule_retail_itself_breaks(self):
        stats = native.synthetic(cgf=dict(files=100, failed=50, codes={'cgf_index_range': 50, 'cgf_subset_indices': 50}, max_position=0.0))
        report = checks.cgf_structure(context({'a/bad.cgf': cgf_blob(indices=(0, 1, 9))}, stats)).report()
        self.assertEqual(report['status'], 'REVIEW')


class MaterialTests(unittest.TestCase):
    def stats(self):
        s = native.synthetic()
        s['shaders'] = dict(names=['illum', 'nodraw'], ext_flags={'illum': {'NORMAL_MAP': 1, 'DETAIL_MAPPING': 2, 'CLOTHING_SYSTEM': 4}},
                            ext_hides={'illum': {'DETAIL_MAPPING': [['CLOTHING_SYSTEM'], []]}})
        s['materials'].update(shader_counts={'illum': 100, 'nodraw': 100}, observed_flags={'illum': ['NORMAL_MAP', 'DETAIL_MAPPING', 'CLOTHING_SYSTEM']},
                              permutations={'illum': {'NORMAL_MAP': 90, '': 5}},
                              hidden_flag_uses={'illum': {'DETAIL_MAPPING': [0, 50]}},
                              surface_shaders={'mat_sack': {'nodraw': 50}, 'mat_wood': {'illum': 50}},
                              proxy_named=dict(total=100, nodraw=98))
        return s

    def run_check(self, check, files, retail=None):
        return check(context(files, self.stats(), retail)).report()

    def test_ext_parser_reads_masks_and_hide_rules(self):
        flags, hides = materials.parse_ext('''Property
{
  Name = %DETAIL_MAPPING
  Mask = 0x4000
  DependencyHide = %CLOTHING_SYSTEM%DETAIL_ATLAS
}
// Property { Name = %IGNORED
Property
{
  Name = %ALPHAMASK
  Mask = 0x800000
  DependencyHide = !%DETAIL_MAPPING
}''')
        self.assertEqual(flags, {'DETAIL_MAPPING': 0x4000, 'ALPHAMASK': 0x800000})
        self.assertEqual(hides['ALPHAMASK'], ([], ['DETAIL_MAPPING']))
        self.assertEqual(materials.hidden_flags(['DETAIL_MAPPING', 'CLOTHING_SYSTEM'], hides | {'DETAIL_MAPPING': (['CLOTHING_SYSTEM'], [])}), ['DETAIL_MAPPING'])
        self.assertEqual(materials.hidden_flags(['ALPHAMASK'], hides), ['ALPHAMASK'])

    def test_clean_material_has_no_findings(self):
        files = {'m/a.mtl': mtl(flags='%NORMAL_MAP', textures=[('Diffuse', 'm/t_diff.dds')]), 'm/t_diff.dds': b'x'}
        report = self.run_check(checks.material_contract, files)
        self.assertEqual(report['status'], 'PASS', report['findings'])

    def test_each_contract_violation_is_named(self):
        files = {
            'm/shader.mtl': mtl(shader='Unheard'),
            'm/flag.mtl': mtl(flags='%NORMAL_MAP%NOT_A_FLAG'),
            'm/hidden.mtl': mtl(flags='%DETAIL_MAPPING%CLOTHING_SYSTEM'),
            'm/novel.mtl': mtl(flags='%CLOTHING_SYSTEM'),
            'm/texture.mtl': mtl(textures=[('Diffuse', 'm/missing_diff.dds')]),
            'm/broken.mtl': b'<Material',
        }
        report = self.run_check(checks.material_contract, files)
        found = {f['code']: f for f in report['findings']}
        self.assertEqual(report['status'], 'FAIL')
        for code in ('shader_unknown', 'genmask_flag_unknown', 'genmask_flag_hidden', 'permutation_not_in_retail',
                     'texture_unresolved', 'mtl_xml'):
            self.assertIn(code, found)
        self.assertEqual(found['genmask_flag_unknown']['severity'], 'error')
        self.assertEqual(found['permutation_not_in_retail']['severity'], 'review')

    def test_texture_may_resolve_in_retail_data_or_next_to_the_material(self):
        files = {'m/a.mtl': mtl(textures=[('Diffuse', 'textures/native_diff.dds'), ('Bumpmap', './local_ddna.tif'),
                                           ('Environment', 'nearest_cubemap'), ('Custom', '$White')]), 'm/local_ddna.dds': b'x'}
        report = self.run_check(checks.material_contract, files, retail={'textures/native_diff.dds': b'x'})
        self.assertNotIn('texture_unresolved', {f['code'] for f in report['findings']})

    def test_numeric_genmask_is_reported_not_judged(self):
        files = {'m/a.mtl': mtl(flags='%NORMAL_MAP', mask='9999')}
        report = self.run_check(checks.material_contract, files)
        self.assertEqual(report['details']['genmask_numeric_vs_extension']['package']['mismatch'], 1)
        self.assertNotIn('genmask_mismatch', {f['code'] for f in report['findings']})

    def test_collision_proxy_texture_must_use_nodraw(self):
        bad = mtl(shader='Illum', textures=[('Diffuse', 'materials/special/collision_proxy.dds')])
        good = mtl(shader='Nodraw', textures=[('Diffuse', 'materials/special/collision_proxy.dds')], surface='mat_player_only')
        report = self.run_check(checks.material_proxy, {'m/bad.mtl': bad, 'm/good.mtl': good})
        self.assertEqual(report['status'], 'FAIL')
        self.assertEqual([f['subject'] for f in report['findings'] if f['code'] == 'proxy_texture_rendered'], ['m/bad.mtl#m'])
        self.assertEqual(report['details']['nodraw_materials'], 1)

    def test_proxy_classes_are_derived_from_retail_surface_and_name_statistics(self):
        files = {'m/a.mtl': mtl(shader='Illum', surface='mat_sack', name='proxy_mat_sack'),
                 'm/b.mtl': mtl(shader='Illum', surface='mat_wood', name='wall'),
                 'm/c.mtl': mtl(shader='Nodraw', surface='mat_sack', name='proxy')}
        report = self.run_check(checks.material_proxy, files)
        self.assertEqual({f['code'] for f in report['findings']}, {'proxy_surface_drawn', 'proxy_named_drawn'})
        self.assertEqual(report['details']['proxy_surface_classes'].keys(), {'mat_sack'})

    def test_proxy_without_retail_statistics_still_catches_the_texture_rule_but_is_unsupported_otherwise(self):
        files = {'m/a.mtl': mtl(shader='Illum', textures=[('Diffuse', 'x/collision_proxy.dds')])}
        self.assertEqual(checks.material_proxy(context(files)).report()['status'], 'FAIL')
        self.assertEqual(checks.material_proxy(context({'m/a.mtl': mtl()})).report()['status'], 'UNSUPPORTED')


class HlodTests(unittest.TestCase):
    def test_clean_records(self):
        dat, xml = hlod_files([(BOX, 3, IDENTITY)])
        out = hlod.scan(dat, xml, 10)
        self.assertEqual(out['bad'], {})
        self.assertEqual(out['stats']['brushes'], 1)
        self.assertAlmostEqual(out['ranges']['scale_max'], 1.0)

    def test_structural_faults_are_named(self):
        zero = (0, 0, 0, 5, 0, 0, 0, 5, 0, 0, 0, 5)
        nan = (math.nan,) + IDENTITY[1:]
        inverted = (6, 4, 4, 4, 6, 6)
        dat, xml = hlod_files([(BOX, 3, zero), (BOX, 3, nan), (inverted, 3, IDENTITY), (BOX, 99, IDENTITY)])
        bad = hlod.scan(dat, xml, 10)['bad']
        for code in ('hlod_degenerate_matrix', 'hlod_nonfinite', 'hlod_inverted_box', 'hlod_mesh_id_range'):
            self.assertIn(code, bad)
        dat, xml = hlod_files([(BOX, 3, IDENTITY)], size_delta=4)
        self.assertIn('hlod_node_size', hlod.scan(dat, xml, 10)['bad'])

    def test_mesh_table_count_reads_only_the_head(self):
        table = struct.pack('<4BI', 29, 0, 6, 0, 0) + bytes(24) + struct.pack('<I', 2) + bytes(720) + struct.pack('<I', 77)
        self.assertEqual(hlod.terrain_mesh_count(lambda n: table[:n]), 77)
        self.assertIsNone(hlod.terrain_mesh_count(lambda n: b'bad' * 20))

    def test_retail_ranges_come_from_the_supplied_statistics(self):
        dat, xml = hlod_files([(BOX, 3, (5, 0, 0, 5, 0, 5, 0, 5, 0, 0, 5, 5))])
        files = {'terrain/hlods.dat': dat, 'terrain/hlods.xml': xml}
        stats = native.synthetic(hlod=dict(scale_min=0.1, scale_max=4.0, extent_max=100.0, duplicate_max=2))
        report = checks.hlod_ranges(context(files, stats)).report()
        self.assertEqual({f['code'] for f in report['findings']}, {'hlod_scale_above_retail'})
        stats['hlod']['scale_max'] = 5.0
        self.assertEqual(checks.hlod_ranges(context(files, stats)).report()['status'], 'PASS')
        self.assertEqual(checks.hlod_ranges(context(files)).report()['status'], 'UNSUPPORTED')

    def test_mesh_id_range_needs_the_terrain_mesh_table(self):
        dat, xml = hlod_files([(BOX, 500, IDENTITY)])
        files = {'terrain/hlods.dat': dat, 'terrain/hlods.xml': xml}
        report = checks.hlod_structure(context(files)).report()
        self.assertEqual(report['status'], 'UNSUPPORTED')
        table = struct.pack('<4BI', 29, 0, 6, 0, 0) + bytes(24) + struct.pack('<I', 0) + struct.pack('<I', 10)
        files['terrain/terrain.dat'] = table
        self.assertEqual(checks.hlod_structure(context(files)).report()['status'], 'FAIL')


class ArchiveTests(unittest.TestCase):
    def test_pak_reads_head_tail_and_whole_members_without_extracting(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'a.pak'
            with zipfile.ZipFile(path, 'w') as z:
                z.writestr('Dir/Stored.bin', bytes(range(200)), zipfile.ZIP_STORED)
                z.writestr('Dir/Packed.bin', bytes(range(200)) * 3, zipfile.ZIP_DEFLATED)
            a = Archives([path])
            self.assertEqual(a.read_head('dir/stored.bin', 4), bytes(range(4)))
            self.assertEqual(a.read_tail('dir/stored.bin', 3), bytes([197, 198, 199]))
            self.assertEqual(a.read_tail('DIR\\PACKED.BIN', 3), bytes([197, 198, 199]))
            self.assertEqual(len(a.read('dir/packed.bin')), 600)
            self.assertEqual(a.fingerprints[0]['members'], 2)
            self.assertEqual(a.pak_of('dir/stored.bin'), 'a.pak')
            self.assertEqual(sorted(a.names('dir/')), ['dir/packed.bin', 'dir/stored.bin'])
            a.close()


class ResultSemanticsTests(unittest.TestCase):
    def test_skipped_part_prevents_pass_but_not_a_finding(self):
        r = checks.Result('x', 'x', 's')
        self.assertEqual(r.status(), 'PASS')
        r.skipped.append('not run')
        self.assertEqual(r.status(), 'UNSUPPORTED')
        r.add('review', 'c', 's', 'd')
        self.assertEqual(r.status(), 'REVIEW')
        r.add('error', 'c2', 's', 'd')
        self.assertEqual(r.status(), 'FAIL')

    def test_counts_stay_exact_when_details_are_capped_and_errors_are_listed_first(self):
        r = checks.Result('x', 'x', 's', limit=3)
        for i in range(10): r.add('review', 'many', f's{i}', 'd')
        r.add('error', 'one', 'e', 'd')
        report = r.report()
        self.assertEqual(sum(c['count'] for c in report['counts']), 11)
        self.assertEqual(report['findings'][0]['code'], 'one')
        self.assertEqual(report['findings_truncated'], 7)

    def test_verdict_never_claims_a_pass(self):
        self.assertEqual(verdict([dict(status='PASS')]), 'NO_FINDINGS_IN_MODELLED_SCOPE')
        self.assertEqual(verdict([dict(status='PASS'), dict(status='UNSUPPORTED')]), 'INCOMPLETE')
        self.assertEqual(verdict([dict(status='REVIEW'), dict(status='UNSUPPORTED')]), 'REVIEW')
        self.assertEqual(verdict([dict(status='ERROR'), dict(status='PASS')]), 'FAIL')

    def test_a_crashing_check_is_an_error_not_a_pass(self):
        from asset_lab.audit import execute
        original = checks.CHECK_IDS['cgf_structure']
        checks.CHECK_IDS['cgf_structure'] = lambda ctx: 1 / 0
        try: results = execute(context({}), ['cgf_structure'])
        finally: checks.CHECK_IDS['cgf_structure'] = original
        self.assertEqual(results[0]['status'], 'ERROR')
        self.assertEqual(exit_code(dict(checks=results)), 1)


def make_install(root, largest):
    data = root / 'Data'
    (data / 'Levels' / 'town').mkdir(parents=True)
    (root / 'Engine').mkdir()
    with zipfile.ZipFile(data / 'Textures-part0.pak', 'w') as z:
        z.writestr('Textures/a/wall_diff.dds.1', bytes(largest))
        z.writestr('Textures/a/wall_diff.dds.2', bytes(1024))
    with zipfile.ZipFile(data / 'IPL_Textures-part0.pak', 'w') as z:
        for i in range(3):
            z.writestr(f'Textures/a/f{i}_diff.dds', bytes(synth.make_family(16, 16, 'BC7')['']))
    with zipfile.ZipFile(root / 'Engine' / 'Shaders.pak', 'w') as z:
        z.writestr('Shaders/Illum.ext', 'Property\n{\n  Name = %NORMAL_MAP\n  Mask = 0x1\n}\n')
        z.writestr('Shaders/HWScripts/CryFX/Illum.cfx', 'x')
    with zipfile.ZipFile(data / 'IPL_Objects-part0.pak', 'w') as z:
        z.writestr('Objects/a.mtl', mtl(flags='%NORMAL_MAP', surface='mat_wood'))
        z.writestr('Objects/b.mtl', mtl(shader='Nodraw', name='proxy', surface='mat_sack'))
        z.writestr('Objects/a.cgf', cgf_blob())
    dat, xml = hlod_files([(BOX, 1, IDENTITY)])
    with zipfile.ZipFile(data / 'Levels' / 'town' / 'level.pak', 'w') as z:
        z.writestr('terrain/hlods.dat', dat)
        z.writestr('terrain/hlods.xml', xml)


class NativeStatisticsTests(unittest.TestCase):
    def test_thresholds_are_measured_from_the_install_and_cached_by_fingerprint(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / 'kcd2'
            make_install(root, 5 * MIB)
            cache = Path(tmp) / 'cache.json'
            stats, arch, cached = native.load(root, cache)
            arch.close()
            self.assertFalse(cached)
            self.assertEqual(stats['dds']['max_member_bytes'], 5 * MIB)
            self.assertEqual(stats['dds']['max_member']['name'], 'textures/a/wall_diff.dds.1')
            self.assertEqual(stats['dds']['slot_formats']['_diff'], {'DX10:BC7_UNORM': 3})
            self.assertEqual(stats['shaders']['ext_flags'], {'illum': {'NORMAL_MAP': 1}})
            self.assertEqual(stats['materials']['permutations']['illum'], {'NORMAL_MAP': 1})
            self.assertEqual(stats['materials']['proxy_named'], dict(total=1, nodraw=1))
            self.assertEqual(stats['cgf']['files'], 1)
            self.assertEqual(stats['hlod']['extent_max'], 2.0)
            self.assertEqual(stats['dds']['families']['violations']['dds_orphan_parts'], {'textures': 1})
            self.assertTrue(native.load(root, cache)[2])
            self.make_install_changed(root)
            self.assertFalse(native.load(root, cache)[2])

    def make_install_changed(self, root):
        with zipfile.ZipFile(root / 'Data' / 'Textures-part0.pak', 'a') as z:
            z.writestr('Textures/a/other_diff.dds.1', bytes(10))

    def test_a_different_install_moves_the_threshold(self):
        for largest in (3 * MIB, 7 * MIB):
            with tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp) / 'kcd2'
                make_install(root, largest)
                stats, arch, _ = native.load(root)
                arch.close()
                self.assertEqual(stats['dds']['max_member_bytes'], largest)


class AuditEndToEndTests(unittest.TestCase):
    def build(self, root, float_size):
        mod = root / 'mod' / 'Data'
        mod.mkdir(parents=True)
        with zipfile.ZipFile(mod / 'mod.pak', 'w', zipfile.ZIP_STORED) as z:
            for name, data in synth.blobs('o/a_diff.dds', synth.make_family(64, 64, 'BC7_SRGB', streamed=2)).items(): z.writestr(name, data)
            for name, data in synth.blobs('o/f_diff.dds', synth.make_family(float_size, float_size, 'R16G16B16A16_FLOAT', payload=False)).items():
                z.writestr(name, data)
            z.writestr('o/a.cgf', cgf_blob())
            z.writestr('o/a.mtl', mtl(flags='%NORMAL_MAP', textures=[('Diffuse', 'o/a_diff.dds')]))
        return root / 'mod'

    def test_audit_writes_reports_and_exit_code_follows_failures(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            install = root / 'kcd2'
            make_install(install, 2 * MIB)
            mod = self.build(root, 2048)
            out = root / 'out'
            code = main(['audit', str(mod), '--target', str(install), '--native-cache', str(root / 'c.json'), '--output', str(out)])
            report = json.loads((out / 'audit.json').read_text())
            self.assertEqual(code, 1)
            self.assertEqual(report['verdict'], 'FAIL')
            self.assertFalse(report['native_runtime_verified'])
            by_id = {c['id']: c for c in report['checks']}
            self.assertEqual(by_id['dds_piece_budget']['status'], 'FAIL')
            self.assertEqual(by_id['cgf_structure']['status'], 'PASS')
            self.assertEqual(len(report['contracts']), len(checks.CONTRACTS))
            self.assertTrue(all(c['status'] == 'UNSUPPORTED' for c in report['contracts']))
            self.assertEqual(report['thresholds'][0]['value'], 2 * MIB)
            suite = ET.parse(out / 'junit.xml').getroot()
            self.assertEqual(suite.get('failures'), str(sum(c['status'] == 'FAIL' for c in report['checks'])))
            self.assertIn('Largest streaming pieces', (out / 'audit.html').read_text(encoding='utf-8'))

    def test_without_target_native_checks_are_unsupported_and_strict_fails_them(self):
        with tempfile.TemporaryDirectory() as tmp:
            mod = self.build(Path(tmp), 64)
            out = Path(tmp) / 'out'
            self.assertEqual(main(['audit', str(mod), '--output', str(out), '--check', 'dds_piece_budget']), 0)
            self.assertEqual(json.loads((out / 'audit.json').read_text())['verdict'], 'INCOMPLETE')
            self.assertEqual(main(['audit', str(mod), '--output', str(out), '--check', 'dds_piece_budget', '--strict']), 1)

    def test_inventory_lists_without_a_verdict(self):
        with tempfile.TemporaryDirectory() as tmp:
            mod = self.build(Path(tmp), 64)
            out = Path(tmp) / 'inv.json'
            self.assertEqual(main(['inventory', str(mod), '--output', str(out)]), 0)
            report = json.loads(out.read_text())
            self.assertNotIn('verdict', report)
            self.assertEqual(report['dds']['families'], 2)
            self.assertEqual(report['materials']['shaders'], {'illum': 1})


class ScenarioTests(unittest.TestCase):
    def test_scenario_asserts_status_and_codes(self):
        scenario = dict(name='pre-793bdfb float texture', members={
            'o/old_diff.dds': dict(dds=dict(width=4096, height=4096, format='R16G16B16A16_FLOAT', payload=False))},
            target=dict(contract=dict(max_member_bytes=64 * MIB)), checks=['dds_piece_budget'],
            assertions=[dict(check='dds_piece_budget', status='FAIL', codes_include=['piece_over_retail_max'])])
        self.assertEqual(run_scenario(scenario)['status'], 'PASS')
        scenario['assertions'][0]['status'] = 'PASS'
        self.assertEqual(run_scenario(scenario)['status'], 'FAIL')

    def test_cli_run_reports_errors_for_bad_scenarios(self):
        with tempfile.TemporaryDirectory() as tmp:
            bad = Path(tmp) / 'bad.json'
            bad.write_text(json.dumps(dict(name='x', members={}, checks=['nope'], assertions=[])))
            good = Path(tmp) / 'good.json'
            good.write_text(json.dumps(dict(name='g', members={'o/a_diff.dds': dict(dds=dict(width=64, height=64))},
                                            checks=['dds_structure'], assertions=[dict(check='dds_structure', status='UNSUPPORTED')])))
            self.assertEqual(main(['run', str(good), '--output', str(Path(tmp) / 'ok')]), 0)
            self.assertEqual(main(['run', str(good), str(bad), '--output', str(Path(tmp) / 'out')]), 1)
            results = json.loads((Path(tmp) / 'out' / 'results.json').read_text())['results']
            self.assertEqual([r['status'] for r in results], ['PASS', 'ERROR'])
            self.assertTrue((Path(tmp) / 'out' / 'report.html').is_file())


if __name__ == '__main__':
    unittest.main()
