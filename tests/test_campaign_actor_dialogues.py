import sys
from pathlib import Path
import unittest
import xml.etree.ElementTree as ET

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from campaign_actor_dialogues import discover, role_bindings, register_roles, remap_roles


def tables():
    return dict(topic=[dict(topic_id='7', label=''), dict(topic_id='8', label='another')],
                sequence=[dict(sequence_id='70', priority='0', next='8'),
                          dict(sequence_id='80', priority='0', next='7')],
                topic2sequence=[dict(topic_id='7', sequence_id='70'), dict(topic_id='8', sequence_id='80')],
                sequence_line=[], response=[], v_dialogue_commands=[], v_response_wave_file_recorded=[],
                sequence2quest_objective=[], sequence_flowchart=[], dialogue_mood=[], v_topic2subchapter_id=[],
                v_branch=[dict(start_topic='7'), dict(start_topic='8')],
                topictorole=[dict(topic_id='7', role_id='12', metarole_id='2'),
                            dict(topic_id='8', role_id='13', metarole_id='2')],
                role=[dict(role_id='12', role_name='arbitrary_worker', metarole_id='2'),
                      dict(role_id='13', role_name='arbitrary_neighbor', metarole_id='2')],
                metarole=[dict(metarole_id='2', metarole_name='NPC')],
                soul2role=[dict(soul_id='abc', role_id='12'), dict(soul_id='def', role_id='13')])


class ActorDialogueTests(unittest.TestCase):
    def test_role_registration_uses_source_soul_and_isolates_native_campaign(self):
        people, conversations = discover(tables(), ['abc'])
        resources = {'Libs/Storm/storm.xml': b'<storm><tasks><task name="roles"/></tasks></storm>'}
        files, mapping = register_roles(resources, role_bindings(people, conversations),
                                        {'abc': 'actor_from_source'}, [], 'imported_roles')
        rules = ET.fromstring(files['Libs/Storm/roles/imported_roles.xml'])
        self.assertEqual(rules.find('.//hasName').get('name'), 'actor_from_source')
        self.assertEqual(rules.find('.//addRole').get('name'), 'imported_roles_12')
        converted = remap_roles(conversations['7'], mapping)
        self.assertEqual(converted['roles']['12']['role_name'], 'imported_roles_12')
        self.assertEqual(conversations['7']['roles']['12']['role_name'], 'arbitrary_worker')
        with self.assertRaisesRegex(ValueError, 'not registered'):
            register_roles(resources, role_bindings(people, conversations), {}, [], 'imported_roles')

    def test_source_memberships_find_unnamed_branches_and_follow_cycles(self):
        people, conversations = discover(tables(), ['ABC'])
        self.assertEqual(set(conversations), {'7'})
        self.assertEqual(set(conversations['7']['topics']), {'7', '8'})
        self.assertEqual(people['abc']['branches'], [dict(start_topic='7', role_ids=['12'])])
        self.assertEqual(role_bindings(people, conversations)['abc'][0]['role_name'], 'arbitrary_worker')
        self.assertEqual(role_bindings(people, {})['abc'], [])

    def test_no_cross_actor_roles_and_unresolved_memberships_fail(self):
        people, conversations = discover(tables(), ['abc', 'def'])
        self.assertEqual(set(conversations), {'7', '8'})
        self.assertEqual([r['role_id'] for r in role_bindings(people, conversations)['def']], ['13'])
        with self.assertRaisesRegex(ValueError, 'Missing source dialogue roles'):
            discover(tables(), ['unknown'])
        source = tables()
        source['soul2role'][0]['role_id'] = 'missing'
        with self.assertRaisesRegex(ValueError, 'Unresolved source dialogue role'):
            discover(source, ['abc'])


if __name__ == '__main__': unittest.main()
