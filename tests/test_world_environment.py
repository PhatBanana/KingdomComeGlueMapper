import sys
from pathlib import Path
import unittest
import xml.etree.ElementTree as ET

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'tools'))
from world_environment import convert, particle_count_limit
from region_travel import guid


class EnvironmentTests(unittest.TestCase):
    def test_particle_limit_is_targeted_idempotent_and_preserves_effect_size(self):
        props = ET.Element('Properties', ParticleEffect='WH_vranik.vranik.fire_e',
                           CountScale='1', Scale='2', bActive='1')
        self.assertEqual(particle_count_limit(props)['after'], .25)
        self.assertIsNone(particle_count_limit(props))
        self.assertEqual(props.get('Scale'), '2')
        self.assertEqual(props.get('bActive'), '1')
        props.set('CountScale', '.1')
        self.assertIsNone(particle_count_limit(props))
        props.set('ParticleEffect', 'Native.Smoke')
        props.set('CountScale', '1')
        self.assertIsNone(particle_count_limit(props))
        self.assertEqual(props.get('CountScale'), '1')

    def test_allocator_skips_local_player_id_and_remaps_area(self):
        source = ET.fromstring('''<Objects>
        <Entity EntityId="1" EntityClass="AudioAreaAmbience"><Properties audioTriggerPlayTrigger="native"/></Entity>
        <Entity EntityId="2" EntityClass="AreaShape"><Area><Entities><Entity Id="1"/></Entities></Area></Entity>
        </Objects>''')
        data, _ = convert(b'<Objects><Entity EntityId="30582" Name="existing"/></Objects>',
                          {e.get('EntityId'):e for e in source}, {'1','2'}, {},
                          {('ATLTrigger','native'):'native'}, guid)
        root = ET.fromstring(data)
        self.assertEqual(root[1].get('EntityId'), '30584')
        self.assertEqual(root[2].get('EntityId'), '30585')
        self.assertEqual(root[2].find('Area/Entities/Entity').get('Id'), '30584')
        self.assertIsNone(root.find("Entity[@EntityId='30583']"))

        # The boundary allocator must reserve it too, not only audio emitters.
        data, _ = convert(b'<Objects><Entity EntityId="30581"/></Objects>',
                          {e.get('EntityId'):e for e in source}, {'1','2'}, {},
                          {('ATLTrigger','native'):'native'}, guid)
        root = ET.fromstring(data)
        self.assertEqual(root[1].get('EntityId'), '30582')
        self.assertEqual(root[2].get('EntityId'), '30584')
        self.assertEqual(root[2].find('Area/Entities/Entity').get('Id'), '30582')

    def convert(self, text, active=None, aliases=None):
        entities = {e.get('EntityId'):e for e in ET.fromstring(text)}
        return convert(b'<Objects><Entity EntityId="100" EntityGuid="existing" Name="keep"/></Objects>',
                       entities, set(entities) if active is None else active,
                       {'native.smoke':'Native.Smoke'},
                       {('ATLTrigger','a_l_native'):'a_l_native', ('ATLRtpc','amb_fade_dist'):'amb_fade_dist'}, guid, aliases)

    def test_particle_transform_and_inactive_filter(self):
        data, report = self.convert('''<Objects>
        <Entity EntityId="1" Pos="10,20,30" Scale="2,2,2"/>
        <Entity EntityId="2" ParentId="1" Pos="1,0,0" EntityClass="ParticleEffect"><Properties ParticleEffect="native.smoke" bActive="0"/></Entity>
        <Entity EntityId="3" EntityClass="FogVolume"><Properties bActive="1"/></Entity>
        </Objects>''', {'2'})
        entity = ET.fromstring(data).find("Entity[@Name='gm_environment_2']")
        self.assertEqual(entity.get('Pos'), '12.0,20.0,30.0')
        self.assertIsNone(entity.get('ParentId'))
        self.assertEqual(entity.find('Properties').get('bActive'),'0')
        self.assertEqual(report['deferred'], {'inactive_layer':1})

    def test_audio_boundary_references_are_remapped_without_other_targets(self):
        data, report = self.convert('''<Objects>
        <Entity EntityId="1" EntityClass="AudioAreaAmbience"><Properties audioTriggerPlayTrigger="a_l_native"/></Entity>
        <Entity EntityId="2" EntityClass="AreaShape" Pos="5,6,7"><Area Height="20" Priority="4"><Points><Point Pos="0,0,0" ObstructSound="1"/><Point Pos="10,0,0"/><Point Pos="0,10,0"/></Points><Entities><Entity Id="1"/><Entity Id="99"/></Entities></Area></Entity>
        </Objects>''')
        root = ET.fromstring(data); area=root.find("Entity[@EntityClass='AreaShape']")
        self.assertEqual(area.find('Area').get('Priority'),'4')
        self.assertEqual(area.find('Area/Points/Point').get('ObstructSound'),'1')
        self.assertEqual([e.get('Id') for e in area.findall('Area/Entities/Entity')],
                         [root.find("Entity[@EntityClass='AudioAreaAmbience']").get('EntityId')])
        self.assertEqual(report['audio_boundaries'],1)
        self.assertEqual(root[0].get('EntityGuid'),'existing')

    def test_loop_substitution_does_not_retrigger_as_random_one_shot(self):
        data, report=self.convert('''<Objects><Entity EntityId="1" EntityClass="AudioAreaRandom"><Properties audioTriggerPlayTrigger="old" fMinDelay="2" fMaxDelay="4"/></Entity></Objects>''',
                                  aliases={('ATLTrigger','old'):'a_l_native'})
        entity=ET.fromstring(data)[1]
        self.assertEqual(entity.get('EntityClass'),'AudioAreaAmbience')
        self.assertIsNone(entity.find('Properties').get('fMinDelay'))
        self.assertTrue(report['records'][0]['loop_substitution'])

    def test_village_one_shot_is_retired_not_doubled_as_village_loop(self):
        from environment_audio import aliases
        data,report=self.convert('''<Objects><Entity EntityId="1" EntityClass="AudioAreaRandom"><Properties audioTriggerPlayTrigger="a_o_village_oneshot" fMinDelay="9" fMaxDelay="24"/></Entity></Objects>''',
                                 aliases=aliases())
        self.assertEqual(len(ET.fromstring(data)),1)
        self.assertEqual(report['retired'], {'no_native_ambient_action':1})

    def test_missing_native_control_is_reported_not_silently_emitted(self):
        data,report=self.convert('''<Objects><Entity EntityId="1" EntityClass="AudioTriggerSpot"><Properties audioTriggerPlayTriggerName="missing"/></Entity></Objects>''')
        self.assertEqual(len(ET.fromstring(data)),1)
        self.assertEqual(report['deferred'], {'missing_native_audio_controls':1})

    def test_retired_rtpc_does_not_drive_unrelated_native_parameter(self):
        data,report=self.convert('''<Objects><Entity EntityId="1" EntityClass="AudioAreaEntity"><Properties/><FlowGraph><Nodes><Node Id="1" Class="Audio:Rtpc"><Inputs audioRTPC_Name="ambient_morphing"/></Node><Node Id="2" Class="entity:AudioAreaEntity"/></Nodes><Edges><Edge nodeIn="1" nodeOut="2"/></Edges></FlowGraph></Entity></Objects>''')
        self.assertEqual(len(ET.fromstring(data)),1)
        self.assertEqual(report['retired'], {'legacy_global_mixer_control':1})

    def test_repeat_install_rejected(self):
        with self.assertRaisesRegex(ValueError,'already installed'):
            convert(b'<Objects><Entity Name="gm_environment_1"/></Objects>', {},set(),{},{},guid)


if __name__ == '__main__': unittest.main()
