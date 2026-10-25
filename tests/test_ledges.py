from pathlib import Path
import json
import sys
import tempfile
import unittest
from unittest.mock import patch
import xml.etree.ElementTree as E
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'tools'))
from ledges import convert, PREFIX
from region_travel import guid
from test_cooking_pots import archive


def ledge(entity, start, count, flags='559'):
    return (f'<Ledge><entityId>{entity}</entityId><markersStartIdx>{start}</markersStartIdx><markersCount>{count}</markersCount>'
            f'<ledgeCornerEndAdjustAmount>0.5</ledgeCornerEndAdjustAmount><Flags0>{flags}</Flags0><Flags1>{flags}</Flags1></Ledge>')


def marker(x, end='1'):
    return (f'<Marker><worldPosition>{x},3400.5,26.25</worldPosition><facingDirection>0,-1,0</facingDirection>'
            f'<endOrCorner>{end}</endOrCorner></Marker>')


def whdata(ledges, markers, root='<Root>', extra=''):
    return (root+'<LedgeManager><Ledges>'+''.join(ledges)+'</Ledges><Markers>'+''.join(markers)+
            '</Markers></LedgeManager>'+extra+'</Root>').encode()


PROPS = '<Properties bIsThin="1" bLedgeDoubleSide="1"><MainSide esLedgeType="Vault"/></Properties>'
SOURCE = {'objects_mission0.xml': f'''<Objects>
<Entity EntityId="9" Pos="100,200,0"/>
<Entity Name="Ledge1" EntityClass="LedgeObject" EntityId="11" ParentId="9" Pos="1,2,3">{PROPS}</Entity>
<Entity Name="Ledge2" EntityClass="LedgeObject" EntityId="12" Layer="army_camp_state1{{x}}" Pos="0,0,0">{PROPS}</Entity>
<Entity Name="Ledge3" EntityClass="LedgeObject" EntityId="13" Pos="0,0,0">{PROPS}</Entity>
<Entity Name="Brush" EntityClass="GeomEntity" EntityId="14"/></Objects>'''.encode(),
    'whdata_1': whdata([ledge(0, 0, 2), ledge(12, 2, 2), ledge(11, 4, 3, '551'), ledge(77, 7, 2), ledge(14, 9, 2)],
                       [marker(800+i, str(i % 2)) for i in range(11)], extra='<GameProfileManager><GameProfiles/></GameProfileManager>')}
NATIVE = {'whdata_1': whdata([ledge(0, 0, 2)], [marker(1), marker(2)], '<Root version="1">', '<GameProfileManager/>')}
MISSION = b'<Objects><Entity Name="glue_item_1" EntityId="40"/><Entity Name="x" EntityId="41"/></Objects>'


class LedgeTests(unittest.TestCase):
    def build(self, files=None, source=SOURCE, native=NATIVE):
        with archive(source) as src, archive(native) as nat:
            return convert(files or {'objects_mission0.xml': MISSION}, src, nat, guid)

    def test_static_and_active_entity_ledges_keep_geometry_and_remap_ids(self):
        files, r = self.build()
        root = E.fromstring(files['objects_mission0.xml'])
        node = root.find(f"Entity[@Name='{PREFIX}11']")
        self.assertEqual((node.get('EntityClass'), node.get('EntityId'), node.get('Pos')), ('LedgeObject', '42', '101,202,3'))
        self.assertEqual(node.get('EntityGuid'), guid('ledge/11'))
        self.assertEqual(node.find('Properties').get('bIsThin'), '1')
        self.assertEqual(node.find('Properties/MainSide').get('esLedgeType'), 'Vault')
        self.assertIsNone(root.find(f"Entity[@Name='{PREFIX}12']"))
        self.assertIsNone(root.find(f"Entity[@Name='{PREFIX}13']"))  # no ledge references it
        meta = E.fromstring(files['whdata_1'])
        self.assertEqual((meta.tag, meta.attrib, [c.tag for c in meta]), ('Root', {'version': '1'}, ['LedgeManager']))
        rows = [{c.tag: c.text for c in l} for l in meta.iter('Ledge')]
        self.assertEqual([(l['entityId'], l['markersStartIdx'], l['markersCount'], l['Flags0']) for l in rows],
                         [('0', '0', '2', '559'), ('42', '2', '3', '551')])
        xs = [m.findtext('worldPosition') for m in meta.iter('Marker')]
        self.assertEqual(xs, [f'{800+i},3400.5,26.25' for i in (0, 1, 4, 5, 6)])
        self.assertEqual([m.findtext('endOrCorner') for m in meta.iter('Marker')], ['0', '1', '0', '1', '0'])
        self.assertEqual(r['skipped'], {'inactive_layer': 1, 'missing_entity': 1, 'non_ledge_entity': 1})
        self.assertEqual(r['skipped_layers'], {'army_camp_state1{x}': 1})
        self.assertEqual((r['ledges'], r['static_ledges'], r['entities'], r['markers']), (2, 1, 1, 5))
        self.assertEqual(r['unreferenced_entities'], ['13'])
        self.assertFalse(r['runtime_verified'])

    def test_deterministic_and_repeat_is_rejected(self):
        first, _ = self.build()
        self.assertEqual(first, self.build()[0])
        with self.assertRaisesRegex(ValueError, 'already converted'):
            self.build(first)
        mission = first['objects_mission0.xml'].replace(PREFIX.encode(), b'other_')
        with self.assertRaisesRegex(ValueError, 'already converted'):
            self.build(dict(first, **{'objects_mission0.xml': mission}))

    def test_existing_game_profiles_are_kept_after_ledges(self):
        profiles = b'<Root version="1"><GameProfileManager><GameProfiles><GameProfile><Name>p</Name></GameProfile></GameProfiles></GameProfileManager></Root>'
        files, _ = self.build({'objects_mission0.xml': MISSION, 'whdata_1': profiles})
        meta = E.fromstring(files['whdata_1'])
        self.assertEqual([c.tag for c in meta], ['LedgeManager', 'GameProfileManager'])
        self.assertEqual(meta.findtext('GameProfileManager/GameProfiles/GameProfile/Name'), 'p')
        with self.assertRaisesRegex(ValueError, 'destination whdata_1 root'):
            self.build({'objects_mission0.xml': MISSION, 'whdata_1': b'<Root><GameProfileManager/></Root>'})

    def test_schema_drift_is_rejected(self):
        broken = dict(SOURCE, whdata_1=SOURCE['whdata_1'].replace(b'<markersStartIdx>4<', b'<markersStartIdx>5<'))
        with self.assertRaisesRegex(ValueError, 'non-contiguous'):
            self.build(source=broken)
        renamed = dict(NATIVE, whdata_1=NATIVE['whdata_1'].replace(b'Flags1', b'Flags2'))
        with self.assertRaisesRegex(ValueError, 'native: unexpected Ledge fields'):
            self.build(native=renamed)
        moved = dict(NATIVE, whdata_1=b'<Root version="1"><GameProfileManager/>'+NATIVE['whdata_1'][len(b'<Root version="1">'):-len(b'<GameProfileManager/></Root>')]+b'</Root>')
        with self.assertRaisesRegex(ValueError, 'leads with LedgeManager'):
            self.build(native=moved)
        nan = dict(SOURCE, whdata_1=SOURCE['whdata_1'].replace(b'<worldPosition>800,', b'<worldPosition>nan,'))
        with self.assertRaisesRegex(ValueError, 'invalid ledge marker'):
            self.build(source=nan)


class LedgeUpgradeTests(unittest.TestCase):
    def test_upgrade_writes_record_then_revalidates_without_rewriting(self):
        import setup_world_ledges as S
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1]) as d:
            p, src, dst = Path(d)/'pkg', Path(d)/'kcd1', Path(d)/'kcd2'
            for folder, files in ((p/'Data/Levels/kcd1_travel', {'objects_mission0.xml': MISSION, 'keep': b'1'}),
                                  (src/'Data/Levels/rataje', SOURCE), (dst/'Data/Levels/trosecko', NATIVE)):
                folder.mkdir(parents=True)
                with zipfile.ZipFile(folder/'level.pak', 'w') as z:
                    for n, b in files.items(): z.writestr(n, b)
            (p/'gluemapper-install.json').write_text(json.dumps(dict(campaign_level='kcd1_rataje',
                travel_bridge=dict(destination='kcd1_travel'))), encoding='utf-8')
            files, report = S.upgrade(p, src, dst)
            self.assertEqual(set(files), {'Data/Levels/kcd1_travel/level.pak', S.RECORD})
            self.assertEqual((report['ledges'], report['status']), (2, 'native_ledges'))
            level = p/'Data/Levels/kcd1_travel/level.pak'
            with zipfile.ZipFile(level) as z:
                self.assertEqual(z.read('keep'), b'1')
                self.assertIn(b'<LedgeManager>', z.read('whdata_1'))
            before = level.read_bytes()
            self.assertEqual(S.upgrade(p, None, None), ({}, report))
            self.assertEqual(level.read_bytes(), before)
            with zipfile.ZipFile(level) as z:
                changed = {n: z.read(n) for n in z.namelist()}
            changed['whdata_1'] = changed['whdata_1'].replace(b'<Flags0>551<', b'<Flags0>1<')
            level.unlink()
            with zipfile.ZipFile(level, 'w') as z:
                for n, b in changed.items(): z.writestr(n, b)
            with self.assertRaisesRegex(ValueError, 'Changed owned native ledge'):
                S.upgrade(p, None, None)


if __name__ == '__main__':
    unittest.main()
