from pathlib import Path
import sys
import unittest
import xml.etree.ElementTree as E

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from campaign_entity_links import native_guid, guid_value, append_links, entity_link
from build_campaign_runtime_probe import add_concept_preprocess


class EntityLinksTests(unittest.TestCase):
    def test_text_guid_matches_binary_identity_field_order(self):
        self.assertEqual(native_guid(0x123456789abcdef0), '9abcdef0-5678-1234')
        self.assertEqual(guid_value('9abcdef0-5678-1234'), 0x123456789abcdef0)
        for value in (0, -1, 1 << 64):
            with self.assertRaises(ValueError): native_guid(value)
        for value in ('1234', '00000000-0000-0000', '12345678-1234-1234-1234-123456789abc'):
            with self.assertRaises(ValueError): guid_value(value)

    def test_persistent_link_network_preserves_existing_and_deduplicates(self):
        a, b, c = (native_guid(i) for i in (1, 2, 3))
        source = f'<StaticLinksInfo version="1"><WaitingLinks><WaitingLink SourceId="{a}" TargetId="{b}"><LinkDefinition>home</LinkDefinition></WaitingLink></WaitingLinks></StaticLinksInfo>'.encode()
        data = append_links(source, [(a, b, 'home'), (a, b, "asset['door']"), (a, c, "asset['area']")])
        r = E.fromstring(data)
        self.assertEqual(len(r.find('WaitingLinks')), 2)
        self.assertEqual([n.text for n in r.find('WaitingLinks')[0]], ['home', "asset['door']"])
        self.assertEqual(append_links(data, [(a, c, "asset['area']")]), data)
        with self.assertRaises(ValueError): append_links(b'<StaticLinksInfo version="2"/>', [])

    def test_entity_link_writes_inline_link_and_records_waiting_tuple(self):
        a = E.Element('Entity', EntityId='10', EntityGuid=native_guid(10))
        b = E.Element('Entity', EntityId='20', EntityGuid=native_guid(20))
        waiting = []
        entity_link(a, b, 'teleportBefore', waiting)
        self.assertEqual(waiting, [(native_guid(10), native_guid(20), 'teleportBefore')])
        link = a.find('EntityLinks/Link')
        self.assertEqual((link.get('Name'), link.get('TargetId'), link.get('TargetGuid')),
                         ('teleportBefore', '20', native_guid(20)))
        entity_link(a, b, "asset['x']", waiting)
        self.assertEqual(len(a.findall('EntityLinks')), 1)
        self.assertEqual(len(a.findall('EntityLinks/Link')), 2)
        self.assertEqual(waiting[-1], (native_guid(10), native_guid(20), "asset['x']"))

    def test_concept_registration_preserves_people_and_binds_real_player(self):
        original = b'<Root version="1"><SoulList><Souls><Soul><Name>existing</Name><Guid>existing</Guid></Soul></Souls></SoulList></Root>'
        player = E.fromstring('<Soul version="8"><Name>Dude</Name><Player>1</Player><SharedSoulGuid>player-id</SharedSoulGuid></Soul>')
        data = add_concept_preprocess(original, 'Quests/Example.xml', 'example_world', player)
        r = E.fromstring(data)
        self.assertEqual([n.findtext('Name') for n in r.findall('./SoulList/Souls/Soul')], ['existing', 'Dude'])
        self.assertEqual(r.findtext('./ConceptManager/ConceptPaths/Path'), 'quests/example.xml')
        self.assertEqual(r.findtext('./AI/LevelPath'), 'data/levels/example_world')
        self.assertEqual(add_concept_preprocess(data, 'Quests/Example.xml', 'example_world', player), data)
        player.find('SharedSoulGuid').text = 'different'
        with self.assertRaisesRegex(ValueError, 'Conflicting'):
            add_concept_preprocess(data, 'Quests/Example.xml', 'example_world', player)

    def test_cached_network_extends_to_the_same_bytes_as_a_fresh_parse(self):
        import random
        from unittest.mock import patch
        import campaign_entity_links as module
        rng = random.Random(1); guids = [native_guid(i) for i in range(1, 30)]
        batches = [[(rng.choice(guids), rng.choice(guids), rng.choice(['home', "asset['door']", '_,use', 'work']))
                    for _ in range(rng.randint(0, 6))] for _ in range(24)]
        batches[5].append((guids[0], guids[1], ''))  # the untagged reservation edge
        def chain(cached):
            data, states, parses = b'', [], []
            real = module.ET.fromstring
            with patch.object(module.ET, 'fromstring', side_effect=lambda *a, **k: parses.append(1) or real(*a, **k)):
                for step, links in enumerate(batches):
                    if not cached: module._LAST = None
                    if step == 12: data = states[4]  # a caller hands back an older network
                    data = append_links(data, links, allow_untagged=step == 5); states.append(data)
            return states, len(parses)
        fresh, fresh_parses = chain(False)
        module._LAST = None
        cached, cached_parses = chain(True)
        self.assertEqual(cached, fresh)
        self.assertEqual(fresh_parses, 23)  # the empty start is built, every later step parses
        self.assertEqual(cached_parses, 1)  # only the handed-back older network
        root = E.fromstring(cached[-1])
        self.assertEqual(root.find('WaitingLinks')[-1].tail, '\n  ')
        self.assertTrue(all(n.text == '\n      ' and n[-1].tail == '\n    ' for n in root.find('WaitingLinks')))


if __name__ == '__main__': unittest.main()
