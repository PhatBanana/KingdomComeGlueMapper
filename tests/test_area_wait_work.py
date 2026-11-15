from pathlib import Path
import sys
import unittest
from unittest.mock import patch
import xml.etree.ElementTree as E

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'tools'))
import character_area_wait_work as work
import character_work_adapters as registry
from character_schedule_world import ARRIVAL_TEMPLATE

LOOP = '''<While condition="&quot;$t_timeChanged == false&quot;"><Wait duration="&quot;5m&quot;"
  timeType="&quot;WorldTime&quot;" doFail="&quot;false&quot;" variation="&quot;&quot;" skipInLOD="&quot;false&quot;"/></While>'''
WAIT = '<BehaviorTree name="Wait"><Root><Behavior><LODGuardian><LOD>'+LOOP+'</LOD><Detail>'+LOOP+'''</Detail>
  </LODGuardian></Behavior></Root><EditorData><Root><Behavior><LODGuardian/></Behavior></Root></EditorData></BehaviorTree>'''
WRAPPER = '''<BehaviorTree name="goToSmartArea"><Root><Behavior><Sequence>
  <IfCondition condition="&quot;$p_phase &lt; 5000 &amp; $t_behaviorData.moveToArea == true&quot;"><Sequence>
    <GraphSearch Origin="&quot;t_behavior.areaId&quot;" SubGraph="&quot;inside&quot;"/>
    <Expression expressions="&quot;$t_distanceMove_params.target = $t_behavior.areaId &#10;$t_distanceMove_params.outsideAreaOnly = $t_behaviorData.moveToOutside&quot;"/>
    <IncludeTree File="&quot;final/moveUtils.xml&quot;" Name="&quot;distanceMove&quot;"/>
  </Sequence></IfCondition></Sequence></Behavior></Root></BehaviorTree>'''
MOVE = '''<BehaviorTree name="distanceMove"><Root><Behavior><Move destinationSpecification="&quot;t_destination&quot;"
  stopWithinDistance="&quot;$t_distanceMove_params.distance&quot;" rayCasteFlee="&quot;true&quot;"
  stopDistanceVariation="&quot;$t_distanceMove_params.variation&quot;"
  successDistance="&quot;$t_distanceMove_params.successDist&quot;"/></Behavior></Root></BehaviorTree>'''
TYPES = '''<TypeDefinitions><Type name="distanceMove_params"><member name="speed">$enum:movementSpeed.walk</member>
  <member name="exact">false</member><member name="distance">0.2</member><member name="variation">0.1</member>
  <member name="successDist">5</member></Type><Type name="daycycle"><Type name="behavior"><Type name="data">
  <Member name="moveToArea">true</Member><Member name="moveToOutside">false</Member></Type></Type></Type></TypeDefinitions>'''
MOVEMENT = dict(stopWithinDistance='0.2', stopDistanceVariation='0.1', successDistance='5', speed='Walk', rayCasteFlee='true')
WAITING = dict(duration='5m', timeType='WorldTime', doFail='false', variation='', skipInLOD='false')


def tree(text):
    return E.fromstring(text)


def entry(name='Wait', file='final/emptyWork.xml'):
    return dict(behavior=dict(tree_file=file, tree_name=name, sa_behaviour_tag_name='Wait'),
                binding=dict(sa_smart_area_id='area-template'), area=dict(EntityId='1', Name='area'),
                target_links=[dict(TargetId='5', Name='inside'), dict(TargetId='6', Name='outside')],
                target_kind='smart_area', start_minute=480, end_minute=720)


class RecognitionTests(unittest.TestCase):
    def test_claims_by_tree_identity_only(self):
        self.assertTrue(work.supports(entry()))
        self.assertFalse(work.supports(entry('DummyWait')))
        self.assertFalse(work.supports(entry(file='final/sa_home.xml')))
        self.assertFalse(work.supports(dict(entry(), target_kind='quest_controller')))

    def test_wait_requires_identical_time_change_loops(self):
        self.assertEqual(work.recognize_wait(tree(WAIT)), WAITING)
        self.assertIsNone(work.recognize_wait(tree(WAIT.replace('$t_timeChanged == false', 'true', 1))))
        self.assertIsNone(work.recognize_wait(tree(WAIT.replace('5m', '2s', 1))))
        self.assertIsNone(work.recognize_wait(tree(WAIT.replace('<LOD>'+LOOP, '<LOD><Sequence/>'))))
        self.assertIsNone(work.recognize_wait(tree(WAIT.replace('&quot;5m&quot;', '&quot;-1&quot;'))))

    def test_move_values_come_from_source_defaults(self):
        self.assertEqual(work.recognize_move(tree(WRAPPER), tree(MOVE), tree(TYPES)), MOVEMENT)
        with self.assertRaisesRegex(ValueError, 'defaults changed'):
            work.recognize_move(tree(WRAPPER), tree(MOVE), tree(TYPES.replace('>true<', '>false<')))
        with self.assertRaisesRegex(ValueError, 'distanceMove'):
            work.recognize_move(tree(WRAPPER.replace('distanceMove&quot;', 'other&quot;')), tree(MOVE), tree(TYPES))
        with self.assertRaisesRegex(ValueError, 'target changed'):
            work.recognize_move(tree(WRAPPER.replace('= $t_behavior.areaId', '= $home')), tree(MOVE), tree(TYPES))

    def test_data_tree_overrides(self):
        data = '<BehaviorTree><Root><Behavior><Expression expressions="&quot;{}&quot;"/></Behavior></Root></BehaviorTree>'
        self.assertEqual(work.data_overrides(tree(data.format('$t_behaviorData.moveToArea = false'))), dict(moveToArea=False))
        self.assertEqual(work.data_overrides(tree(data.format('t_behaviorData.moveToOutside = true'))), dict(moveToOutside=True))
        self.assertEqual(work.data_overrides(tree(data.format("$t_behaviorData.clothes.clothesType = 'normal',"))), {})


class ResolveTests(unittest.TestCase):
    def resolve(self, overrides, work_tree=WAIT):
        roots = dict(work=tree('<BehaviorTrees>'+work_tree+'</BehaviorTrees>'), wrapper=tree('<B>'+WRAPPER+'</B>'),
                     move=tree('<B>'+MOVE+'</B>'), types=tree(TYPES))
        points = {'5': E.Element('Entity', EntityId='5', EntityClass='TagPoint', Name='in'),
                  '6': E.Element('Entity', EntityId='6', EntityClass='TagPoint', Name='out')}
        with patch.object(work, 'source_trees', return_value=roots), \
             patch.object(work, 'area_data', return_value=overrides), \
             patch.object(work, 'read', return_value='<Objects/>'), \
             patch.object(work, 'resolve_link_targets', side_effect=lambda a, area, e, p: list(points.values())), \
             patch.object(work, 'world_entity', side_effect=lambda a, e, es: e):
            return work.resolve(entry(), None, 'src', 'reader')

    def test_default_area_walks_to_inside_point(self):
        result = self.resolve({})
        self.assertEqual(result['arrival']['EntityId'], '5')
        self.assertEqual(result['area_wait_work'], dict(movement=MOVEMENT, wait=WAITING))

    def test_outside_request_uses_outside_point(self):
        self.assertEqual(self.resolve(dict(moveToOutside=True))['arrival']['EntityId'], '6')

    def test_area_without_move_or_changed_tree_is_a_contract_failure(self):
        with self.assertRaisesRegex(ValueError, 'does not move'):
            self.resolve(dict(moveToArea=False))
        with self.assertRaisesRegex(ValueError, 'Unsupported source area wait'):
            self.resolve({}, WAIT.replace('$t_timeChanged == false', 'true'))


class ProgramTests(unittest.TestCase):
    contract = dict(movement=MOVEMENT, wait=WAITING)

    def test_program_repeats_source_move_and_wait(self):
        template, files = work.resources(self.contract)
        table, program = (E.fromstring(files[k]) for k in sorted(files, reverse=True))
        definition = table.find('.//SmartEntityTemplate')
        self.assertEqual(definition.get('DatabaseId'), template)
        location = definition.find('.//TreeLocation')
        self.assertIn('AI/'+location.get('FileName'), files)
        nodes = list(program.find('.//Sequence'))
        self.assertEqual([n.tag for n in nodes], ['Move', 'WaitAction', 'Wait'])
        self.assertEqual((nodes[0].get('destinationSpecification'), nodes[0].get('successDistance')), ('$__object.id', '5'))
        self.assertEqual((nodes[2].get('duration'), nodes[2].get('timeType')), ("'5m'", 'WorldTime'))
        other, _ = work.resources(dict(self.contract, wait=dict(WAITING, duration='2s')))
        self.assertNotEqual(template, other)
        self.assertEqual(template, work.resources(dict(self.contract))[0])

    def mission(self, template=ARRIVAL_TEMPLATE):
        mission = E.Element('Objects')
        job = E.SubElement(mission, 'Entity', Name='gm_schedule_p_5', EntityGuid='{J}')
        E.SubElement(job, 'Properties', guidSmartObjectType=template)
        return mission

    def bound(self):
        return dict(entry(), arrival=dict(EntityId='5', EntityGuid='{A}'), area_wait_work=self.contract)

    def test_bind_only_retargets_an_importer_owned_arrival(self):
        mission = self.mission()
        job, links, report = work.bind(mission, None, 'p', self.bound(), None)
        template, _ = work.resources(self.contract)
        self.assertEqual(job.find('Properties').get('guidSmartObjectType'), template)
        self.assertEqual((links, report['interval'], report['pending']), ([], [480, 720], []))
        work.bind(mission, None, 'p', self.bound(), None)
        with self.assertRaisesRegex(ValueError, 'importer-owned'):
            work.bind(self.mission('native'), None, 'p', self.bound(), None)

    def test_registry_publishes_only_used_programs(self):
        template, files = work.resources(self.contract)
        schedules = dict(p=[self.bound(), dict(entry(), arrival={})])
        self.assertEqual(registry.resources(schedules, {template}).keys(), files.keys())
        self.assertEqual(registry.resources(schedules, {'other'}), {})
        self.assertEqual(registry.adapter_for(entry())[0].key, 'area_wait_work')


if __name__ == '__main__':
    unittest.main()
