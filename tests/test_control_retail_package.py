import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
import xml.etree.ElementTree as ET

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from control_retail_package import merge_table, merge_storm, character_rekeys, rewrite_pak
from control_system_sources import SourceObjects, authored_links
from full_system_control import local_home
from region_travel_dialogue import patch, patch_test_world, DIALOGUE, HOST


class ControlPackageTests(unittest.TestCase):
    def test_patch_preserves_native_local_records_and_has_one_active_replacement(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / 'level.pak'
            with zipfile.ZipFile(path, 'w') as archive:
                entry = zipfile.ZipInfo('objects_mission0.xml')
                entry.compress_type = zipfile.ZIP_DEFLATED
                entry.extra = b'\xfe\xca\x04\x00test'
                archive.writestr(entry, b'<Objects/>' * 100)
                archive.writestr('whdata_0', b'<Old/>')
                archive.writestr('terrain/cover.ctc', bytes(range(256)))
            original = path.read_bytes()
            with zipfile.ZipFile(path) as archive:
                directory = archive.start_dir
                before = {i.filename: (i.header_offset, i.compress_type, i.extra, i.CRC)
                          for i in archive.infolist()}
            rewrite_pak(path, {'whdata_0': b'<New/>'})
            self.assertEqual(path.read_bytes()[:directory], original[:directory])
            with zipfile.ZipFile(path) as archive:
                self.assertEqual(archive.namelist().count('whdata_0'), 1)
                self.assertEqual(archive.read('whdata_0'), b'<New/>')
                self.assertIsNone(archive.testzip())
                for name in ('objects_mission0.xml', 'terrain/cover.ctc'):
                    i = archive.getinfo(name)
                    self.assertEqual((i.header_offset, i.compress_type, i.extra, i.CRC), before[name])

    def test_menu_preserves_rattay_and_kuttenberg_with_separate_transfer_chain(self):
        dialog = b'<Database><Skald><FaderDialog><Ports/><Dialogue><Decision><Sequences><Sequence Name="original"><UiPrompt StringName="ui_prechod_z_seq1_Gr38"/></Sequence><Sequence Name="exit"/></Sequences></Decision></Dialogue></FaderDialog></Skald></Database>'
        host = b'<Database><Skald><Gameplay><Nodes><State Name="original"/></Nodes></Gameplay></Skald></Database>'
        first, _ = patch(dialog, host)
        second, strings = patch_test_world(first[DIALOGUE], first[HOST])
        choices = ET.fromstring(second[DIALOGUE]).findall('.//Sequence/UiPrompt')
        self.assertEqual({n.get('StringName') for n in choices}, {'ui_prechod_z_seq1_Gr38', 'ui_gluemapper_travel_kcd1', 'ui_gluemapper_travel_test_world'})
        nodes = ET.fromstring(second[HOST]).find('.//Nodes')
        self.assertEqual(len({n.get('Name') for n in nodes}), len(nodes))
        switch = nodes.find("Function[@Name='gluemapper_switch_to_test_world']")
        self.assertEqual(switch.find('Constant').get('Value'), 'gluemappertravel_to_test_world')
        self.assertEqual(switch.find('Edge').get('From'), 'gluemapper_test_prepare_travel.OnExec')
        self.assertIn(b'(Travel to Test world)', strings)
        with self.assertRaises(ValueError): patch_test_world(second[DIALOGUE], second[HOST])

    def test_shared_records_are_deduplicated_but_conflicts_fail(self):
        a = b'<database><souls version="2"><soul soul_id="a" soul_name="A"/></souls></database>'
        b = b'<database><souls version="2"><soul soul_name="A" soul_id="a"/><soul soul_id="b"/></souls></database>'
        self.assertEqual(len(ET.fromstring(merge_table(a, b))[0]), 2)
        with self.assertRaisesRegex(ValueError, 'Conflicting record'):
            merge_table(a, b.replace(b'soul_name="A"', b'soul_name="Changed"'))

    def test_storm_preserves_existing_imports(self):
        base = b'<storm><tasks><task name="roles"><source path="coach.xml"/><source path="inn.xml"/></task></tasks></storm>'
        extra = b'<storm><tasks><task name="roles"><source path="coach.xml"/><source path="gmtest_trosky_ska_fricek.xml"/></task></tasks></storm>'
        paths = [s.get('path') for s in ET.fromstring(merge_storm(base, extra)).findall('.//source')]
        self.assertEqual(paths, ['coach.xml', 'inn.xml', 'gmtest_trosky_ska_fricek.xml'])

    def test_character_guid_conflicts_receive_stable_independent_ids(self):
        guid = '615fff35-a99f-55fa-bd04-2b662d8d6aa3'
        a = ('<database><clothing_presets><clothing_preset clothing_preset_id="' + guid + '" clothing_preset_name="existing"/></clothing_presets></database>').encode()
        b = a.replace(b'"existing"', b'"control"')
        existing = {'libs/tables/item/clothing_preset__kingdomcomegluemapper.xml': a}
        source = {'Libs/Tables/item/clothing_preset__test.xml': b}
        remap = character_rekeys(existing, source)
        self.assertNotEqual(remap[guid], guid)
        self.assertEqual(remap, character_rekeys(existing, source))
        self.assertEqual(existing['libs/tables/item/clothing_preset__kingdomcomegluemapper.xml'], a)

    def test_prefab_virtual_port_is_resolved_without_runtime_entity(self):
        with tempfile.TemporaryDirectory() as d:
            Path(d, 'main.lyr').write_text('<Layer><Objects><Object Id="one" Name="system"><EntityLinks><Link Name="service" TargetId="virtual"/></EntityLinks></Object><Object Id="prefab" Name="service"><ObjectGUID Instance="virtual" Name="port"/></Object></Objects></Layer>')
            index = SourceObjects(d)
            selected, _, missing = index.closure(['one'], authored_links)
            self.assertEqual(selected, {'one', 'prefab'})
            self.assertFalse(missing)

    def test_residents_do_not_share_a_home_area(self):
        objects = ET.Element('Objects')
        for name in ('one', 'two'):
            npc = ET.SubElement(objects, 'Object', Name=name, Pos='1,2,3')
            local_home(objects, npc, 'land')
        homes = objects.findall("Object[@EntityClass='SchedulerHub']/EntityLinks/Link[@Name='home_area']")
        self.assertEqual(len({h.get('TargetId') for h in homes}), 2)
        self.assertNotIn('land', {h.get('TargetId') for h in homes})
        self.assertEqual({l.get('TargetId') for l in objects.findall("Object/EntityLinks/Link[@Name='^delegate']")}, {'land'})


if __name__ == '__main__': unittest.main()
