from pathlib import Path
import sys
import unittest
import xml.etree.ElementTree as E
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from campaign_quest_people import bind_markers, dependencies

SID = '41315647-d7e3-98de-b434-338e04c51bb6'
PROJECT = b'<Database><Skald><Project Name="test"><Assets /></Project></Skald></Database>'
QUEST = b'<Database><Skald><Quest Name="test"><Objectives><Objective Name="talk"><Logs><EnumLog Type="Started"/><EnumLog Type="Completed"/></Logs></Objective></Objectives></Quest></Skald></Database>'


def model():
    return dict(quest='test', quest_id='1', tables=dict(
        quest_npc=dict(rows=[dict(quest_id='1', quest_asset_id='2', soul_id=SID)]),
        quest_objective=dict(rows=[dict(objective_id='3', objective_name='talk')]),
        quest_tracked_asset=dict(rows=[dict(quest_id='1', objective_id='3', quest_asset_id='2',
                                          on_map='True', pos='-1020,-560,0')])) )


class QuestPeopleTests(unittest.TestCase):
    def test_unregistered_soul_cannot_get_marker(self):
        p, q, r = bind_markers(PROJECT, QUEST, model(), set())
        self.assertFalse(r['converted']); self.assertEqual(len(r['pending']), 1)
        self.assertNotIn(b'Marker=', q)

    def test_marker_tracks_soul_and_only_active_log(self):
        p, q, r = bind_markers(PROJECT, QUEST, model(), {SID})
        asset = E.fromstring(p).find('.//SoulAsset')
        logs = E.fromstring(q).findall('.//EnumLog')
        self.assertEqual(asset.get('SharedSoulGuids'), SID)
        self.assertEqual(logs[0].get('Marker'), asset.get('Name'))
        self.assertIsNone(logs[1].get('Marker'))
        self.assertNotIn(b'-1020', p + q)
        p2, q2, _ = bind_markers(p, q, model(), {SID})
        self.assertEqual(p, p2); self.assertEqual(q, q2)

    def test_reuses_existing_actor_asset(self):
        p = PROJECT.replace(b'<Assets />', f'<Assets><SoulAsset Name="existing" SharedSoulGuids="{SID}"/></Assets>'.encode())
        result, q, _ = bind_markers(p, QUEST, model(), {SID})
        self.assertEqual(len(E.fromstring(result).findall('.//SoulAsset')), 1)
        self.assertIn(b'Marker="existing"', q)

    def test_hidden_marker_and_wrong_quest(self):
        m = model(); m['tables']['quest_tracked_asset']['rows'][0]['on_map'] = 'False'
        self.assertFalse(bind_markers(PROJECT, QUEST, m, {SID})[2]['converted'])
        m['tables']['quest_npc']['rows'][0]['quest_id'] = '2'
        with self.assertRaises(ValueError): dependencies(m)

    def test_npc_filters_are_not_silently_dropped(self):
        m = model(); m['tables']['quest_npc']['rows'][0]['soul_faction_id'] = '8'
        _, q, r = bind_markers(PROJECT, QUEST, m, {SID})
        self.assertFalse(r['converted']); self.assertNotIn(b'Marker=', q)


if __name__ == '__main__': unittest.main()
