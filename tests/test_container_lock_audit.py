from contextlib import contextmanager
from pathlib import Path
import sys
import tempfile
import unittest
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from container_lock_audit import audit


@contextmanager
def archive(files):
    with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1]) as directory:
        path = Path(directory) / 'fixture.pak'
        with zipfile.ZipFile(path, 'w') as z:
            for name, data in files.items():
                z.writestr(name, data)
        with zipfile.ZipFile(path) as z:
            yield z


SOURCE_MAIN = b'''<Objects>
  <Entity EntityId="1" EntityClass="Stash" Name="chest_a" Pos="700,3400,50"><Properties><Lock bLocked="1" guidItemClassId="AAAA"/></Properties></Entity>
  <Entity EntityId="2" EntityClass="Stash" Name="chest_b" Pos="701,3400,50"><Properties><Lock bLocked="0"/></Properties></Entity>
</Objects>'''
SOURCE_LAYER = b'''<Objects>
  <Entity EntityId="3" EntityClass="Stash" Name="chest_c" Layer="sv_state0{x}" Pos="702,3400,50"><Properties><Lock bLocked="1"/></Properties></Entity>
  <Entity EntityId="4" EntityClass="Stash" Name="chest_d" Layer="sv_state0{x}" Pos="900,3400,50"><Properties><Lock bLocked="0" guidItemClassId="00000000-0000-0000-0000-000000000000"/></Properties></Entity>
</Objects>'''
MISSION = b'''<Objects>
  <Entity EntityId="10" EntityClass="Stash" Name="gm_container_1" Pos="700,3400,50"><Properties><Lock bLocked="1" guidItemClassId="aaaa"/></Properties></Entity>
  <Entity EntityId="11" EntityClass="Stash" Name="gm_container_2" Pos="701,3400,50"><Properties><Lock bLocked="1"/></Properties></Entity>
  <Entity EntityId="12" EntityClass="Stash" Name="gm_container_3" Pos="702,3400,50"><Properties><Lock bLocked="1" guidItemClassId="bbbb"/></Properties></Entity>
  <Entity EntityId="13" EntityClass="Stash" Name="gm_container_4" Pos="900,3400,50"><Properties><Lock bLocked="0" guidItemClassId=""/></Properties></Entity>
  <Entity EntityId="14" EntityClass="Stash" Name="gm_container_9" Pos="703,3400,50"><Properties><Lock bLocked="0"/></Properties></Entity>
  <Entity EntityId="15" EntityClass="Stash" Name="gm_player_chest_1" Pos="704,3400,50"><Properties><Lock bLocked="0"/></Properties></Entity>
  <Entity EntityId="16" EntityClass="GeomEntity" Name="gm_container_2" Pos="705,3400,50"/>
</Objects>'''


class ContainerLockAuditTests(unittest.TestCase):
    def test_reports_only_real_lock_and_key_differences(self):
        with archive({'objects_mission0.xml': SOURCE_MAIN, 'layers/sv_state0{x}.xml': SOURCE_LAYER}) as source:
            report = audit(MISSION, source, region=(600, 3330, 800, 3600))
        self.assertEqual((report['containers'], report['locked'], report['unlocked']), (5, 3, 2))
        self.assertEqual(report['mismatches'], [
            {'name': 'gm_container_2', 'field': 'bLocked', 'converted': True, 'source': False},
            {'name': 'gm_container_3', 'field': 'guidItemClassId', 'converted': 'bbbb', 'source': ''},
            {'name': 'gm_container_9', 'field': 'source', 'converted': 'present', 'source': 'missing'}])
        inside = {c['name']: c for c in report['region']['containers']}
        self.assertEqual(set(inside), {'gm_container_1', 'gm_container_2', 'gm_container_3'})
        self.assertEqual(report['region']['locked'], 3)
        self.assertEqual(inside['gm_container_1']['source_layer'], '')
        self.assertEqual(inside['gm_container_3']['source_layer'], 'sv_state0')
        self.assertTrue(inside['gm_container_1']['source_locked'])

    def test_matching_world_has_no_mismatches_and_no_region_without_a_box(self):
        matching = MISSION.replace(b'Name="gm_container_2" Pos="701,3400,50"><Properties><Lock bLocked="1"/>',
                                   b'Name="gm_container_2" Pos="701,3400,50"><Properties><Lock bLocked="0"/>')
        matching = matching.replace(b'guidItemClassId="bbbb"', b'').replace(b'Name="gm_container_9"', b'Name="gm_other_9"')
        with archive({'objects_mission0.xml': SOURCE_MAIN, 'layers/sv_state0{x}.xml': SOURCE_LAYER}) as source:
            report = audit(matching, source)
        self.assertEqual(report['mismatches'], [])
        self.assertEqual(report['containers'], 4)
        self.assertNotIn('region', report)


if __name__ == '__main__':
    unittest.main()
