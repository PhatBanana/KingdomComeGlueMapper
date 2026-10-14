import sys
from pathlib import Path
import unittest
import xml.etree.ElementTree as ET

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from campaign_actor_dialogues import discover, role_bindings, register_roles, remap_roles, actor_branches, required_actor_souls
from build_actor_dialogues_test import actor_voice_bindings, actor_ui_name


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
    def test_required_souls_include_connected_silent_participants_and_reject_ambiguity(self):
        t=tables()
        _,models=discover(t,['abc'])
        self.assertEqual(required_actor_souls(list(models.values()),t['soul2role'],t['role'],t['metarole']),
                         {'12':'abc','13':'def'})
        t['soul2role'].append(dict(soul_id='different_person',role_id='13'))
        self.assertEqual(required_actor_souls(list(models.values()),t['soul2role'],t['role'],t['metarole'],{'abc','def'}),{'12':'abc','13':'def'})
        with self.assertRaisesRegex(ValueError,'ambiguous dialogue actor'):
            required_actor_souls(list(models.values()),t['soul2role'],t['role'],t['metarole'])

    def test_actor_scope_uses_memberships_not_labels_or_topic_numbers(self):
        closure = dict(branches=[
            dict(source=dict(start_topic='901'), topic=dict(label=''), participants=[dict(role_id='12')]),
            dict(source=dict(start_topic='4'), topic=dict(label='arbitrary_worker'), participants=[dict(role_id='13')])])
        selected = actor_branches(closure, tables()['soul2role'], ['ABC'])
        self.assertEqual([b['source']['start_topic'] for b in selected], ['901'])
        self.assertEqual(len(closure['branches']), 2)
        with self.assertRaisesRegex(ValueError, 'Missing source'):
            actor_branches(closure, tables()['soul2role'], ['missing'])

    def test_voice_registration_reuses_actor_display_name_and_rejects_ambiguous_rules(self):
        rule = b'<storm><rules><rule><selectors><hasName name="worker"/></selectors><operations><setUiName name="worker_original"/></operations></rule></rules></storm>'
        resources = {'Libs/Storm/names/person.xml': rule}
        self.assertEqual(actor_ui_name(resources, 'worker'), 'worker_original')
        resources['Libs/Storm/names/conflict.xml'] = rule.replace(b'worker_original', b'wrong_name')
        with self.assertRaisesRegex(ValueError, 'ambiguous'):
            actor_ui_name(resources, 'worker')

    def test_recorded_voice_registers_source_actor_without_player_override(self):
        bindings = {'actor': [dict(role_name='WORKER')]}
        voice = dict(voice_id='7', voice_technical_name='originalSpeaker')
        reports = [dict(binding=dict(roles={'imported_worker': voice, 'HENRY': dict(voice_id='108')}))]
        self.assertEqual(actor_voice_bindings(bindings, {'WORKER': 'imported_worker'}, reports),
                         {'actor': dict(role='imported_worker', voice=voice)})

    def test_conflicting_actor_voices_are_not_silently_overwritten(self):
        bindings = {'actor': [dict(role_name='WORKER'), dict(role_name='NEIGHBOR')]}
        reports = [dict(binding=dict(roles={'a': dict(voice_id='7'), 'b': dict(voice_id='8')}))]
        with self.assertRaisesRegex(ValueError, 'Conflicting recorded voices for soul'):
            actor_voice_bindings(bindings, {'WORKER': 'a', 'NEIGHBOR': 'b'}, reports)

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
