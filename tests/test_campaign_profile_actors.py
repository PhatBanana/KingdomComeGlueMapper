import sys
from pathlib import Path
import unittest
import xml.etree.ElementTree as ET

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from campaign_profile_actors import collect, select


class ProfileActorTests(unittest.TestCase):
    def test_explicit_actor_roots_preserve_profile_and_placement(self):
        actors = select(*self.fixtures(), ['actor_refugee'])
        self.assertEqual(len(actors), 1)
        self.assertEqual(actors[0]['profiles'], ['later'])
        self.assertEqual(actors[0]['entity_guid'], '20')
        self.assertEqual(actors[0]['transform']['Pos'], '4,5,6')

    def test_explicit_actor_root_cannot_silently_disappear(self):
        with self.assertRaisesRegex(ValueError, 'Missing selected source actors'):
            select(*self.fixtures(), ['missing'])
        p, s, d = self.fixtures()
        d['layers/duplicate.xml'] = d['layers/cast{a}.xml']
        with self.assertRaisesRegex(ValueError, 'ambiguous selected actor placement'):
            select(p, s, d, ['actor'])

    def fixtures(self):
        profiles = ET.fromstring('''<Root>
          <GameProfile><Name>opening</Name><GameLayers><GameLayer>cast{A}</GameLayer></GameLayers></GameProfile>
          <GameProfile><Name>later</Name><GameLayers><GameLayer>cast{B}</GameLayer></GameLayers></GameProfile>
          </Root>''')
        souls = ET.fromstring('''<Root><SoulList><Souls>
          <Soul><Name>actor</Name><SharedSoulGuid>early</SharedSoulGuid><Guid>instance1</Guid><EntityGuid>16</EntityGuid></Soul>
          <Soul><Name>actor_refugee</Name><SharedSoulGuid>late</SharedSoulGuid><Guid>instance2</Guid><EntityGuid>32</EntityGuid></Soul>
          </Souls></SoulList></Root>''')
        docs = {'layers/cast{a}.xml': b'<Objects><Entity Name="same_role" EntityClass="NPC" EntityGuid="10" Pos="1,2,3"/></Objects>',
                'layers/cast{b}.xml': b'<Objects><Entity Name="same_role" EntityClass="NPC" EntityGuid="20" Pos="4,5,6"/></Objects>'}
        return profiles, souls, docs

    def test_profile_identity_separates_story_variants(self):
        records = collect(*self.fixtures(), ['opening'])
        self.assertEqual([r['soul_id'] for r in records], ['early'])
        self.assertEqual(records[0]['transform']['Pos'], '1,2,3')

    def test_missing_layer_or_soul_is_not_silently_skipped(self):
        p,s,d = self.fixtures()
        with self.assertRaisesRegex(ValueError, 'Missing source profile layer'):
            collect(p,s,{},['opening'])
        s.find('./SoulList/Souls').clear()
        with self.assertRaisesRegex(ValueError, 'missing source soul'):
            collect(p,s,d,['opening'])

    def test_shared_layer_keeps_both_activation_owners(self):
        p,s,d = self.fixtures()
        p.findall('GameProfile')[1].find('GameLayers/GameLayer').text = 'cast{A}'
        actors = collect(p,s,d,['opening','later'])
        self.assertEqual(len(actors),1)
        self.assertEqual(actors[0]['profiles'],['later','opening'])


if __name__ == '__main__': unittest.main()
