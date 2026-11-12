import copy
from pathlib import Path
import sys
import unittest
import xml.etree.ElementTree as E

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from campaign_quest_graph import emit_project
from campaign_quest_registration import register
from test_campaign_quest_graph import model as quest_model

SID = '41315647-d7e3-98de-b434-338e04c51bb6'
PATH = '../gm_kcd1_quests/arbitrary_quest.xml'
PROJECT = (b'<Database><Skald><Project Name="travel"><Definitions/><Nodes/><Types/>'
           b'<ObjectiveValueTypes><ObjectiveValueType Type="None" IsPast="false" Icon="Exclamation"/>'
           b'</ObjectiveValueTypes><Assets/></Project></Skald></Database>')
ENTRY = b'<Database><Skald><Level Name="level"><Definitions/><Nodes/></Level></Skald></Database>'


def with_people():
    m = quest_model()
    m['tables']['quest_npc'] = dict(rows=[dict(quest_id='42', quest_asset_id='9', soul_id=SID)])
    m['tables']['quest_tracked_asset'] = dict(rows=[dict(
        quest_id='42', objective_id='4', quest_asset_id='9', on_map='True')])
    return m


def emitted(m=None):
    files, _ = emit_project([m or quest_model()], 'gm_quests')
    return files['gm_quests.xml'], files['gm_quests/arbitrary_quest.xml']


class RegistrationTests(unittest.TestCase):
    def test_type_copied_once_and_quest_lands_in_the_level(self):
        project, quest = emitted()
        p, e, q, report = register(PROJECT, ENTRY, project, quest, PATH)
        proot, eroot = E.fromstring(p).find('Skald/Project'), E.fromstring(e).find('Skald/Level')
        self.assertEqual([t.get('TypeName') for t in proot.findall('Types/Type')], ['gm_questsObjectiveProgress'])
        self.assertEqual([t.get('Type') for t in proot.findall('ObjectiveValueTypes/ObjectiveValueType')],
                         ['None', 'Started', 'Completed', 'Canceled'])
        self.assertEqual(report['objective_value_types'], ['Started', 'Completed', 'Canceled'])
        self.assertEqual([d.get('File') for d in eroot.findall('Definitions/Definition')], [PATH])
        self.assertEqual([(n.tag, n.get('Name')) for n in eroot.find('Nodes')], [('arbitrary_quest',) * 2])
        self.assertEqual(proot.find('Nodes').findall('*'), [])
        self.assertEqual(proot.find('Definitions').findall('*'), [])
        self.assertIsNone(E.fromstring(q).find('Skald/Quest').get('Type'))
        self.assertIsNone(report['quest_type'])

    def test_group_sets_activity_type_and_unknown_group_is_refused(self):
        project, quest = emitted()
        _, _, q, report = register(PROJECT, ENTRY, project, quest, PATH, group='Side-Activity')
        self.assertEqual(E.fromstring(q).find('Skald/Quest').get('Type'), 'Activity')
        self.assertEqual(report['quest_type'], 'Activity')
        with self.assertRaisesRegex(ValueError, 'group'):
            register(PROJECT, ENTRY, project, quest, PATH, group='Main')
        conflicting = quest.replace(b'<Quest ', b'<Quest Type="Main" ', 1)
        with self.assertRaisesRegex(ValueError, 'Conflicting quest type'):
            register(PROJECT, ENTRY, project, conflicting, PATH, group='Side-Activity')

    def test_collisions_are_refused(self):
        project, quest = emitted()
        p, e, q, _ = register(PROJECT, ENTRY, project, quest, PATH)
        with self.assertRaisesRegex(ValueError, 'Quest name already registered'):
            register(p, e, project, quest, '../other/arbitrary_quest.xml')
        e_file = ENTRY.replace(b'<Definitions/>', ('<Definitions><Definition File="%s"/></Definitions>' % PATH).encode())
        with self.assertRaisesRegex(ValueError, 'Quest file already registered'):
            register(PROJECT, e_file, project, quest, PATH)
        with self.assertRaisesRegex(ValueError, 'Quest type already registered'):
            register(p, ENTRY, project, quest, PATH)
        for bad in ('/abs/q.xml', 'C:/q.xml', '..\\q.xml'):
            with self.subTest(path=bad), self.assertRaisesRegex(ValueError, 'relative'):
                register(PROJECT, ENTRY, project, quest, bad)
        with self.assertRaises(ValueError):
            register(PROJECT, b'<Database><Skald><Project Name="x"/></Skald></Database>', project, quest, PATH)

    def test_refused_registration_does_not_change_inputs(self):
        project, quest = emitted()
        before = (PROJECT, ENTRY)
        with self.assertRaises(ValueError):
            register(PROJECT, ENTRY, project, quest, PATH, group='Main')
        self.assertEqual((PROJECT, ENTRY), before)

    def test_souls_are_declared_and_marker_reuses_the_alias(self):
        m = with_people()
        project, quest = emitted(m)
        p, _, q, report = register(PROJECT, ENTRY, project, quest, PATH, model=m,
                                   souls={SID: 'gm_soul_rat_refugee_ales'}, group='Side-Activity')
        assets = E.fromstring(p).findall('Skald/Project/Assets/SoulAsset')
        self.assertEqual([(a.get('Name'), a.get('SharedSoulGuids')) for a in assets],
                         [('gm_soul_rat_refugee_ales', SID)])
        self.assertEqual(report['soul_assets'], ['gm_soul_rat_refugee_ales'])
        self.assertEqual([(c['objective'], c['marker']) for c in report['markers']['converted']],
                         [('first', 'gm_soul_rat_refugee_ales')])
        log = E.fromstring(q).find(".//Objective[@Name='first']/Logs/EnumLog[@Type='Started']")
        self.assertEqual(log.get('Marker'), 'gm_soul_rat_refugee_ales')

    def test_existing_soul_alias_with_same_guid_is_reused(self):
        m = with_people()
        project, quest = emitted(m)
        base = PROJECT.replace(b'<Assets/>', ('<Assets><SoulAsset Name="existing" SharedSoulGuids="%s"/></Assets>' % SID).encode())
        p, _, q, report = register(base, ENTRY, project, quest, PATH, model=m, souls={SID: 'gm_soul_new'})
        self.assertEqual(len(E.fromstring(p).findall('Skald/Project/Assets/SoulAsset')), 1)
        self.assertEqual(report['soul_assets'], [])
        self.assertIn(b'Marker="existing"', q)

    def test_soul_alias_used_by_another_soul_is_refused(self):
        project, quest = emitted()
        base = PROJECT.replace(b'<Assets/>', b'<Assets><SoulAsset Name="gm_soul_a" SharedSoulGuids="other"/></Assets>')
        with self.assertRaisesRegex(ValueError, 'alias already used'):
            register(base, ENTRY, project, quest, PATH, souls={SID: 'gm_soul_a'})

    def test_unregistered_soul_gets_no_marker(self):
        m = with_people()
        project, quest = emitted(m)
        _, _, q, report = register(PROJECT, ENTRY, project, quest, PATH, model=m)
        self.assertEqual(report['markers']['converted'], [])
        self.assertNotIn(b'Marker=', q)


if __name__ == '__main__': unittest.main()
