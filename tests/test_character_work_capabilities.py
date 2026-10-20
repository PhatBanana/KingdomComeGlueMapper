import sys
from pathlib import Path
import unittest
import xml.etree.ElementTree as E
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from character_work_capabilities import housework_phases, repair_housework_bindings
from character_sweeping_routes import TEMPLATE
from character_schedule_world import ARRIVAL_TEMPLATE
from campaign_entity_links import native_guid


def source():
    tree = E.fromstring('<BehaviorTree><Root><OnInit><Sequence>'
        '<IfElseCondition><Then/><Else/></IfElseCondition>'
        '</Sequence></OnInit></Root></BehaviorTree>')
    select = tree.find('.//IfElseCondition')
    select.set('condition', '"$b_soul.gender == $enum:humanGender.female"')
    E.SubElement(select.find('Then'), 'Expression',
        expressions="$houseworks[0].name = 'Cooking', $houseworks[1].name = 'houseSweeping'")
    E.SubElement(select.find('Else'), 'Expression',
        expressions="$houseworks[0].name = 'repair_home_fence', $houseworks[1].name = 'hangingOut'")
    return tree


class WorkCapabilitiesTests(unittest.TestCase):
    def test_migration_changes_only_owned_incompatible_job_and_is_idempotent(self):
        actor, job = native_guid(1), native_guid(2)
        files = {
            'objects_mission0.xml': (
                f'<Objects><Entity Name="arbitrary" EntityClass="NPC" EntityGuid="{actor}"/>'
                f'<Entity Name="gm_schedule_arbitrary_77" EntityClass="SmartObjectHolder" EntityGuid="{job}">'
                f'<Properties guidSmartObjectType="{TEMPLATE}"/></Entity></Objects>').encode(),
            'tables/ai/scheduler.xml': b'<Root><Schedulers><C_NPC EntityGuid="1"><Links>'
                b'<S_ActivityLink TargetGuid="2"><Parameters BehaviorName="use" TimeOfDayStart="300" '
                b'TimeOfDayEnd="900"/></S_ActivityLink></Links></C_NPC></Schedulers></Root>',
            'waitinglinks.xml': b'<preserve/>'}
        schedules = {'arbitrary': [dict(behavior=dict(tree_file='final/sa_home.xml', tree_name='housework'),
                                       arrival=dict(EntityId='77'))]}
        with patch('character_work_capabilities.allowed_housework', return_value=['hangingOut']):
            result, report = repair_housework_bindings(files, schedules, None)
            again, second = repair_housework_bindings(result, schedules, None)
        self.assertEqual(result, again)
        self.assertEqual(second, [])
        self.assertEqual(result['tables/ai/scheduler.xml'], files['tables/ai/scheduler.xml'])
        self.assertEqual(result['waitinglinks.xml'], files['waitinglinks.xml'])
        self.assertEqual(E.fromstring(result['objects_mission0.xml']).find('.//Properties').get(
            'guidSmartObjectType'), ARRIVAL_TEMPLATE)
        self.assertEqual(report[0]['pending'], ['hangingOut'])
        with patch('character_work_capabilities.allowed_housework', return_value=['houseSweeping']):
            self.assertEqual(repair_housework_bindings(files, schedules, None), (files, []))
        shared = dict(files, **{'tables/ai/scheduler.xml':
            files['tables/ai/scheduler.xml'].replace(b'EntityGuid="1"', b'EntityGuid="3"')})
        with patch('character_work_capabilities.allowed_housework', return_value=['hangingOut']):
            with self.assertRaisesRegex(ValueError, 'unexpected owners'):
                repair_housework_bindings(shared, schedules, None)

    def test_source_selector_excludes_sweeping_for_male_actors(self):
        tree = source()
        self.assertEqual(housework_phases(tree, 'NPC'), ['repair_home_fence', 'hangingOut'])
        self.assertEqual(housework_phases(tree, 'NPC_Female'), ['Cooking', 'houseSweeping'])

    def test_changed_or_ambiguous_selector_is_not_guessed(self):
        tree = source()
        tree.find('.//IfElseCondition').set('condition', '$someOtherCondition')
        with self.assertRaises(ValueError):
            housework_phases(tree, 'NPC')
        with self.assertRaises(ValueError):
            housework_phases(source(), 'SomeOtherActor')
        tree = source()
        tree.find('.//Else/Expression').set('expressions', "$houseworks[2].name = 'x'")
        with self.assertRaises(ValueError):
            housework_phases(tree, 'NPC')
