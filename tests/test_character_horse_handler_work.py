import copy
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
import xml.etree.ElementTree as E
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
import character_horse_handler_work as stable
from character_schedule_jobs import bind_jobs, population_work_supports, job_resources
import test_character_city_work as fixture


PROGRAM = b'''<BehaviorTrees><BehaviorTree name="horseHandler_work"><Root>
<Expression expressions="$behaviors[1] = 'unloadHay'"/>
<GraphSearch Origin="__area.id" depth="1"><HasBehaviorFilter Child="activityTarget"/></GraphSearch>
</Root></BehaviorTree></BehaviorTrees>'''


class HorseHandlerTests(unittest.TestCase):
    def test_start_pose_composes_native_alignment_with_rotated_cart(self):
        from math import sqrt
        animation=dict(init_align0='1;3;0.2;0;0;0;1')
        result=stable.work_contact(dict(Pos='10,20,4',Rotate=f'{sqrt(.5)},0,0,{sqrt(.5)}'),animation)
        for actual,expected in zip(map(float,result['Pos'].split(',')),(7,21,4.2)):
            self.assertAlmostEqual(actual,expected)
        self.assertEqual(result['Rotate'],f'{sqrt(.5):.9g},0,0,{sqrt(.5):.9g}')
        for bad in ('0;0;0', 'nan;0;0;0;0;0;1', '0;0;0;0;0;0;0'):
            with self.assertRaises(ValueError):
                stable.work_contact(dict(Pos='0,0,0'),dict(init_align0=bad))

    def prepared(self):
        files, schedules = fixture.CityWorkTests().prepared()
        for entry in schedules['person']:
            entry.pop('city_work')
            entry['behavior'] = dict(tree_file=stable.SOURCE[0], tree_name=stable.SOURCE[1])
            entry['horse_handler_work'] = dict(cart=dict(EntityGuid='AB'), alignment=dict(Pos='4,5,6',Rotate='1,0,0,0'), fork=
                '<Entity EntityClass="ItemSlot" EntityId="99" EntityGuid="FF" Pos="1,2,3"><Properties guidItemClassId="' + stable.FORK + '"/></Entity>')
        return files, schedules

    def bind(self, files, schedules, registered=None):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'source.pak'
            with zipfile.ZipFile(path, 'w') as z:
                z.writestr('objects_mission0.xml', '<Objects/>')
            with zipfile.ZipFile(path) as z, patch.object(stable, 'native_fragments'):
                return bind_jobs(files, schedules, z, None,
                                 {stable.FORK: stable.FORK} if registered is None else registered)

    def test_selection_uses_source_behavior(self):
        self.assertTrue(population_work_supports(dict(behavior=dict(tree_file='final\\sa_stable.xml', tree_name='horseHandler_work'))))
        self.assertFalse(stable.supports(dict(behavior=dict(tree_file=stable.SOURCE[0], tree_name='other'))))

    def test_changed_source_search_is_rejected(self):
        stable.source_contract(PROGRAM)
        for blob in (PROGRAM.replace(b'unloadHay', b'other'), PROGRAM.replace(b'depth="1"', b'depth="2"'), PROGRAM.replace(b'__area.id', b'__actor.id')):
            with self.assertRaises(ValueError):
                stable.source_contract(blob)

    def test_same_anchor_multiple_intervals_bind_once(self):
        files, schedules = self.prepared()
        entry = schedules['person'][0]
        schedules['person'].append(copy.deepcopy(entry))
        result, report = self.bind(files, schedules)
        jobs = [r for r in report if r['job'] == 'stable_hay_unloading']
        self.assertEqual(len(jobs), 1)
        self.assertEqual(len(jobs[0]['intervals']), 2)
        self.assertFalse(jobs[0]['runtime_verified'])
        self.assertIn('water refill', jobs[0]['pending'])
        mission = E.fromstring(result['objects_mission0.xml'])
        carts = [e for e in mission if e.get('Name', '').startswith('gm_stable_hay_')]
        self.assertEqual(len(carts), 2)
        carts=[e for e in carts if e.get('EntityClass')=='SmartObjectHolder']
        self.assertEqual(carts[0].get('Pos'),'4,5,6')
        reservations = [l for l in carts[0].findall('EntityLinks/Link') if l.get('Name').startswith('schedulerReservedItem')]
        self.assertEqual(len(reservations), 1)
        self.assertEqual(reservations[0].get('Name'), "schedulerReservedItem['use','stable_pitchfork']")
        resources = job_resources(None, None, result, {})
        self.assertIn('AI/gluemapper/stable_hay.xml', resources)
        labels = E.fromstring(resources['Libs/Tables/ai/DecisionLabelDatabase__gm_stable_hay.xml'])
        self.assertEqual([e.get('Name') for e in labels.iter('DecisionLabel')], ['stable_pitchfork'])

    def test_unregistered_tool_fails(self):
        with self.assertRaisesRegex(ValueError, 'Unregistered job item'):
            self.bind(*self.prepared(), registered={})

    def test_conflicting_intervals_fail(self):
        files, schedules = self.prepared()
        other = copy.deepcopy(schedules['person'][0])
        other['horse_handler_work']['cart']['EntityGuid'] = 'AC'
        schedules['person'].append(other)
        with self.assertRaisesRegex(ValueError, 'Different stables'):
            self.bind(files, schedules)

    def test_native_animation_validation(self):
        with tempfile.TemporaryDirectory() as tmp:
            target=Path(tmp); (target/'Data').mkdir()
            def write(bad=None):
                root=E.Element('AnimDB'); actions=E.Element('database')
                for i,name in enumerate(stable.FRAGMENTS):
                    tags='left+up' if i==1 else ''
                    fragment=E.SubElement(E.SubElement(root,name),'Fragment',FragTags=tags,GUID=str(i))
                    E.SubElement(E.SubElement(fragment,'AnimLayer'),'Animation',name='clip')
                    row=E.SubElement(actions,'actor_anim_action',mn_fragment_id=name,mn_tags=tags,
                        mn_fragment_guid=str(i),player='false',mounted='false',actor_class_hash='native-controller',
                        isfullbody='true',isOneShot='false' if i==1 else 'true',
                        init_align0='0;3;0;0;0;0;1',init_align1='0;3;0;0;0;0;1')
                    if i==0 and bad=='missing':actions.remove(row)
                    if i==0 and bad=='guid':row.set('mn_fragment_guid','unknown')
                    if i==0 and bad=='alignment':row.set('init_align1','1;3;0;0;0;0;1')
                    if i==1 and bad=='loop':row.set('isOneShot','true')
                with zipfile.ZipFile(target/'Data/Animations.pak','w') as z:
                    z.writestr('Animations/Mannequin/ADB/kcd_male_database.adb',E.tostring(root))
                with zipfile.ZipFile(target/'Data/Tables.pak','w') as z:
                    z.writestr('Libs/Tables/action/actor_anim_action.xml',E.tostring(actions))
            write()
            self.assertEqual(stable.native_fragments(target)[stable.FRAGMENTS[0]]['init_align0'],'0;3;0;0;0;0;1')
            for bad in ('missing','guid','alignment','loop'):
                write(bad)
                with self.subTest(bad=bad),self.assertRaises(ValueError):stable.native_fragments(target)

    def test_tool_is_held_during_approach_and_animation(self):
        root = E.fromstring(stable.resources()['AI/gluemapper/stable_hay.xml'])
        hand = root.find('.//HandContentElement')
        self.assertEqual(hand.get('decisionLabel'), 'stable_pitchfork')
        sequence = hand.find('Exec/Sequence')
        self.assertEqual(sequence[0].tag, 'GraphSearch')
        self.assertEqual(sequence[0].find('LinkTagFilter').get('Child'), '$approach')
        self.assertEqual(sequence[1].get('destinationSpecification'), '$approach')
        self.assertEqual(sequence[1].get('directionSpecification'), '$approach')
        actions=list(sequence.iter('AnimationAction'))
        self.assertEqual(actions[1].get('tags'), "'left,up'")
        self.assertTrue(all(a.get('alignObject')=='$__object.id' for a in actions))
        self.assertEqual([a.get('fragment') for a in sequence.iter('AnimationAction')],
                         ["'" + name + "'" for name in stable.FRAGMENTS])


if __name__ == '__main__':
    unittest.main()
