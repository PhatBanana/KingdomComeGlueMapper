import sys
import tempfile
import unittest
import xml.etree.ElementTree as E
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from world_encounter_graphs import Graphs, BASE, ROOT, module
from world_encounter_sites import discover, hull
from campaign_trigger_areas import TriggerArea, write_areas
from setup_world_encounters import owned_state


def archive(test, files):
    folder = tempfile.TemporaryDirectory()
    test.addCleanup(folder.cleanup)
    path = Path(folder.name)/'test.pak'
    with zipfile.ZipFile(path, 'w') as z:
        for name, data in files.items(): z.writestr(name, data)
    result = zipfile.ZipFile(path)
    test.addCleanup(result.close)
    return result


class EncounterGraphsTests(unittest.TestCase):
    def graphs(self):
        parent = module('random_events')
        E.SubElement(parent.find('.//Definitions'), 'Definition', File='random_events/event.xml')
        E.SubElement(parent.find('.//Nodes'), 'event', Name='event')
        child = module('event', 'RandomEventVariant')
        E.SubElement(child.find('.//Nodes'), 'State', Name='alive')
        E.SubElement(child.find('Skald')[0], 'NpcGroups')
        z = archive(self, {ROOT: E.tostring(parent), BASE+'random_events/event.xml': E.tostring(child),
                     BASE.rstrip('/')+'.xml': E.tostring(module('Barbora', 'Project'))})
        self.addCleanup(z.close)
        return Graphs(z), BASE+'random_events/event.xml'

    def test_namespace_first_does_not_erase_executable_event(self):
        g, path = self.graphs()
        g.include(path, shell=True)
        self.assertEqual(g.selected[path].find('Skald')[0].tag, 'Module')
        self.assertIsNone(g.selected[path].find('.//NpcGroups'))
        g.include(ROOT)
        self.assertEqual(g.selected[path].find('Skald')[0].tag, 'RandomEventVariant')
        self.assertIsNotNone(g.selected[path].find('.//State'))
        self.assertIsNotNone(g.selected[path].find('.//NpcGroups'))

    def test_execution_first_survives_later_namespace_reference(self):
        g, path = self.graphs()
        g.include(ROOT)
        before = E.tostring(g.selected[path])
        g.include(path, shell=True)
        self.assertEqual(before, E.tostring(g.selected[path]))

    def test_native_imports_are_literal_archive_paths(self):
        g, path = self.graphs(); g.include(ROOT)
        output, paths = g.finish()
        for name, blob in output.items():
            for definition in E.fromstring(blob).findall('.//Definitions/Definition'):
                relative = definition.get('File')
                self.assertNotIn('..', relative.split('/'))
                self.assertIn(name.rsplit('/', 1)[0]+'/'+relative, output)

    def test_no_fast_travel_without_a_player_landing(self):
        g, path = self.graphs()
        host = g.get(path).find('Skald')[0]
        E.SubElement(host, 'PlayerInitiatedFastTravelData')
        E.SubElement(host, 'EventInitiatedFastTravelData')
        g.include(ROOT)
        output, paths = g.finish()
        self.assertNotIn(b'FastTravelData', output[paths[path]])


class EncounterSitesTests(unittest.TestCase):
    def data(self, *, condition='1', kind='Wanderer', chance='1', points=True):
        main = b'''<Objects><Entity EntityId="1" EntityGuid="0000000000000001" Name="road" EntityClass="RandomEvent"><Properties nRandomEventDBId="10" gpGameProfile="event"/><EntityLinks><Link Name="trigger" TargetId="2"/></EntityLinks></Entity><Entity EntityId="2" EntityGuid="0000000000000002" EntityClass="TriggerArea" Pos="100,200,30"/></Objects>'''
        files = {'objects_mission0.xml': main,
                 'whdata_1': b'<Data><GameProfile><Name>event</Name><GameLayers><GameLayer>event_layer</GameLayer></GameLayers></GameProfile></Data>',
                 'layers/event_layer.xml': b'<Objects>'+ (b'<Entity EntityId="3" EntityGuid="0000000000000003" EntityClass="TagPoint" Pos="108,208,30"><Properties sWH_AI_EntityCategory="wanderer"/></Entity>' if points else b'') + b'</Objects>',
                 'triggerareas.fubar': write_areas([TriggerArea(2, 4, ((100,200,30),(102,200,30),(102,204,30),(100,204,30)))], 1)}
        z = archive(self, files)
        tables = {'random_event': [dict(random_event_id='10', random_event_option_set_id='20', condition_expression=condition, base_run_chance=chance)],
                  'random_event_option_set': [dict(random_event_option_set_id='20', random_event_option_set_name=kind)]}
        return z, tables

    def test_authored_coordinates_are_preserved(self):
        sites, deferred = discover(*self.data())
        self.assertEqual(deferred, [])
        self.assertEqual(sites[0]['native_family'], 'pocestny')
        self.assertEqual(tuple(map(float, sites[0]['spawns'][0].get('Pos').split(','))), (108,208,30))
        self.assertEqual(sites[0]['triggers'][0][1].points[0], (100,200,30))

    def test_campaign_conditions_are_not_discarded(self):
        sites, deferred = discover(*self.data(condition="quest('ambush').active"))
        self.assertEqual(sites, [])
        self.assertIn('quest-specific', deferred[0]['reason'])

    def test_special_scenery_and_missing_ground_points_are_deferred(self):
        for options in ({'kind':'RoadsideCorpse'}, {'points':False}, {'chance':'0'}):
            with self.subTest(options=options):
                sites, deferred = discover(*self.data(**options))
                self.assertEqual(sites, []); self.assertEqual(len(deferred), 1)

    def test_footprint_uses_authored_geometry(self):
        self.assertEqual(hull([(0,0,1),(4,0,1),(4,2,1),(0,2,1),(2,1,1)]), [(0,0),(4,0),(4,2),(0,2)])
        with self.assertRaisesRegex(ValueError, 'Degenerate'): hull([(0,0,0),(1,1,0),(2,2,0)])


class EncounterReceiptTests(unittest.TestCase):
    def files(self):
        return {'objects_mission0.xml': b'<Objects><Entity EntityId="1" EntityGuid="00000001-0000-0000" Name="owned"/><Entity EntityId="2" EntityGuid="00000002-0000-0000" Name="other"/></Objects>',
                'tables/ai/scheduler.xml': b'<Table><Schedulers><C_SmartHub EntityGuid="1"><Links><S_ActivityLink TargetGuid="1"/></Links></C_SmartHub></Schedulers></Table>',
                'waitinglinks.xml': b'<StaticLinksInfo version="1"><WaitingLinks/></StaticLinksInfo>',
                'triggerareas.fubar': write_areas([TriggerArea(1, 2, ((1,1,1),(2,1,1),(2,2,1)))],1)}

    def state(self, files): return owned_state(files, ['00000001-0000-0000'], ['1'])

    def test_other_upgrades_do_not_invalidate_owned_state(self):
        files = self.files(); before = self.state(files)
        files['objects_mission0.xml'] = files['objects_mission0.xml'].replace(b'Name="other"', b'Name="improved"')
        self.assertEqual(before, self.state(files))

    def test_owned_geometry_or_entity_mutation_is_detected(self):
        files = self.files(); before = self.state(files)
        files['objects_mission0.xml'] = files['objects_mission0.xml'].replace(b'Name="owned"', b'Name="broken"')
        self.assertNotEqual(before, self.state(files))
        files = self.files(); files['triggerareas.fubar'] = write_areas([],1)
        self.assertNotEqual(before, self.state(files))

    def test_dangling_entity_and_external_scheduler_targets_fail(self):
        files = self.files()
        files['objects_mission0.xml'] = files['objects_mission0.xml'].replace(b'Name="owned"/>', b'Name="owned"><EntityLinks><Link TargetId="9" TargetGuid="00000009-0000-0000"/></EntityLinks></Entity>')
        with self.assertRaisesRegex(ValueError, 'Dangling'): self.state(files)
        files = self.files(); files['tables/ai/scheduler.xml'] = files['tables/ai/scheduler.xml'].replace(b'TargetGuid="1"', b'TargetGuid="2"')
        with self.assertRaisesRegex(ValueError, 'outside'): self.state(files)


if __name__ == '__main__': unittest.main()
