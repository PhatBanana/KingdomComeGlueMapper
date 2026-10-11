from pathlib import Path
import sys
import unittest
import xml.etree.ElementTree as E

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from campaign_dependencies import DependencyImporter
from campaign_profiles import ProfileBridge, WorldProfileAdapter, WorldLayerAdapter, ProfileLifecycleAdapter
from campaign_entity_links import native_guid
from campaign_quest_bridge import UnsupportedOperation


PROFILES = '''<Root><GameProfileManager><GameProfiles><GameProfile>
  <Name>authored_opening</Name><Id>814</Id><HasNavigation>1</HasNavigation>
  <NeedsSVORebuild>0</NeedsSVORebuild><GameLayers>
  <GameLayer>Actors{AB}</GameLayer><GameLayer>Doors{CD}</GameLayer></GameLayers>
  <AutoActForOlderVersion>2147483647</AutoActForOlderVersion>
</GameProfile></GameProfiles></GameProfileManager></Root>'''
HELPER = b'''<Database><Skald><Module Name="streamprofileshandling"><Nodes>
  <Layer/><ProfileStateTrigger/></Nodes></Module></Skald></Database>'''


def importer(registered=None):
    adapter = WorldProfileAdapter(E.fromstring(PROFILES), 'OtherWorld', [dict(archive='retail')])
    return DependencyImporter(dict(world_profiles=adapter), registered)


def complete_importer():
    return importer(dict(world_layers={'Actors{AB}': 'native_actors', 'Doors{CD}': 'native_doors'},
        profile_navigation={'authored_opening': 'nav_receipt'},
        profile_lifecycle={'authored_opening': 'migration_receipt'}))


def action(enable='', disable=''):
    return dict(op='EnableProfile', attributes=dict(profileEnable='"' + enable + '"',
        profileDisable='"' + disable + '"'), children=[], text='')


class WorldProfileTests(unittest.TestCase):
    def test_only_declared_invalid_version_policy_avoids_cross_game_migration(self):
        root = E.fromstring(PROFILES)
        metadata = dict(sha256='source-engine-proof', enum_declarations=[dict(name='gameVersion',
            function_start_rva=123, values=[dict(name='Invalid', ordinal=2147483647), dict(name='Later', ordinal=90)])])
        adapter = ProfileLifecycleAdapter(root, 'World', metadata)
        plan = adapter.plan('authored_opening')
        _, files, evidence = adapter.convert('authored_opening', plan, {})
        self.assertFalse(files)
        self.assertEqual(evidence['source_enum'], 'gameVersion.Invalid')
        self.assertFalse(evidence['cross_game_version_comparison'])
        root.find('.//AutoActForOlderVersion').text = '90'
        with self.assertRaisesRegex(ValueError, 'runtime service.*before Later'):
            adapter.plan('authored_opening')

    def test_layer_members_require_real_outputs_and_keep_authored_order(self):
        a, b = native_guid(11), native_guid(12)
        documents = {'layers/People{AB}.xml': b'<Objects><Entity Name="one" EntityGuid="000000000000000B"/><Entity Name="two" EntityGuid="000000000000000C"/></Objects>'}
        files = {'world/entities/' + a + '.xml': b'<Entity Name="native_one"/>',
                 'world/entities/' + b + '.xml': b'<Entity Name="native_two"/>'}
        adapter = WorldLayerAdapter(documents, 'AnotherWorld', files)
        plan = adapter.plan('people{ab}')
        self.assertEqual(plan.dependencies, [('entities', a), ('entities', b)])
        target, output, _ = adapter.convert('people{ab}', plan, {'entities': {a: a, b: b}})
        root = E.fromstring(next(iter(output.values())))
        self.assertEqual([n.get('Name') for n in root], ['native_one', 'native_two'])
        self.assertEqual({n.get('Layer') for n in root}, {target})
        files.pop('world/entities/' + b + '.xml')
        with self.assertRaisesRegex(ValueError, 'no converted output'):
            adapter.convert('people{ab}', plan, {'entities': {a: a, b: b}})

    def test_old_decals_are_requested_for_conversion_instead_of_copied(self):
        adapter = WorldLayerAdapter({'layers/Scenery.xml': b'<Objects><Object Type="Decal" Material="old"/></Objects>'}, 'World', {})
        plan = adapter.plan('scenery')
        self.assertEqual(plan.dependencies, [('world_layer_objects', 'scenery#0')])

    def test_local_prefab_entities_do_not_hide_later_layer_dependencies(self):
        data = b'<Objects><Entity EntityGuid="0"/><Entity EntityGuid="000000000000000B"/><Object Type="Decal"/></Objects>'
        adapter = WorldLayerAdapter({'layers/Scenery.xml': data}, 'World', {})
        plan = adapter.plan('scenery')
        self.assertEqual(plan.dependencies, [('world_layer_entities', 'scenery#0'),
            ('entities', native_guid(11)), ('world_layer_objects', 'scenery#2')])

    def test_native_empty_profiles_remain_explicit_profiles(self):
        root = E.fromstring('<Root><GameProfile><Name>empty_event</Name><Id>9</Id><HasNavigation>0</HasNavigation><NeedsSVORebuild>0</NeedsSVORebuild></GameProfile></Root>')
        adapter = WorldProfileAdapter(root, 'World', [])
        result = DependencyImporter(dict(world_profiles=adapter))
        self.assertEqual(result.ensure('world_profiles', 'empty_event'), 'world_empty_event')
        self.assertIsNone(E.fromstring(next(iter(result.files.values()))).find('GameLayers'))

    def test_navigation_and_migration_cannot_be_dropped_to_register_profile(self):
        result = importer(dict(world_layers={'Actors{AB}': 'native_actors', 'Doors{CD}': 'native_doors'}))
        self.assertIsNone(result.ensure('world_profiles', 'authored_opening'))
        failed = result.jobs[('world_profiles', 'authored_opening')]
        self.assertIn('profile_navigation:authored_opening', failed['error'])
        self.assertIn('profile_lifecycle:authored_opening', failed['error'])
        self.assertFalse(result.files)

    def test_native_fragment_preserves_flags_and_layer_order_without_claiming_world_id(self):
        result = complete_importer()
        self.assertEqual(result.ensure('world_profiles', 'authored_opening'), 'otherworld_authored_opening')
        root = E.fromstring(next(iter(result.files.values())))
        self.assertEqual(root.findtext('HasNavigation'), '1')
        self.assertEqual(root.findtext('NeedsSVORebuild'), '0')
        self.assertEqual([n.text for n in root.findall('GameLayers/GameLayer')], ['native_actors', 'native_doors'])
        self.assertIsNone(root.find('Id'))
        self.assertFalse(result.jobs[('world_profiles', 'authored_opening')]['evidence']['runtime_validated'])

    def test_activation_remains_event_driven_with_actual_loaded_acknowledgement(self):
        result = complete_importer()
        bridge = ProfileBridge('OtherWorld', result)
        node = bridge.lower(action('authored_opening'), dict(tree='sourceTree'))
        disable = bridge.lower(action(disable='authored_opening'), dict(tree='anotherTree'))
        self.assertNotEqual(node.tag, disable.tag)
        files = bridge.emit(HELPER)
        root = E.fromstring(files['Quests/OtherWorld_profile_bridge.xml'])
        stream = root.find('.//streamprofileshandling')
        edges = {e.get('To'): e.get('From') for e in stream.findall('Edge')}
        self.assertEqual(edges['streamprofiles'], node.tag.removeprefix('SendAIConceptSignal_') + '.OnNotification')
        self.assertEqual(edges['unstreamprofiles'], disable.tag.removeprefix('SendAIConceptSignal_') + '.OnNotification')
        self.assertEqual(root.find('.//ProfileAsset').get('AssetProfiles'), 'otherworld_authored_opening')
        loaded = root.find('.//State')
        self.assertEqual(loaded.find("Edge[@To='SetTrue']").get('From'), stream.get('Name') + '.onloaded')
        self.assertEqual(loaded.find("Edge[@To='SetFalse']").get('From'), stream.get('Name') + '.onunloaded')
        self.assertFalse(any(e.get('From') in ('OnWake', 'OnInit') for e in root.iter('Edge')))
        self.assertEqual(files['Quests/OtherWorld_profile_streaming.xml'], HELPER)
        self.assertEqual(root.find('.//Definitions/Definition').get('File'), 'OtherWorld_profile_streaming.xml')

    def test_incomplete_profile_cannot_emit_activation_signal(self):
        bridge = ProfileBridge('OtherWorld', importer())
        with self.assertRaisesRegex(UnsupportedOperation, 'conversion did not complete'):
            bridge.lower(action('authored_opening'), {})
        self.assertFalse(bridge.actions)
        with self.assertRaisesRegex(UnsupportedOperation, 'Dynamic profile identity'):
            bridge.lower(action('$profile'), {})

    def test_activation_refuses_changed_helper_and_conflicting_source_request(self):
        bridge = ProfileBridge('OtherWorld', complete_importer())
        with self.assertRaisesRegex(UnsupportedOperation, 'enabled and disabled'):
            bridge.lower(action('authored_opening', 'authored_opening'), {})
        bridge.lower(action('authored_opening'), {})
        with self.assertRaisesRegex(ValueError, 'helper contract changed'):
            bridge.emit(b'<Database><Skald><Module Name="streamprofileshandling"/></Skald></Database>')


if __name__ == '__main__':
    unittest.main()
