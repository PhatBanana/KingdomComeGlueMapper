from pathlib import Path
import sys
import unittest
import xml.etree.ElementTree as ET

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from world_environment import retire_converted_audio


def fixture():
    sources = ET.fromstring('''<Objects>
      <Entity EntityId="1" EntityClass="AudioAreaRandom"><Properties audioTriggerPlayTrigger="a_o_village_oneshot"/></Entity>
      <Entity EntityId="2" EntityClass="AudioAreaAmbience"><Properties audioTriggerPlayTrigger="a_l_village_skalice"/></Entity>
    </Objects>''')
    mission = b'''<Objects>
      <Entity Name="quest_actor" EntityId="9" Pos="7,8,9"><Properties value="keep"/></Entity>
      <Entity Name="gm_environment_1" EntityId="10" EntityClass="AudioAreaAmbience" Pos="1,2,3"><Properties audioTriggerPlayTrigger="a_l_village_amb01"/></Entity>
      <Entity Name="gm_environment_2" EntityId="11" EntityClass="AudioAreaAmbience" Pos="4,5,6"><Properties audioTriggerPlayTrigger="a_l_village_amb01"/></Entity>
      <Entity Name="gm_environment_area_shared" EntityId="12" EntityClass="AreaShape"><Area><Entities><Entity Id="10"/><Entity Id="11"/></Entities></Area></Entity>
      <Entity Name="gm_environment_area_retired" EntityId="13" EntityClass="AreaShape"><Area><Entities><Entity Id="10"/></Entities></Area></Entity>
    </Objects>'''
    return mission, {e.get('EntityId'): e for e in sources}


class AmbientUpgradeTests(unittest.TestCase):
    def test_source_policy_removes_only_obsolete_loop_and_updates_shared_boundary(self):
        mission, sources = fixture()
        result, report = retire_converted_audio(mission, entities=sources)
        before, after = ET.fromstring(mission), ET.fromstring(result)
        self.assertEqual([e.get('EntityId') for e in after], ['9', '11', '12'])
        for identity in ('9', '11'):
            self.assertEqual(ET.tostring(before.find(f"Entity[@EntityId='{identity}']")),
                             ET.tostring(after.find(f"Entity[@EntityId='{identity}']")))
        self.assertEqual([e.get('Id') for e in after.findall('.//Area/Entities/Entity')], ['11'])
        self.assertEqual(report['removed_emitters'], ['gm_environment_1'])
        self.assertEqual(report['removed_boundaries'], ['gm_environment_area_retired'])
        repeated, report = retire_converted_audio(result, entities=sources)
        self.assertEqual(repeated, result)
        self.assertFalse(report['cleared_controls'])

    def test_retirement_is_generic_and_retains_reverb_action(self):
        mission, sources = fixture()
        sources['1'].find('Properties').set('audioTriggerPlayTrigger', 'mus_enforced_stealth_music')
        root = ET.fromstring(mission)
        root.find("Entity[@EntityId='10']/Properties").set('audioEnvironmentEnvironment', 'native_reverb')
        result, report = retire_converted_audio(ET.tostring(root), entities=sources)
        props = ET.fromstring(result).find("Entity[@EntityId='10']/Properties")
        self.assertEqual(props.get('audioTriggerPlayTrigger'), '')
        self.assertEqual(props.get('audioEnvironmentEnvironment'), 'native_reverb')
        self.assertFalse(report['removed_emitters'])
        self.assertFalse(report['removed_boundaries'])

    def test_unrelated_mission_needs_no_source_and_is_byte_identical(self):
        mission = b'<Objects><Entity Name="native_audio" EntityClass="AudioAreaAmbience"/></Objects>'
        self.assertEqual(retire_converted_audio(mission)[0], mission)

    def test_missing_source_and_foreign_references_fail_closed(self):
        mission, sources = fixture()
        with self.assertRaisesRegex(ValueError, 'source folder'):
            retire_converted_audio(mission)
        with self.assertRaisesRegex(ValueError, 'Missing source'):
            retire_converted_audio(mission, entities={})
        for reference in ('<EntityLinks><Link TargetId="10"/></EntityLinks>',
                          '<Area><Entities><Entity Id="10"/></Entities></Area>',
                          '<FlowGraph><Nodes><Node><Inputs entityId="10"/></Node></Nodes></FlowGraph>'):
            root = ET.fromstring(mission)
            root[0].append(ET.fromstring(reference))
            with self.assertRaisesRegex(ValueError, 'references retired'):
                retire_converted_audio(ET.tostring(root), entities=sources)
