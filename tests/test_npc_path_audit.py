"""Regression cases for source placement, emitted jobs and retail mount diagnosis."""
from contextlib import contextmanager
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
import xml.etree.ElementTree as E
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from character_person import world_entity
from character_market_jobs import resolve
from character_schedule_world import resolve_arrivals
from character_schedule_jobs import job_resources
from character_sweeping_routes import TEMPLATE
from npc_runtime_paths import audit


@contextmanager
def archive(files):
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / 'level.pak'
        with zipfile.ZipFile(path, 'w') as z:
            for name, content in files.items():
                z.writestr(name, content)
        with zipfile.ZipFile(path) as z:
            yield z


class PlacementTests(unittest.TestCase):
    def fixture(self):
        # The parent's position is itself local to a root in another layer.
        point = E.fromstring('<Entity EntityClass="TagPoint" EntityId="3" EntityGuid="3" '
                             'ParentId="2" Pos="1,0,0"/>')
        files = {'objects_mission0.xml': b'<Objects>' + E.tostring(point) + b'</Objects>',
                 'layers/parents.xml': '<Objects><Entity EntityId="2" ParentId="1" Pos="10,0,0" '
                     'Rotate="0.7071067811865476,0,0,0.7071067811865476"/>'
                     '<Entity EntityId="1" Pos="100,200,30"/></Objects>'}
        return point, files

    def test_nested_cross_layer_parent_is_composed_without_mutating_source(self):
        point, files = self.fixture()
        before = E.tostring(point)
        provenance = {}
        with archive(files) as z:
            result = world_entity(z, point, [point], provenance)
        self.assertEqual(tuple(map(float, result.get('Pos').split(','))), (110, 201, 30))
        self.assertIsNone(result.get('ParentId'))
        self.assertEqual(E.tostring(point), before)
        self.assertIn('layers/parents.xml', provenance)

    def test_market_and_area_arrivals_use_world_not_local_position(self):
        point, files = self.fixture()
        for label, resolver in [('merchantPoint', resolve), ('inside', None)]:
            entry = dict(area=dict(EntityId='9'), target_links=[dict(Name=label, TargetId='3')],
                         behavior=dict(tree_file='final/sa_home.xml', tree_name='housework'))
            with archive(files) as z:
                result = resolver(entry, z) if resolver else resolve_arrivals(dict(resolved=[entry]), z)[0]
            self.assertEqual(result['arrival']['Pos'], '110,201,30')
            self.assertNotIn('ParentId', result['arrival'])

    def test_unparented_position_is_retained_and_missing_parent_or_cycle_fails(self):
        point = E.fromstring('<Entity EntityId="3" Pos="1.000,2.000,3.000"/>')
        with archive({}) as z:
            self.assertEqual(world_entity(z, point, [point]).get('Pos'), point.get('Pos'))
            point.set('ParentId', '3')
            with self.assertRaisesRegex(ValueError, 'cycle'):
                world_entity(z, point, [point])
            point.set('ParentId', 'missing')
            with self.assertRaisesRegex(ValueError, 'Unresolved'):
                world_entity(z, point, [point])


class ResourceTests(unittest.TestCase):
    def test_route_holder_brings_its_program_even_without_new_people(self):
        files = {'objects_mission0.xml': f'<Objects><Entity><Properties guidSmartObjectType="{TEMPLATE}"/></Entity></Objects>'.encode()}
        payload = {'AI/gluemapper/sweeping_route.xml': b'program', 'Libs/Tables/route.xml': b'template'}
        with patch('character_sweeping_routes.resources', return_value=(payload, {})) as emit:
            self.assertEqual({k: v for k, v in job_resources(None, None, files, {}).items() if k in payload}, payload)
            emit.assert_called_once()

    def test_arrival_only_does_not_require_source_sweeping_program(self):
        with patch('character_sweeping_routes.resources', side_effect=AssertionError('unused')):
            self.assertIn('AI/gluemapper/schedule_arrival.xml',
                          job_resources(None, None, {'objects_mission0.xml': b'<Objects/>'}, {}))

    def test_station_program_is_packaged_with_the_bound_template(self):
        from character_station_work import resources
        contract = dict(movement=dict(destinationSpecification='$__object.id'), wait=dict(duration='-1'))
        template, expected = resources(contract)
        files = {'objects_mission0.xml': f'<Objects><Entity><Properties guidSmartObjectType="{template}"/></Entity></Objects>'.encode()}
        result = job_resources(None, None, files, {'person': [dict(station_work=contract)]})
        self.assertTrue(expected.items() <= result.items())


class RuntimePathTests(unittest.TestCase):
    def test_mod_relative_load_is_not_validated_by_successful_lua_initialization(self):
        with archive({'whdata_0': '<Root><AI><LevelPath>data/levels/custom</LevelPath></AI></Root>'}) as z:
            log = "Pak 'mods\\test\\data\\levels\\custom\\level.pak' is opened, root: 'mods\\test\\data\\levels\\custom\\'\n[GM_NPC_INIT] exit BasicAI.RegisterAI hasAI=true"
            result = audit(z.filename, log)
            self.assertEqual(result['status'], 'ai_level_path_mismatch')
            self.assertFalse(result['runtime_verified'])

    def test_canonical_mount_agrees_but_does_not_claim_walking(self):
        with archive({'whdata_0': '<Root><AI><LevelPath>data/levels/custom</LevelPath></AI></Root>'}) as z:
            result = audit(z.filename, "Pak 'data\\levels\\custom\\level.pak' is opened, root: 'data\\levels\\custom\\'")
            self.assertEqual(result['status'], 'matching_mount')
            self.assertFalse(result['runtime_verified'])
            self.assertEqual(audit(z.filename, 'no level entered')['status'], 'no_level_mount_in_log')


if __name__ == '__main__':
    unittest.main()
