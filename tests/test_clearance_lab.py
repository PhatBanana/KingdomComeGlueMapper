"""Clearance lab: synthetic blobs for readers and geometry; no game data."""
import contextlib
import io
import json
from pathlib import Path
import struct
import sys
import tempfile
import unittest
import xml.etree.ElementTree as E

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from clearance_lab import Unsupported, geometry as g
from clearance_lab.audit import audit, ASSUMPTIONS, check_boundary, prepare
from clearance_lab.runner import normalize_world, run_scenario
from clearance_lab.source import (Files, walk_hlods, package_brush, terrain_tables, cgf_info, surface_table,
                                  designer_volumes, interactions_from_mission, blocks)
from clearance_lab.__main__ import main

SURFACES_XML = b'''<SurfaceTypes><!-- comment -->
<SurfaceType name="mat_default"><Physics dbg_color="1"/></SurfaceType>
<SurfaceType name="mat_player_only"><Physics player_only="1"/><AI navIgnored="1"/></SurfaceType>
<SurfaceType name="mat_horse_only"><Physics horse_only="1"/></SurfaceType>
<SurfaceType name="mat_level_barrier"><Physics player_only="1"/>
  <Barrier distance="10" slowdown="1" monologMetaroleId="HRAC_NEMUZE_Z_MAPY"/></SurfaceType>
<SurfaceType name="mat_nodraw_designer"><Physics pierceability="11"/></SurfaceType>
<SurfaceType name="mat_mudwater"><Physics/><AI movementSpeedMult="0.7"/></SurfaceType>
</SurfaceTypes>'''
SURFACES = surface_table(SURFACES_XML)
IDENTITY = (1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0)


def at(x, y, z=0.0, yaw=0.0):
    import math
    c, s = math.cos(yaw), math.sin(yaw)
    return (c, -s, 0, x, s, c, 0, y, 0, 0, 1, z)


def vol(vid, surface, matrix, lo, hi, **kw):
    return dict(dict(id=vid, surface=surface, matrix=matrix, local_min=lo, local_max=hi), **kw)


def world(volumes=(), interactions=(), roads=(), extent=(0, 0, 100, 100)):
    return normalize_world(dict(surfaces=SURFACES, volumes=list(volumes), interactions=list(interactions),
                                roads=list(roads), extent=extent))


def ring(extent=100.0, inset=10.0, thick=2.0, drop=None, shrink=0.0):
    """Four wall panels (local x = length, local y = -thick..0) forming a closed square."""
    a, b = inset, extent - inset; L = b - a
    panels = [('s', at(a, a + thick)), ('e', at(b, a, yaw=1.5707963267948966)),
              ('n', at(b, b, yaw=3.141592653589793)), ('w', at(a, b, yaw=-1.5707963267948966))]
    out = []
    for name, m in panels:
        if name == drop: continue
        out.append(vol('ring_' + name, 'mat_level_barrier', m, (0, -thick, 0), (L + thick - shrink, 0, 250)))
    return out


def cgf(lo, hi, material, vertices=None):
    """Minimal static CGF: material-name chunk, positions stream and mesh chunk."""
    chunks = []
    chunks.append((0x1014, 0x802, 2, material.encode().ljust(128, b'\0') + bytes(8)))
    if vertices is not None:
        chunks.append((0x1016, 0x800, 5, struct.pack('<6I', 0, 0, len(vertices), 12, 0, 0) + b''.join(struct.pack('<3f', *v) for v in vertices)))
    mesh = bytearray(264)
    struct.pack_into('<I', mesh, 28, 5 if vertices is not None else 0)
    struct.pack_into('<3f', mesh, 108, *lo); struct.pack_into('<3f', mesh, 120, *hi)
    chunks.append((0x1000, 0x801, 10, bytes(mesh)))
    table = 16; body = bytearray(); entries = []
    offset = table + 16 * len(chunks)
    for kind, version, ident, data in chunks:
        entries.append(struct.pack('<HHIII', kind, version, ident, len(data), offset + len(body))); body += data
    return b'CrCh' + struct.pack('<III', 0x746, len(chunks), table) + b''.join(entries) + bytes(body)


def hlods(records):
    body = b''.join(records)
    return struct.pack('<I', 0) + struct.pack('<I', len(body)) + body


def brush(mesh, matrix, aabb, material=-1, layer=0):
    r = bytearray(104)
    struct.pack_into('<I', r, 0, 1); struct.pack_into('<6f', r, 4, *aabb); struct.pack_into('<H', r, 28, layer)
    struct.pack_into('<H', r, 40, mesh); struct.pack_into('<12f', r, 44, *matrix); struct.pack_into('<i', r, 96, material)
    return bytes(r)


def tables(meshes, materials=()):
    out = bytearray(32) + struct.pack('<I', 0)
    for paths in (meshes, materials):
        out += struct.pack('<I', len(paths))
        for p in paths: out += p.encode().ljust(256, b'\0')
    return bytes(out)


class ReaderTests(unittest.TestCase):
    def test_package_blobs_resolve_designer_volume_surface_through_mesh_material(self):
        verts = [(0, -2, 0), (20, 0, 5), (10, -1, 2)]
        files = Files.blobs({
            'gluebuild/setup_designer/mesh0.cgf': cgf((0, 0, 0), (1, 1, 1), 'gluebuild/setup_designer/m0', verts),
            'gluebuild/setup_designer/m0.mtl': b'<Material Shader="Nodraw" SurfaceType="mat_level_barrier"/>',
            'objects/house.cgf': cgf((0, 0, 0), (1, 1, 1), 'objects/house')})
        meshes = ['objects/house.cgf', 'gluebuild/setup_designer/mesh0.cgf']
        data = hlods([brush(0, IDENTITY, (0,) * 6), brush(1, at(5, 6, 7), (5, 4, 7, 25, 6, 12))])
        records = [(o, package_brush(data, o)) for o, k in walk_hlods(data) if k == 1]
        vols, bad = designer_volumes(records, terrain_tables(tables(meshes))['meshes'], [], lambda p: p, files, None, 'package')
        self.assertEqual(bad, [])
        self.assertEqual(len(vols), 1)
        v = vols[0]
        self.assertEqual((v['surface'], v['bounds_source'], v['local_min'], v['local_max']),
                         ('mat_level_barrier', 'float3_vertices', (0, -2, 0), (20, 0, 5)))
        self.assertEqual(v['matrix'][3], 5)

    def test_unresolved_material_or_mesh_is_unsupported_never_dropped(self):
        files = Files.blobs({'gluebuild/setup_designer/mesh0.cgf': cgf((0, 0, 0), (1, 1, 1), 'gluebuild/setup_designer/missing')})
        data = hlods([brush(0, IDENTITY, (0,) * 6), brush(1, IDENTITY, (0,) * 6)])
        records = [(o, package_brush(data, o)) for o, k in walk_hlods(data)]
        vols, bad = designer_volumes(records, ['gluebuild/setup_designer/mesh0.cgf', 'gluebuild/setup_designer/mesh1.cgf'],
                                     [], lambda p: p, files, None, 'package')
        self.assertEqual(vols, [])
        self.assertEqual(len(bad), 2)
        self.assertTrue(any('mesh unresolved' in b['reason'] for b in bad))
        self.assertTrue(any('surface type unresolved' in b['reason'] for b in bad))

    def test_hlods_walker_rejects_unknown_kinds_and_overruns(self):
        with self.assertRaises(Unsupported): list(walk_hlods(hlods([struct.pack('<I', 9) + bytes(60)])))
        bad = struct.pack('<I', 0) + struct.pack('<I', 50) + brush(0, IDENTITY, (0,) * 6)
        with self.assertRaises(Unsupported): list(walk_hlods(bad))

    def test_cgf_requires_one_mesh_and_one_material_name(self):
        info = cgf_info(cgf((0, -1, 0), (3, 0, 2), 'm'))
        self.assertEqual(info['bounds_source'], 'mesh_header')
        with self.assertRaises(Unsupported): cgf_info(b'not a cgf')

    def test_surface_semantics_from_native_flags(self):
        self.assertEqual(blocks(SURFACES['mat_player_only']), ['player'])
        self.assertEqual(blocks(SURFACES['mat_horse_only']), ['horse'])
        self.assertEqual(blocks(SURFACES['mat_nodraw_designer']), ['player', 'horse', 'npc'])
        self.assertEqual(blocks(SURFACES['mat_mudwater']), [])
        self.assertIsNone(blocks(None))
        self.assertEqual(SURFACES['mat_level_barrier']['barrier']['monolog'], 'HRAC_NEMUZE_Z_MAPY')

    def test_mission_interactions_and_rotation(self):
        xml = b'''<Objects><Entity Name="gm_door_1" EntityClass="AnimDoor" EntityId="1" Pos="1,2,3" Rotate="0.70710678,0,0,0.70710678"/>
          <Entity Name="pot" EntityClass="KettleActionTrigger" EntityId="2" Pos="4,5,6"><Properties><Click fActiveDistance="1.7" UseMessage="@ui_eat_kettle"/></Properties></Entity>
          <Entity Name="l" EntityClass="Ladder" EntityId="3" Pos="0,0,0"><Properties height="2.75"/></Entity>
          <Entity Name="x" EntityClass="Light" EntityId="4" Pos="0,0,0"/></Objects>'''
        items, classes = interactions_from_mission(xml)
        self.assertEqual([i['kind'] for i in items], ['door', 'cooking', 'ladder'])
        self.assertEqual(classes['Light'], 1)
        door = items[0]['matrix']  # 90 degrees about z: local x -> world y
        self.assertAlmostEqual(door[4], 1.0); self.assertAlmostEqual(door[0], 0.0, places=6)
        self.assertEqual(items[1]['active_distance'], 1.7); self.assertEqual(items[2]['height'], 2.75)


class GeometryTests(unittest.TestCase):
    def test_penetration_and_signed_distance(self):
        a = [(0, 0), (2, 0), (2, 2), (0, 2)]; b = [(1.5, 0), (4, 0), (4, 2), (1.5, 2)]
        self.assertAlmostEqual(g.penetration(a, b), 0.5)
        self.assertEqual(g.penetration(a, [(3, 0), (4, 0), (4, 1), (3, 1)]), 0.0)
        self.assertAlmostEqual(g.signed_distance((1, 1), a), -1.0)
        self.assertAlmostEqual(g.signed_distance((3, 1), a), 1.0)
        self.assertAlmostEqual(g.polygon_distance(a, [(3, 0), (4, 0), (4, 1), (3, 1)]), 1.0)


class ClearanceTests(unittest.TestCase):
    def door(self, **kw):
        return dict(dict(name='gm_door_7', id='7', cls='AnimDoor', kind='door', pos=(50, 50, 0)), **kw)

    def findings(self, w, check):
        return next(c for c in audit(w)['checks'] if c['name'] == check)

    def test_box_straddling_a_door_passage_fails_and_coincident_blocker_is_flagged(self):
        c = self.findings(world([vol('b', 'mat_horse_only', at(50, 50), (-0.5, -0.1, 0), (0.5, 0.1, 2.5))], [self.door()]),
                          'interaction_clearance')
        self.assertEqual(c['status'], 'FAIL')
        f = c['findings'][0]
        self.assertTrue(f['origin_coincident']); self.assertEqual(f['blocks'], ['horse'])
        self.assertEqual((f['x'], f['y']), (50, 50))

    def test_shallow_overlap_is_inspect_and_far_box_is_clear(self):
        shallow = world([vol('b', 'mat_nodraw_designer', at(51.0, 50), (0, -1, 0), (2, 1, 3))], [self.door()])
        c = self.findings(shallow, 'interaction_clearance')
        self.assertEqual((c['status'], c['findings'][0]['severity']), ('REVIEW', 'inspect'))
        far = world([vol('b', 'mat_nodraw_designer', at(60, 50), (0, -1, 0), (2, 1, 3))], [self.door()])
        self.assertEqual(self.findings(far, 'interaction_clearance')['status'], 'PASS')

    def test_volume_above_or_below_body_band_is_ignored(self):
        high = world([vol('b', 'mat_nodraw_designer', at(50, 50, 5), (-1, -1, 0), (1, 1, 1))], [self.door()])
        self.assertEqual(self.findings(high, 'interaction_clearance')['findings'], [])

    def test_player_only_volume_enclosing_cooking_pot_is_a_defect(self):
        pot = dict(name='gm_cooking_1_2', id='2', cls='KettleActionTrigger', kind='cooking', pos=(20, 20, 1))
        c = self.findings(world([vol('p', 'mat_player_only', at(19, 19), (0, 0, 0), (2, 2, 2))], [pot]), 'interaction_clearance')
        f = c['findings'][0]
        self.assertEqual((f['severity'], f['use_point_enclosed'], f['blocks']), ('defect', True, ['player']))

    def test_ladder_is_checked_along_its_height(self):
        ladder = dict(name='l', id='3', cls='Ladder', kind='ladder', pos=(30, 30, 0), height=4.0)
        top = vol('t', 'mat_nodraw_designer', at(30, 30, 3.8), (-1, -1, 0), (1, 1, 0.5))
        self.assertEqual(len(self.findings(world([top], [ladder]), 'interaction_clearance')['findings']), 1)

    def test_ground_surface_proxy_is_not_an_obstacle_and_unknown_surface_is_unsupported(self):
        mud = world([vol('m', 'mat_mudwater', at(50, 50), (-1, -1, 0), (1, 1, 1))], [self.door()])
        self.assertEqual(self.findings(mud, 'interaction_clearance')['status'], 'PASS')
        unknown = world([vol('u', 'mat_not_native', at(80, 80), (0, 0, 0), (1, 1, 1))], [self.door()])
        self.assertEqual(self.findings(unknown, 'interaction_clearance')['status'], 'UNSUPPORTED')

    def test_duplicate_placements_fail(self):
        v = vol('a', 'mat_horse_only', at(5, 5), (0, 0, 0), (1, 1, 1))
        c = self.findings(world([v, dict(v, id='b')]), 'duplicate_volumes')
        self.assertEqual(c['status'], 'FAIL'); self.assertEqual(c['findings'][0]['volumes'], ['a', 'b'])
        self.assertEqual(self.findings(world([v, dict(v, id='b', matrix=at(5, 5.01))]), 'duplicate_volumes')['status'], 'PASS')


class BoundaryTests(unittest.TestCase):
    def boundary(self, volumes, **kw):
        w = world(volumes, **kw)
        return check_boundary(w, prepare(w), ASSUMPTIONS)

    def test_closed_ring_passes(self):
        findings, info = self.boundary(ring())
        self.assertEqual(findings, []); self.assertEqual((info['panels'], info['components']), (4, 1))

    def test_ring_with_a_missing_segment_reports_the_gap(self):
        findings, _ = self.boundary(ring(drop='n'))
        self.assertTrue(findings)
        self.assertTrue(all(f['category'] == 'boundary_gap' and f['severity'] == 'defect' for f in findings))
        self.assertTrue(any(f['y'] > 80 for f in findings))

    def test_narrow_gap_is_inspect_with_passability(self):
        findings, _ = self.boundary(ring(shrink=3.0))
        self.assertTrue(findings)
        f = findings[0]
        self.assertEqual(f['severity'], 'inspect'); self.assertAlmostEqual(f['gap_m'], 1.0, places=2)
        self.assertTrue(f['passable_player']); self.assertFalse(f['passable_horse'])

    def test_no_barrier_is_a_defect(self):
        findings, _ = self.boundary([])
        self.assertEqual(findings[0]['category'], 'boundary_missing')


class RoadTests(unittest.TestCase):
    def test_road_crossing_barrier_and_blocked_road(self):
        road = dict(id='r', center=[(50, 50, 0), (50, 95, 0), (50, 99.5, 0)], widths=[4, 4, 4])
        blocker = vol('x', 'mat_nodraw_designer', at(48, 60), (0, 0, 0), (4, 2, 3))
        report = audit(world(ring() + [blocker], roads=[road]))
        c = next(c for c in report['checks'] if c['name'] == 'road_crossings')
        cats = {f['category']: f for f in c['findings']}
        self.assertEqual(set(cats), {'road_crosses_barrier', 'road_blocked', 'road_reaches_map_edge'})
        self.assertEqual(cats['road_blocked']['severity'], 'defect')
        self.assertEqual(c['status'], 'FAIL')
        self.assertTrue(c['sites'])

    def test_missing_roads_are_unsupported(self):
        c = next(c for c in audit(world(ring()))['checks'] if c['name'] == 'road_crossings')
        self.assertEqual(c['status'], 'UNSUPPORTED')


class RunnerTests(unittest.TestCase):
    def scenario(self, assertions, **kw):
        return dict(name='s', world=dict(surfaces=SURFACES, extent=(0, 0, 100, 100), volumes=ring(),
                                         interactions=[], roads=[]), assertions=assertions, **kw)

    def test_assertions_pass_and_unasserted_unsupported_check_is_not_counted_for_inline_worlds(self):
        r = run_scenario(self.scenario([{'check': 'boundary_closure', 'status': 'PASS'},
                                        {'category': 'boundary_gap', 'count': {'max': 0}}]))
        self.assertEqual(r['status'], 'PASS')

    def test_asserting_an_unsupported_check_never_passes(self):
        r = run_scenario(self.scenario([{'check': 'road_crossings', 'status': 'UNSUPPORTED'}]))
        self.assertEqual(r['status'], 'UNSUPPORTED')
        r = run_scenario(self.scenario([{'check': 'boundary_closure', 'status': 'PASS'}], all_checks=True))
        self.assertEqual(r['status'], 'UNSUPPORTED')

    def test_failed_assertion_and_no_assertions(self):
        self.assertEqual(run_scenario(self.scenario([{'category': 'boundary_gap', 'expect': 'present'}]))['status'], 'FAIL')
        self.assertEqual(run_scenario(self.scenario([]))['status'], 'UNSUPPORTED')

    def test_cli_run_writes_reports_and_nonzero_exit(self):
        with tempfile.TemporaryDirectory() as d:
            ok = Path(d, 'ok.json'); bad = Path(d, 'bad.json')
            ok.write_text(json.dumps(self.scenario([{'check': 'boundary_closure', 'status': 'PASS'}])))
            bad.write_text(json.dumps(self.scenario([{'check': 'road_crossings', 'status': 'PASS'}])))
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(main(['run', str(ok), '--output', str(Path(d, 'out'))]), 0)
                self.assertEqual(main(['run', str(ok), str(bad), '--output', str(Path(d, 'out2'))]), 1)
            suite = E.parse(Path(d, 'out2', 'junit.xml')).getroot()
            self.assertEqual(suite.get('tests'), '2')
            self.assertTrue(Path(d, 'out2', 'scenario-00.html').exists())
            results = json.loads(Path(d, 'out2', 'results.json').read_text())
            self.assertFalse(results['native_runtime_verified'])


if __name__ == '__main__':
    unittest.main()
