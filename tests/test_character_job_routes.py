import copy
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
import xml.etree.ElementTree as E

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from character_job_routes import bind_points, native_approach, FIRST, NEXT
from character_sweeping_routes import resources, upgrade_installed, TEMPLATE, bind
from test_character_work_paths import graph


NATIVE = b'''<BehaviorTrees><BehaviorTree name="use"><Variables/>
<Root><Behavior><HandContentElement hand="Right" decisionLabel="tavern_broom"><Exec>
<EntityContextElement context="speech_readyForSwitchDialog"><EntityContextElement context="ForceForbidAutoTorch">
<Sequence><HandCheck RightHand="$right"/>
<IfElseCondition condition="$right ~= $broom"><Then><Move destinationSpecification="$__object.id" destinationSpecification2="" pathFindingParams="" speed="Walk"/></Then>
<Else><DistanceCondition ReferencePt="$__object.id"><Move destinationSpecification="$__object.id" destinationSpecification2="" pathFindingParams="" speed="Walk"/></DistanceCondition></Else></IfElseCondition>
<UnstanceAction unstance="sweeping"/><Wait duration="'5s'"/>
</Sequence></EntityContextElement></EntityContextElement></Exec></HandContentElement></Behavior></Root>
</BehaviorTree></BehaviorTrees>'''


class JobRouteTests(unittest.TestCase):
    def test_existing_job_upgrade_is_generic_preserves_world_and_repeats(self):
        mission = E.fromstring('<Objects><Entity Name="unrelated" EntityId="8"/>'
            '<Entity Name="arbitrary_job" EntityId="9" EntityGuid="00000099-0000-0000">'
            '<Properties guidSmartObjectType="'+TEMPLATE+'"/><EntityLinks>'
            '<Link Name="SweepingPath" TargetGuid="0000007b-0000-0000" TargetId="10"/>'
            '</EntityLinks></Entity><Entity Name="arbitrary_route" EntityId="10" EntityGuid="0000007b-0000-0000"/></Objects>')
        originals = [E.tostring(n) for n in mission]
        files = {'objects_mission0.xml': E.tostring(mission),
                 'waitinglinks.xml': b'<StaticLinksInfo version="1"><WaitingLinks/></StaticLinksInfo>',
                 'ubernav.tmm': b'preserve native navigation', 'other': b'preserve'}
        updated, report = upgrade_installed(files, graph())
        self.assertEqual(updated, upgrade_installed(updated, graph())[0])
        self.assertEqual(updated['ubernav.tmm'], files['ubernav.tmm'])
        self.assertEqual(updated['other'], files['other'])
        self.assertEqual(report['jobs'][0]['job'], 'arbitrary_job')
        self.assertEqual(len(E.fromstring(updated['objects_mission0.xml'])), 5)
        self.assertEqual([E.tostring(n) for n in mission], originals)
        self.assertIn(b'gm_work_first', updated['waitinglinks.xml'])
        broken=copy.deepcopy(files)
        broken['objects_mission0.xml']=broken['objects_mission0.xml'].replace(b'TargetId="10"',b'TargetId="999"')
        with self.assertRaisesRegex(ValueError, 'unresolved'):
            upgrade_installed(broken, graph())

    def test_clean_conversion_does_not_require_legacy_target_navigation(self):
        mission=E.fromstring('<Objects><Entity EntityId="1" EntityGuid="00000099-0000-0000"><Properties/></Entity></Objects>')
        source=E.fromstring('<Entity EntityClass="PredefinedNavigationPath" EntityGuid="000000000000007B" Name="route" Pos="1,2,3"/>')
        edges, report=bind(mission,mission[0],[source],graph(),b'different native navigation')
        self.assertEqual(len(edges),3)
        self.assertFalse(report['graph']['target_navigation_modified'])

    def test_ordered_points_are_stable_and_do_not_merge_other_routes(self):
        mission = E.fromstring('<Objects><Entity EntityGuid="one" EntityId="1"/></Objects>')
        route = mission[0]
        points = [(1., 2., 3.), (4., 5., 6.), (7., 8., 9.)]
        edges = bind_points(mission, route, points)
        before = E.tostring(mission)
        self.assertEqual(edges, bind_points(mission, route, points))
        self.assertEqual(before, E.tostring(mission))
        by_guid = {n.get('EntityGuid'): n for n in mission}
        current = route
        for index, point in enumerate(points):
            link = current.find("EntityLinks/Link[@Name='" + (FIRST if index == 0 else NEXT) + "']")
            current = by_guid[link.get('TargetGuid')]
            self.assertEqual(tuple(map(float, current.get('Pos').split(','))), point)
        self.assertIsNone(current.find('EntityLinks'))
        second = E.SubElement(mission, 'Entity', EntityGuid='two', EntityId='10')
        other = bind_points(mission, second, points)
        self.assertTrue({e[1] for e in edges}.isdisjoint(e[1] for e in other))

    def test_invalid_coordinates_and_changed_existing_points_are_rejected(self):
        mission = E.fromstring('<Objects><Entity EntityGuid="one" EntityId="1"/></Objects>')
        before = E.tostring(mission)
        with self.assertRaises(ValueError):
            bind_points(mission, mission[0], [(0,0,0),(float('nan'),0,0)])
        self.assertEqual(before, E.tostring(mission))
        bind_points(mission, mission[0], [(0,0,0),(1,0,0)])
        with self.assertRaisesRegex(ValueError, 'differs from source'):
            bind_points(mission, mission[0], [(0,0,0),(2,0,0)])

    def test_native_hand_checks_and_approach_guards_are_preserved(self):
        sequence = E.fromstring(NATIVE).find('.//Sequence')
        before = E.tostring(sequence)
        nodes = native_approach(sequence, '$point')
        self.assertEqual([n.tag for n in nodes], ['HandCheck', 'IfElseCondition'])
        self.assertEqual(nodes[1].find('.//DistanceCondition').get('ReferencePt'), '$point')
        self.assertTrue(all(n.get('destinationSpecification') == '$point' for n in nodes[1].iter('Move')))
        self.assertEqual(before, E.tostring(sequence))
        sequence.find('.//Move').set('destinationSpecification2', '$predefined')
        with self.assertRaisesRegex(ValueError, 'movement contract'):
            native_approach(sequence, '$point')

    def test_sweeping_uses_native_approach_with_failure_propagation_not_tracks(self):
        source = b'''<BehaviorTrees><BehaviorTree name="sweeping"><Variables><Variable name="lodWaitingTime" values="5"/></Variables><Root>
        <While condition="$lodWaitingTime &gt; 0"><Sequence><Wait duration="6s" timeType="GameTime"/><Expression expressions="$lodWaitingTime -= 1"/></Sequence></While>
        </Root></BehaviorTree></BehaviorTrees>'''
        table = b'<database><SmartEntitys><SmartEntityTemplate><BehaviorTemplates><SmartBehaviorTemplate><TreeLocation/></SmartBehaviorTemplate></BehaviorTemplates></SmartEntityTemplate></SmartEntitys></database>'
        blobs = {'Libs/AI/final/so_broom.xml': source, 'AI/world/so_sweeping.xml': NATIVE,
                 'Libs/Tables/ai/smartEntity/SmartEntity__so_sweeping.xml': table}
        with patch('character_sweeping_routes.zipfile.ZipFile'), patch('character_sweeping_routes.read', side_effect=lambda z,n: blobs[n]):
            files, report = resources(Path('source'), Path('native'))
        root = E.fromstring(files['AI/gluemapper/sweeping_route.xml'])
        self.assertFalse(root.findall(".//Variable[@type='predefinedPathParams']"))
        self.assertEqual(len(root.findall('.//HandCheck')), 2)
        self.assertTrue(all(n.get('destinationSpecification') == '$workPoint' and not n.get('destinationSpecification2') for n in root.iter('Move')))
        loop = root.find('.//While')
        self.assertEqual(loop.get('propagateChildFail'), 'true')
        self.assertEqual(loop.find('.//GraphSearch').get('failOnEmpty'), 'false')
        self.assertIsNotNone(loop.find('.//SuppressFailure/GraphSearch'))
        self.assertEqual([n.get('duration') for n in root.iter('Wait')], ["'30s'", "'30s'"])
        self.assertEqual(root.find('.//HandContentElement').get('decisionLabel'), 'tavern_broom')
        self.assertFalse(report['runtime_verified'])


if __name__ == '__main__': unittest.main()
