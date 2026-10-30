import json
import math
from pathlib import Path
import struct
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'tools'))
import loft_navigation as L
from static_navigation_profiles import AUTHORED_LAYER_TAG, BASE, decode, encode, native_layers
from region_travel_navigation import validate_mesh

SETTINGS = bytes(range(56))
GUID = 'c9ef1513-ef3d-d45f'
MISSION = ('<Objects>'
           '<Entity Name="gm_forge_loft_ladder" EntityClass="Ladder" EntityGuid="%s" Pos="737.6,3415.8,63.9089" '
           'Rotate="0,0,0.0697564737,0.99756405"><Properties height="3.25" bUsable="true"/></Entity>'
           '<Entity Name="gm_forge_loft_mother_bed" EntityClass="StanceSmartObject" EntityGuid="e9b1e602-be23-3d5a" '
           'Pos="734.8011561077022,3422.7969556854723,67.315" Rotate="0.700909264,0,0,0.713250449"/>'
           '<Entity Name="gm_forge_loft_father_bed" EntityClass="StanceSmartObject" EntityGuid="20fe68fe-3d4f-cb5a" '
           'Pos="737.1507981913197,3422.8379688406,67.315" Rotate="0.700909264,0,0,0.713250449"/>'
           '</Objects>' % GUID).encode()


def native_tile(cell, layer, verts, neis, z=63.92):
    """A native-looking tile (userId 0) with one clockwise polygon."""
    blob = bytearray(L.pack_tile(cell, layer, [dict(name='n', z=z, verts=verts, neis=neis)], [], (63.84, 64.08)))
    struct.pack_into('<I', blob, 20, 0)
    return bytes(blob)


def base_cells(portal=True):
    west = native_tile((45, 213), 0, ((734.0, 3412.5), (734.0, 3415.2), (736.0, 3415.2), (736.0, 3412.5)),
                       [0, 0, L.PORTAL | 0 if portal else 0, 0])
    east = native_tile((46, 213), 0, ((740.0, 3410.0), (740.0, 3412.0), (742.0, 3412.0), (742.0, 3410.0)), [0, 0, 0, 0])
    upper = native_tile((46, 213), 1, ((744.0, 3410.0), (744.0, 3412.0), (746.0, 3412.0), (746.0, 3410.0)), [0, 0, 0, 0])
    far = native_tile((10, 10), 0, ((160.0, 160.0), (160.0, 162.0), (162.0, 162.0), (162.0, 160.0)), [0, 0, 0, 0])
    return {(10, 10): (far,), (45, 213): (west,), (46, 213): (upper, east)}


def fixture(portal=True):
    header, mesh = encode(base_cells(portal), SETTINGS)
    files = {BASE + '.hdr': header, BASE + '.nav': mesh}
    native = SETTINGS + struct.pack('<I', 1) + base_cells()[(10, 10)][0]
    return files, native


def probe_parse(t):
    """Transcription of navmesh_probe.parse_tile (diag/navmesh-forge-loft-20261029)."""
    h = struct.unpack_from('<4I I I 11I 4f 3f 3f f', t, 0)
    assert h[0] == 0x444e4156 and h[1] == 14
    ints = h[6:17]; P, V, om = ints[0], ints[1], ints[9]
    bmin, bmax = h[21:24], h[24:27]
    assert len(t) == 112 + 4 * V + 28 * P + 68 * om, (len(t), P, V, om)
    o = 112; verts = []; zr = bmax[2] - bmin[2]
    for i in range(V - 2 * om):
        u = struct.unpack_from('<I', t, o)[0]; o += 4
        Z, Y, X = u & 0x3ff, (u >> 10) & 0x7ff, u >> 21
        verts.append((bmin[0] + X * 16 / 2047, bmin[1] + Y * 16 / 2047, bmin[2] + Z * zr / 1023))
    for k in range(om):
        f = struct.unpack_from('<6f', t, o); o += 24
        verts.append(f[:3]); verts.append(f[3:])
    polys = []
    for i in range(P):
        vs = struct.unpack_from('<6H', t, o); ns = struct.unpack_from('<6H', t, o + 12)
        area, nv, flags = struct.unpack_from('<BBH', t, o + 24); o += 28
        polys.append(dict(verts=vs[:nv], neis=ns[:nv], area=area, nv=nv, flags=flags))
    cons = []
    for k in range(om):
        r = struct.unpack_from('<6f f H B B I 8s I I', t, o)
        entity, category = struct.unpack_from('<QI', t, o + 32); o += 52
        cons.append(dict(pos=r[:6], rad=r[6], poly=r[7], flags=r[8], side=r[9], entity=entity, category=category,
                         id=r[12], last=r[13]))
    assert o == len(t)
    return dict(x=h[2], y=h[3], layer=h[4], user=h[5], bmin=bmin, bmax=bmax, verts=verts, polys=polys, cons=cons, ints=ints)


def rotate(q, v):
    w, x, y, z = q
    tx, ty, tz = 2 * (y * v[2] - z * v[1]), 2 * (z * v[0] - x * v[2]), 2 * (x * v[1] - y * v[0])
    return (v[0] + w * tx + (y * tz - z * ty), v[1] + w * ty + (z * tx - x * tz), v[2] + w * tz + (x * ty - y * tx))


class LoftNavigationTests(unittest.TestCase):
    def convert(self, **kwargs):
        files, native = fixture()
        return L.convert(files, MISSION, native, **kwargs)

    def test_authored_layers_round_trip_through_the_probe_decoder(self):
        updated, report = self.convert()
        cells = decode(updated[BASE + '.hdr'], updated[BASE + '.nav'], SETTINGS, 14)
        self.assertEqual({c: len(t) for c, t in cells.items()}, {(10, 10): 1, (45, 213): 2, (46, 213): 3})
        self.assertEqual(validate_mesh(updated[BASE + '.hdr'], updated[BASE + '.nav'], SETTINGS, 14), 6)
        design = {p['name']: p for p in L.polygons()}
        seen = {}
        for cell, layer in (((45, 213), 1), ((46, 213), 2)):
            tile = probe_parse(cells[cell][-1])
            self.assertEqual((tile['x'], tile['y'], tile['layer'], tile['user']), (*cell, layer, AUTHORED_LAYER_TAG))
            P, V, om = tile['ints'][0], tile['ints'][1], tile['ints'][9]
            self.assertEqual(tile['ints'][2], V - 2 * om)            # packed vertex count
            self.assertEqual(tile['ints'][5:9], (0, 0, 0, 0))
            self.assertEqual(tile['ints'][10], P - om)               # offMeshBase
            self.assertEqual(tile['ints'][4], 3)
            names = [p['name'] for p in L.polygons() if p['cell'] == cell]
            internal = 0
            for name, poly in zip(names, tile['polys'][:P - om]):
                points = [tile['verts'][v] for v in poly['verts']]
                self.assertLess(L.shoelace([p[:2] for p in points]), 0, name)   # clockwise like native tiles
                self.assertLessEqual(max(math.hypot(p[0] - d[0], p[1] - d[1]) for p, d in zip(points, design[name]['verts'])), .006)
                self.assertLessEqual(max(abs(p[2] - design[name]['z']) for p in points), .005)
                self.assertEqual((poly['area'], poly['flags']), (1, 0x100))
                for k, nei in enumerate(poly['neis']):
                    a, b = poly['verts'][k], poly['verts'][(k + 1) % poly['nv']]
                    if nei & 0x8000:
                        axis = 0 if nei & 0xff in (0, 4) else 1
                        border = tile['bmax'][axis] if nei & 0xff in (0, 2) else tile['bmin'][axis]
                        self.assertAlmostEqual(tile['verts'][a][axis], border, places=6)
                        self.assertAlmostEqual(tile['verts'][b][axis], border, places=6)
                    elif nei:
                        other = tile['polys'][nei - 1]
                        pairs = [(other['verts'][m], other['verts'][(m + 1) % other['nv']]) for m in range(other['nv'])]
                        self.assertIn((b, a), pairs, name)
                        internal += 1
                seen[name] = points
            self.assertEqual(tile['ints'][3], internal + 2)
            for k, poly in enumerate(tile['polys'][P - om:]):
                self.assertEqual((poly['nv'], poly['area'], poly['flags'], tuple(poly['neis'])), (2, 0x21, 0x101, (0, 0)))
                self.assertEqual(poly['verts'], (V - 2 * om + 2 * k, V - 2 * om + 2 * k + 1))
        self.assertEqual(set(seen), set(design))
        ladder = probe_parse(cells[46, 213][-1])['cons']
        self.assertEqual(len(ladder), 1)
        con = ladder[0]
        self.assertEqual((con['rad'], con['flags'], con['side'], con['category'], con['id'], con['last']),
                         (.5, 1, 255, 3, 0x7fffffff, 0xffff0001))
        self.assertEqual(con['entity'], 0xc9ef1513 | 0xef3d << 32 | 0xd45f << 48)
        self.assertEqual(con['poly'], len([p for p in design.values() if p['cell'] == (46, 213)]))
        q, origin = (0, 0, 0.0697564737, 0.99756405), (737.6, 3415.8, 63.9089)
        foot = rotate(q, (-.038, .518, -.139)); top = rotate(q, (.023, -.425, 3.25))
        expected = [origin[i] + foot[i] for i in range(3)] + [origin[i] + top[i] for i in range(3)]
        for actual, value in zip(con['pos'], expected):
            self.assertAlmostEqual(actual, value, delta=5e-4)   # f32 spacing at these coordinates
        self.assertLess(con['pos'][2], con['pos'][5])                         # start is the foot, like native ladders
        self.assertTrue(L.inside(con['pos'][:2], [p[:2] for p in seen['foot_east']]))
        self.assertTrue(L.inside(con['pos'][3:5], [p[:2] for p in seen['loft_hatch']]))
        self.assertEqual(report['ladder']['support']['foot']['polygon'], 'foot_east')
        self.assertEqual(report['ladder']['support']['top']['polygon'], 'loft_hatch')

    def test_native_tiles_and_order_are_preserved(self):
        files, native = fixture()
        before = decode(files[BASE + '.hdr'], files[BASE + '.nav'], SETTINGS, 14)
        updated, report = L.convert(files, MISSION, native)
        after = decode(updated[BASE + '.hdr'], updated[BASE + '.nav'], SETTINGS, 14)
        self.assertEqual(list(after), list(before))
        for cell, tiles in before.items():
            self.assertEqual(after[cell][:len(tiles)], tiles)
            self.assertEqual(native_layers(after[cell]), tiles)
        self.assertEqual(struct.unpack_from('<I', updated[BASE + '.nav'], 56)[0], 6)
        self.assertEqual(updated[BASE + '.nav'][:56], SETTINGS)
        self.assertTrue(report['native_tiles_preserved'])
        self.assertEqual((report['base_tiles'], report['tiles_after']), (4, 6))
        self.assertFalse(report['runtime_verified'])
        marker = json.loads(updated[L.MARKER])
        self.assertEqual(marker['version'], L.VERSION)
        self.assertEqual(marker['layers'], {'(45, 213)': 1, '(46, 213)': 2})

    def test_repeat_conversion_is_byte_identical(self):
        files, native = fixture()
        once, first = L.convert(files, MISSION, native)
        twice, second = L.convert(once, MISSION, native)
        self.assertEqual(twice, once)
        self.assertEqual((first['previously_authored_layers'], second['previously_authored_layers']), (0, 2))
        first.pop('previously_authored_layers'); second.pop('previously_authored_layers')
        self.assertEqual(first, second)

    def test_poses_and_portals_are_evidenced(self):
        _, report = self.convert()
        for role, expected in (('mother', 'loft_west'), ('father', 'loft_landing')):
            placed = [p['polygon'] for p in report['poses'][role]]
            self.assertEqual(placed, [None, expected], role)   # the wall side is off the mesh, the room side on it
            self.assertGreaterEqual(report['poses'][role][1]['clearance'], .025)
        partners = {(p['polygon'], p['origin']) for p in report['portals']}
        self.assertEqual(partners, {('loft_west', 'authored'), ('loft_border', 'authored'), ('foot_west', 'native')})
        self.assertEqual(report['ladder']['entity'], GUID)

    def test_missing_ground_portal_partner_is_rejected(self):
        files, native = fixture(portal=False)
        with self.assertRaisesRegex(ValueError, 'no partner'):
            L.convert(files, MISSION, native)

    def test_furniture_clearance_and_ladder_placement_are_enforced(self):
        intruding = ('loft_border', L.FLOOR_Z, ((736.00, 3417.15), (736.00, 3422.60), (737.00, 3422.60), (737.00, 3417.15)))
        with patch.object(L, 'LOFT', (L.LOFT[0], intruding) + L.LOFT[2:]):
            with self.assertRaisesRegex(ValueError, 'furniture clearance'):
                self.convert()
        moved = MISSION.replace(b'Pos="737.6,3415.8,63.9089"', b'Pos="741.0,3415.8,63.9089"')
        files, native = fixture()
        with self.assertRaisesRegex(ValueError, 'Ladder foot'):
            L.convert(files, moved, native)

    def test_brushes_under_the_patch_are_rejected(self):
        # The measured 0.6 m object beside the ladder foot, the house shell (too large to count) and a flat mat.
        clear = [(735.27, 3415.51, 63.89, 736.89, 3416.18, 64.49), (700.0, 3400.0, 60.0, 760.0, 3440.0, 70.0),
                 (737.0, 3414.5, 63.92, 738.0, 3415.5, 63.95)]
        _, report = self.convert(brushes=clear)
        self.assertEqual(report['brushes'], dict(checked=1, margin=.3))
        with self.assertRaisesRegex(ValueError, 'overlaps a brush'):
            self.convert(brushes=clear + [(737.5, 3415.0, 63.9, 737.9, 3415.4, 64.6)])

    def test_reference_decoder_rejects_malformed_tiles(self):
        updated, _ = self.convert()
        cells = decode(updated[BASE + '.hdr'], updated[BASE + '.nav'], SETTINGS, 14)
        tile = bytearray(cells[46, 213][-1])
        struct.pack_into('<I', tile, 64, 0)
        with self.assertRaisesRegex(ValueError, 'inconsistent'):
            L.decode_tile(bytes(tile))
        with self.assertRaisesRegex(ValueError, 'size law'):
            L.decode_tile(bytes(cells[46, 213][-1]) + b'\0')


if __name__ == '__main__':
    unittest.main()
