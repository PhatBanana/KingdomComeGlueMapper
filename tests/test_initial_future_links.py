"""Default future Home/Work links become live links, as the source NPC init does."""
from pathlib import Path
import sys
import unittest
import xml.etree.ElementTree as E

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'tools'))
from character_person import initial_future_links


def actor(*names):
    e = E.Element('Entity', Name='npc')
    links = E.SubElement(e, 'EntityLinks')
    for i, n in enumerate(names):
        E.SubElement(links, 'Link', Name=n, TargetId=str(i + 1), TargetGuid='g%d' % (i + 1))
    return e


def names(e):
    return [(l.get('Name'), l.get('TargetId')) for l in e.findall('EntityLinks/Link')]


class FutureLinks(unittest.TestCase):
    def test_default_future_links_become_home_and_work(self):
        source = actor('futureHome', 'futureWork[merchant]', "futureHome[event('later')]",
                       "futureWork[event('later'),work('pub')]")
        result = initial_future_links(source)
        self.assertEqual(names(result)[-2:], [('Home', '1'), ('Work[merchant]', '2')])
        self.assertEqual(len(names(source)), 4)  # the source graph is not mutated

    def test_existing_links_win(self):
        source = actor('Home,owner', 'Work[merchant]', 'futureHome', 'futureWork[baker]')
        self.assertIs(initial_future_links(source), source)

    def test_evented_links_stay_quest_only(self):
        source = actor("futureWork[event('later')]")
        self.assertIs(initial_future_links(source), source)

    def test_two_defaults_are_ambiguous(self):
        with self.assertRaisesRegex(ValueError, 'Ambiguous default future work'):
            initial_future_links(actor('futureWork[a]', 'futureWork[b]'))


if __name__ == '__main__':
    unittest.main()
