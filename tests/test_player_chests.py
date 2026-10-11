from contextlib import contextmanager
from pathlib import Path
import sys
import tempfile
import unittest
import xml.etree.ElementTree as E
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from player_chests import source_chests, native_master, register
from region_travel import guid


@contextmanager
def archive(payload):
    with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1]) as directory:
        path = Path(directory)/'fixture.pak'
        with zipfile.ZipFile(path, 'w') as z: z.writestr('objects_mission0.xml', payload)
        with zipfile.ZipFile(path) as z: yield z


SOURCE = b'''<Objects>
  <Entity EntityId="1" Name="SA_Land"><EntityLinks>
    <Link Name="sharedStash_master" TargetId="10"/>
    <Link Name="sharedStash" TargetId="11"/>
    <Link Name="sleepoverStash" TargetId="11"/>
    <Link Name="sharedStash" TargetId="12"/>
  </EntityLinks></Entity>
  <Entity EntityId="10" EntityClass="Stash" Pos="1,2,3" Rotate="0,0,0,1">
    <Properties object_Model="objects/chest.cga"><Animation anim_Open="source_open" anim_Close="source_close"/></Properties>
  </Entity>
  <Entity EntityId="11" EntityClass="Stash" Pos="4,5,6"><Properties object_Model="objects/chest.cga"/></Entity>
  <Entity EntityId="12" EntityClass="Stash" Layer="quest_state2{guid}"><Properties object_Model="objects/chest.cga"/></Entity>
  <Entity EntityId="13" EntityClass="Stash" Name="playerStashWithConfiscatedItems"><Properties object_Model="objects/chest.cga"/></Entity>
  <Entity EntityId="14" EntityClass="Stash" Name="merchant"><Properties object_Model="objects/chest.cga"/></Entity>
</Objects>'''

NATIVE = b'''<Objects><Entity EntityId="1" Name="Barbora"><EntityLinks>
 <Link Name="asset['player_stash']" TargetId="2"/></EntityLinks></Entity>
 <Entity EntityId="2" EntityGuid="204857b4-ae5f-04ba" EntityClass="Stash" EditorLayer="Trosky" Material="native-rag">
 <Properties object_Model="native.cdf" bOwnedByHome="0"><Database nRestockPeriodDays="0" nDestockPeriodDays="0"/></Properties></Entity></Objects>'''


class PlayerChestTests(unittest.TestCase):
    def setUp(self):
        with archive(SOURCE) as z: self.entities, self.records = source_chests(z)
        with archive(NATIVE) as z: self.master = native_master(z)
        self.files = {'objects_mission0.xml': b'''<Objects>
          <Entity Name="glue_item_10"/><Entity Name="glue_item_11"/><Entity Name="glue_item_14"/>
          <Entity Name="gm_debug_supply_chest" EntityClass="Stash"/>
          <Entity Name="Level" EntityClass="LevelHolder" EntityId="20" EntityGuid="00000020-0000-0000"/>
          </Objects>''',
          'waitinglinks.xml': b'<StaticLinksInfo version="1"><WaitingLinks/></StaticLinksInfo>',
          'whdata_0': b'<Root><SoulList><Souls><Soul><Player>1</Player><EntityGuid>00007777-0000-0000</EntityGuid></Soul></Souls></SoulList></Root>'}

    def build(self, files=None):
        return register(files or self.files, self.entities, self.records, self.master,
                        {'objects/chest.cga': 'gluebuild/player_chests/chest.cga'}, guid)

    def test_classification_uses_authored_links_not_names_or_models(self):
        self.assertEqual([r['source_id'] for r in self.records], ['10', '11', '12'])
        self.assertEqual(len([r for r in self.records if r['source_id'] == '11']), 1)
        self.assertFalse(self.records[-1]['active'])

    def test_shared_native_identity_and_player_ownership_are_preserved(self):
        files, report = self.build()
        root = E.fromstring(files['objects_mission0.xml'])
        master = root.find("Entity[@Name='gm_player_chest_10']")
        slave = root.find("Entity[@Name='gm_player_chest_11']")
        self.assertEqual(master.get('EntityGuid'), self.master.get('EntityGuid'))
        link = slave.find('EntityLinks/Link')
        self.assertEqual(link.get('Name'), 'masterStash')
        self.assertEqual(link.get('TargetId'), master.get('EntityId'))
        self.assertEqual(link.get('TargetGuid'), master.get('EntityGuid'))
        network = {(l.get('SourceId'), l.get('TargetId'), d.text)
                   for l in E.fromstring(files['waitinglinks.xml']).iter('WaitingLink') for d in l}
        for chest in (master, slave):
            self.assertIn(('00007777-0000-0000', chest.get('EntityGuid'), 'owner'), network)
        self.assertIn((slave.get('EntityGuid'), master.get('EntityGuid'), 'masterStash'), network)
        self.assertEqual(report['converted'], 2)
        self.assertEqual(files['whdata_0'], self.files['whdata_0'])

    def test_no_restock_or_seeded_inventory_and_original_open_animation(self):
        files, _ = self.build()
        chest = E.fromstring(files['objects_mission0.xml']).find("Entity[@Name='gm_player_chest_10']")
        self.assertEqual(chest.get('Pos'), '1,2,3')
        self.assertNotIn('Material', chest.attrib)
        props = chest.find('Properties')
        self.assertEqual(props.find('Database').attrib, {'nRestockPeriodDays':'0','nDestockPeriodDays':'0'})
        self.assertEqual(props.find('Animation').get('anim_Open'), 'source_open')
        self.assertEqual(props.find('Lock').get('bLocked'), '0')

    def test_unrelated_loot_and_reward_chests_stay_unchanged(self):
        files, _ = self.build()
        root = E.fromstring(files['objects_mission0.xml'])
        self.assertIsNotNone(root.find("Entity[@Name='glue_item_14']"))
        self.assertIsNotNone(root.find("Entity[@Name='gm_debug_supply_chest']"))
        self.assertIsNone(root.find("Entity[@Name='glue_item_10']"))
        self.assertIsNone(root.find("Entity[@Name='gm_player_chest_12']"))

    def test_reinstall_and_native_identity_collision_fail_before_overwrite(self):
        files, _ = self.build()
        with self.assertRaisesRegex(ValueError, 'already converted'): self.build(files)
        files = dict(self.files)
        files['objects_mission0.xml'] = b'<Objects><Entity EntityGuid="204857b4-ae5f-04ba"/></Objects>'
        with self.assertRaisesRegex(ValueError, 'native master stash identity'): self.build(files)

    def test_missing_source_master_does_not_create_disconnected_storage(self):
        with archive(SOURCE.replace(b'sharedStash_master', b'sharedStash')) as z:
            with self.assertRaisesRegex(ValueError, 'one active source master'): source_chests(z)

    def test_missing_native_campaign_binding_fails(self):
        with archive(NATIVE.replace(b"asset['player_stash']", b"asset['other']")) as z:
            with self.assertRaisesRegex(ValueError, 'native|Native'): native_master(z)


if __name__ == '__main__': unittest.main()
