import math
from pathlib import Path
import struct
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import patch
import xml.etree.ElementTree as E

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from character_work_paths import PATH_WUID, read_paths, bind_path, validate_graph
from campaign_dependency_adapters import EntityAdapter
from campaign_trigger_areas import write_areas
from campaign_dependencies import DependencyImporter, ImportPlan


def graph(points=((1., 2., 3.), (4., 5., 6.)), guid=123):
    return (struct.pack('<I', 38) + b'other navigation sections' + struct.pack('<I', 1)
            + struct.pack('<QQfI', PATH_WUID, guid, .2, len(points))
            + b''.join(struct.pack('<3f', *p) for p in points))


class WorkPathTests(unittest.TestCase):
    def test_campaign_registration_waits_for_navigation_dependency(self):
        class Navigation:
            def plan(self, identity):
                return ImportPlan()
            def convert(self, identity, plan, registered):
                return 'source-world', {'world/navigation/ubernav.tmm': graph()}, {}
        world = dict(entities={'route': dict(source='source-layer', attributes=dict(
            Name='route', Pos='1,2,3', EntityGuid='000000000000007B',
            EntityClass='PredefinedNavigationPath', Layer='source-profile'))})
        navigation = SimpleNamespace(level='source', target_level='native', identity='world')
        adapter = EntityAdapter(world, E.fromstring('<Root/>'), write_areas([], 1), 1, navigation=navigation)
        identity = '0000007b-0000-0000'
        with patch('campaign_dependency_adapters.read', return_value=graph()):
            importer = DependencyImporter({'entities': adapter})
            self.assertIsNone(importer.ensure('entities', identity))
            self.assertFalse(importer.files)
            importer = DependencyImporter({'entities': adapter, 'navigation_base': Navigation()})
            self.assertEqual(importer.ensure('entities', identity), identity)
        e = E.fromstring(importer.files['world/entities/' + identity + '.xml'])
        self.assertEqual(e.get('EntityClass'), 'PredefinedNavigationPath')
        self.assertIsNone(e.get('EntityId'))
        self.assertEqual(e.get('EditorLayer'), 'KDC1/source-profile')
        self.assertEqual(importer.files['world/navigation/ubernav.tmm'], graph())

    def test_preserves_order_radius_and_guid_without_resampling(self):
        points = ((7., 5., 3.), (4., 2., 0.), (1., 8., 6.))
        result = read_paths(graph(points))
        self.assertEqual(result[123]['points'], list(points))
        self.assertAlmostEqual(result[123]['radius'], .2)
        self.assertEqual(result[123]['wuid'], PATH_WUID)

    def test_rejects_partial_invalid_or_wrong_version_graph(self):
        b = graph()
        for data in (b[:-1], b + b'extra', struct.pack('<I', 39) + b[4:],
                     graph(((math.nan, 2., 3.), (4., 5., 6.))),
                     graph(guid=0), graph(((1., 2., 3.),))):
            with self.subTest(data=data[:20]), self.assertRaises(ValueError):
                read_paths(data)

    def test_requires_exact_installed_graph_not_only_matching_version(self):
        paths, evidence = validate_graph(graph(), graph())
        self.assertEqual(evidence['route_count'], 1)
        self.assertIn(123, paths)
        with self.assertRaises(ValueError):
            validate_graph(graph(), graph(guid=124))

    def test_binding_reuses_source_identity_and_refuses_wrong_start(self):
        mission = E.fromstring('<Objects><Entity EntityId="22"/></Objects>')
        source = E.fromstring('<Entity EntityClass="PredefinedNavigationPath" EntityGuid="000000000000007B"'
                              ' Name="arbitrary_route" Pos="1,2,3"/>')
        entity, report = bind_path(mission, source, read_paths(graph()))
        self.assertEqual(entity.get('EntityGuid'), '0000007b-0000-0000')
        self.assertEqual(entity.get('EntityId'), '23')
        self.assertEqual(report['point_count'], 2)
        self.assertIs(bind_path(mission, source, read_paths(graph()))[0], entity)
        source.set('Pos', '1,2,4')
        with self.assertRaises(ValueError):
            bind_path(mission, source, read_paths(graph()))


if __name__ == '__main__':
    unittest.main()
