from pathlib import Path
import json
import struct
import sys
import tempfile
import unittest
import xml.etree.ElementTree as E
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'tools'))
import audit_bed_navigation as A

HELPERS = b'''<SmartObjectHelperSetAnimations>
 <Collection HelperSetName="Bed_1Place_High">
  <SmartObjectHelperSetAnimationCollection HashValue="1"><AnimationsMap><Pair Key="1"><Value>
   <SmartObjectHelperSetAnimation HelperId="0" Checks="1,1" CheckMNMTolerance="MNMToleranceDefault" DebugFragmentName="LieDown" DebugFragTagState="liePlaceBed+lieSideLeft">
    <HelperTransformLocal Rotation="1,0,0,0" Position="0,0,0" /><StartTransform Rotation="0.707,0,0,0.707" Position="0,0.867,0.02" />
   </SmartObjectHelperSetAnimation>
   <SmartObjectHelperSetAnimation HelperId="0" Checks="1,1" CheckMNMTolerance="MNMToleranceDefault" DebugFragmentName="LieDown" DebugFragTagState="liePlaceBed+lieSideRight">
    <HelperTransformLocal Rotation="1,0,0,0" Position="0,0,0" /><StartTransform Rotation="0.707,0,0,0.707" Position="0,0.867,0.02" />
   </SmartObjectHelperSetAnimation>
   <SmartObjectHelperSetAnimation HelperId="0" Checks="0,1" CheckMNMTolerance="MNMToleranceDefault" DebugFragmentName="LieDown" DebugFragTagState="sittingNoTable+lieSideLeft">
    <HelperTransformLocal Rotation="1,0,0,0" Position="0,0,0" /><StartTransform Rotation="1,0,0,0" Position="0,-0.46,0" />
   </SmartObjectHelperSetAnimation>
   <SmartObjectHelperSetAnimation HelperId="0" Checks="1,1" CheckMNMTolerance="MNMToleranceDefault" DebugFragmentName="GetUp" DebugFragTagState="lying">
    <HelperTransformLocal Rotation="1,0,0,0" Position="0,0,0" /><StartTransform Rotation="1,0,0,0" Position="0,0,0" />
   </SmartObjectHelperSetAnimation>
  </Value></Pair></AnimationsMap></SmartObjectHelperSetAnimationCollection>
 </Collection>
 <Collection HelperSetName="Bed_1Place_Tent">
  <SmartObjectHelperSetAnimationCollection HashValue="2"><AnimationsMap><Pair Key="1"><Value>
   <SmartObjectHelperSetAnimation HelperId="0" Checks="1,1" CheckMNMTolerance="MNMToleranceDefault" DebugFragmentName="LieDown" DebugFragTagState="liePlaceShelter">
    <HelperTransformLocal Rotation="1,0,0,0" Position="0,0,0" /><StartTransform Rotation="1,0,0,0" Position="-0.26,0.84,-0.02" />
   </SmartObjectHelperSetAnimation>
  </Value></Pair></AnimationsMap></SmartObjectHelperSetAnimationCollection>
 </Collection>
</SmartObjectHelperSetAnimations>'''
QUARTER = '0.70710678,0,0,0.70710678'  # +90 degrees about z: local +y becomes world -x
ZRANGE = (8.0, 16.0)


def square(x0, y0, x1, y1, z):
    return [(x0, y1, z), (x1, y1, z), (x1, y0, z), (x0, y0, z)]  # clockwise like native polygons


def pack_tile(cell, polys, zrange=ZRANGE, layer=0):
    verts, records = [], []
    for pts in polys:
        idx = []
        for x, y, z in pts:
            X = round((x - cell[0] * 16) / 16 * 2047); Y = round((y - cell[1] * 16) / 16 * 2047)
            Z = round((z - zrange[0]) / (zrange[1] - zrange[0]) * 1023) if zrange[1] > zrange[0] else 0
            idx.append(len(verts)); verts.append(X << 21 | Y << 10 | Z)
        records.append(idx)
    P, V = len(records), len(verts)
    blob = struct.pack('<17I', A.MAGIC, A.TILE_VERSION, cell[0], cell[1], layer, 0, P, V, V, 2 * P, 3, 0, 0, 0, 0, 0, P)
    blob += struct.pack('<11f', 1.76, .32, .32, .8, cell[0] * 16, cell[1] * 16, zrange[0], cell[0] * 16 + 16, cell[1] * 16 + 16, zrange[1], 12.5)
    blob += b''.join(struct.pack('<I', v) for v in verts)
    for idx in records:
        blob += struct.pack('<6H6HBBH', *(idx + [0] * (6 - len(idx))), *([0] * 6), 1, len(idx), 0x100)
    return blob


def bed(name, eid, pos, rot='1,0,0,0', family='Bed_1Place_High', links=()):
    e = E.Element('Entity', Name=name, EntityClass='StanceSmartObject', EntityId=str(eid), EntityGuid='%x' % (0x1000 + eid), Pos=pos, Rotate=rot)
    container = E.SubElement(e, 'EntityLinks')
    for link, target in links:
        E.SubElement(container, 'Link', Name=link, TargetId=str(target), TargetGuid='0')
    props = E.SubElement(e, 'Properties', soclass_SmartObjectHelpers=family, sWH_AI_EntityCategory='Bed')
    E.SubElement(props, 'Bed', esSleepQuality='medium')
    return e


def hub(name, eid, bed_id):
    e = E.Element('Entity', Name=name, EntityClass='SchedulerHub', EntityId=str(eid), EntityGuid='%x' % (0x1000 + eid), Pos='0,0,0')
    E.SubElement(E.SubElement(e, 'EntityLinks'), 'Link', Name='_,use', TargetId=str(bed_id), TargetGuid='0')
    return e


def write_level(folder, entities, tiles):
    folder.mkdir(parents=True, exist_ok=True)
    root = E.Element('Objects')
    for entity in entities:
        root.append(entity)
    with zipfile.ZipFile(folder / 'level.pak', 'w') as z:
        z.writestr('objects_mission0.xml', E.tostring(root)); z.writestr('smartobjecthelpersetanimations.xml', HELPERS)
    by_cell = {}
    for cell, blob in tiles:
        by_cell.setdefault(cell, []).append(blob)
    hdr, nav = b'', bytearray(b'\0' * 60)
    for cell, blobs in by_cell.items():
        hdr += struct.pack('<4I', cell[0], cell[1], len(nav), len(blobs)) + struct.pack('<%dI' % len(blobs), *[len(b) for b in blobs])
        for blob in blobs:
            nav += blob
    with zipfile.ZipFile(folder / 'recast.pak', 'w') as z:
        z.writestr(A.BASE + '.hdr', hdr); z.writestr(A.BASE + '.nav', bytes(nav))


class BedNavigationAuditTests(unittest.TestCase):
    def test_lie_poses_read_liedown_entries_only(self):
        poses = A.lie_poses(E.fromstring(HELPERS))
        high = poses['Bed_1Place_High']
        self.assertEqual([p['local'] for p in high], [(0.0, 0.867, 0.02), (0.0, -0.46, 0.0)])  # left/right share one pose
        self.assertEqual([('liePlace' in p['tags'], p['checks']) for p in high], [(True, '1,1'), (False, '0,1')])
        self.assertEqual(poses['Bed_1Place_Tent'][0]['local'], (-0.26, 0.84, -0.02))

    def test_parse_tile_roundtrip_size_law_and_flat_bounds(self):
        blob = pack_tile((43, 212), [square(697.0, 3398.0, 698.633, 3402.0, 10.0)])
        self.assertEqual(len(blob), 112 + 4 * 4 + 28 * 1)
        tile = A.parse_tile(blob)
        self.assertEqual((tile['cell'], tile['layer'], len(tile['polys']), tile['links']), ((43, 212), 0, 1, []))
        for got, want in zip(tile['verts'], square(697.0, 3398.0, 698.633, 3402.0, 10.0)):
            self.assertLess(max(abs(a - b) for a, b in zip(got, want)), 0.01)
        flat = A.parse_tile(pack_tile((1, 1), [], zrange=(5.0, 5.0)))
        self.assertEqual((flat['polys'], flat['bmin'][2]), ([], 5.0))
        with self.assertRaisesRegex(ValueError, 'size law'):
            A.parse_tile(blob + b'\0')
        with self.assertRaisesRegex(ValueError, 'format'):
            A.parse_tile(b'\0' * len(blob))

    def test_measure_transforms_the_pose_and_finds_the_nearest_polygon(self):
        with tempfile.TemporaryDirectory() as tmp:
            level = Path(tmp) / 'lvl'
            entities = [bed('gm_world_bed_1_bed', 1, '700,3400,10', QUARTER, links=[('preferedSleeper', 5)]),
                        bed('gm_world_bed_2_bed', 2, '720,3400,10', QUARTER), bed('gm_world_bed_3_bed', 3, '100,100,10'),
                        hub('gm_sleep_a', 11, 1), hub('gm_sleep_b', 12, 2), hub('gm_sleep_c', 13, 3),
                        E.Element('Entity', Name='villager', EntityClass='NPC', EntityId='5', EntityGuid='5', Pos='0,0,0')]
            # The pose of bed 1 is 0.867 m west of its centre (699.133, 3400); the polygon's east edge is 0.5 m further west.
            tiles = [((43, 212), pack_tile((43, 212), [square(697.0, 3398.0, 698.633, 3402.0, 10.0)]))]
            write_level(level, entities, tiles)
            records = A.measure(level, scheduled_only=True)
            self.assertEqual([r['name'] for r in records], ['gm_world_bed_1_bed', 'gm_world_bed_2_bed', 'gm_world_bed_3_bed'])
            first, far, away = records
            self.assertEqual((first['sleepers'], first['preferred'], first['town']), (['gm_sleep_a'], ['villager'], 'skalitz'))
            self.assertEqual([p['world'] for p in first['poses']], [[699.133, 3400.0, 10.02], [700.46, 3400.0, 10.0]])
            self.assertAlmostEqual(first['best']['horizontal'], 0.5, delta=0.01)  # vertices are quantized to 16/2047 m
            self.assertEqual((first['best']['cell'], first['best']['poly']), ([43, 212], 0))
            self.assertLess(abs(first['best']['dz'] + 0.02), 0.01)
            self.assertTrue(first['has_pose'])
            self.assertIsNone(far['best'])  # no polygon within 2 m
            self.assertEqual(away['town'], 'elsewhere')
            self.assertEqual([r['name'] for r in A.measure(level, scheduled_only=True, town='skalitz')], ['gm_world_bed_1_bed', 'gm_world_bed_2_bed'])
            self.assertEqual(len(A.measure(level, scheduled_only=False)), 3)

    def test_envelope_and_classification(self):
        def record(family, horizontal, dz=0.03, has_pose=True):
            best = None if horizontal is None else dict(horizontal=horizontal, dz=dz)
            return dict(family=family, has_pose=has_pose, best=best)
        native = A.envelope([record('Bed_1Place_High', h) for h in (0.70, 0.75, 0.78, 0.80, 0.81, 0.82, 0.83, 0.84, 0.85, 0.86, 0.90)]
                            + [record('Bed_1Place_High', None), record('Weird', 0.1, has_pose=False)])
        self.assertEqual(native['Bed_1Place_High'], dict(n=12, without_surface=1, h_p90=0.86, h_max=0.9, dz_p90=0.03, dz_max=0.03))
        self.assertNotIn('Weird', native)
        self.assertEqual(A.classify(record('Bed_1Place_High', 0.82), native), 'ok')
        self.assertEqual(A.classify(record('Bed_1Place_High', 0.88), native), 'marginal')
        self.assertEqual(A.classify(record('Bed_1Place_High', 0.92), native), 'marginal')  # within the 3 cm slack
        self.assertEqual(A.classify(record('Bed_1Place_High', 0.82, dz=0.5), native), 'outlier')
        self.assertEqual(A.classify(record('Bed_1Place_High', 0.95), native), 'outlier')
        self.assertEqual(A.classify(record('Bed_1Place_High', None), native), 'outlier')
        self.assertEqual(A.classify(record('Bed_1Place_Tent', 0.1), native), 'no_native_family')
        self.assertEqual(A.classify(record('Weird', None, has_pose=False), native), 'no_helper_set')

    def test_audit_calibrates_on_the_native_level_and_writes_reports(self):
        with tempfile.TemporaryDirectory() as tmp:
            target, package = Path(tmp) / 'kcd2', Path(tmp) / 'mod'
            # Native beds (no schedule links) with their poses 0.3, 0.8 and 0.9 m from a polygon edge.
            native_entities, native_tiles = [], []
            for i, gap in enumerate((0.3, 0.8, 0.9)):
                y = 100.0 + 4 * i
                native_entities.append(bed('bed_%d' % i, 20 + i, '100,%s,10' % y))
                native_tiles.append(((6, 6), pack_tile((6, 6), [square(100.0 + gap, y, 101.0 + gap, y + 2.0, 10.0)])))
            write_level(target / A.NATIVE, native_entities, native_tiles)
            entities = [bed('gm_world_bed_1_bed', 1, '700,3400,10', QUARTER), hub('gm_sleep_a', 11, 1),
                        bed('gm_world_bed_2_bed', 2, '720,3400,10', QUARTER), hub('gm_sleep_b', 12, 2),
                        bed('gm_world_bed_9_bed', 9, '740,3400,10', QUARTER)]
            tiles = [((43, 212), pack_tile((43, 212), [square(697.0, 3398.0, 698.633, 3402.0, 10.0)]))]
            write_level(package / A.CONVERTED, entities, tiles)
            out = Path(tmp) / 'out'
            report = A.audit(package, target, out, town='skalitz')
            high = report['native_envelope']['Bed_1Place_High']
            self.assertEqual((high['n'], high['without_surface']), (3, 0))
            for key, want in (('h_p90', 0.9), ('h_max', 0.9), ('dz_p90', 0.02), ('dz_max', 0.02)):
                self.assertAlmostEqual(high[key], want, delta=0.01, msg=key)
            self.assertEqual((report['beds'], report['by_status']), (2, {'ok': 1, 'outlier': 1}))
            self.assertEqual(report['by_family_status'], {'Bed_1Place_High/ok': 1, 'Bed_1Place_High/outlier': 1})
            self.assertEqual([(f['name'], f['status'], f['best']) for f in report['flagged']], [('gm_world_bed_2_bed', 'outlier', None)])
            self.assertFalse(report['runtime_verified'])
            lines = [json.loads(l) for l in (out / 'beds.jsonl').read_text(encoding='utf-8').splitlines()]
            self.assertEqual([(l['name'], l['status']) for l in lines], [('gm_world_bed_1_bed', 'ok'), ('gm_world_bed_2_bed', 'outlier')])
            self.assertEqual(json.loads((out / 'report.json').read_text(encoding='utf-8'))['by_status'], {'ok': 1, 'outlier': 1})


if __name__ == '__main__': unittest.main()
