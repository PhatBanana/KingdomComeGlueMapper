import io
from pathlib import Path
import struct
import sys
import unittest
from unittest.mock import patch
import xml.etree.ElementTree as E
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from campaign_dependencies import DependencyImporter
from campaign_navigation import NavigationSource, BaseNavigationAdapter, ProfileNavigationAdapter


def archive(files):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, 'w') as handle:
        for name, data in files.items():
            handle.writestr(name, data)
    return zipfile.ZipFile(buffer)


def fixtures(version=14, settings=b'\0' * 56, grouped=False):
    tile = struct.pack('<4I', 0x444e4156, version, 8, 9)
    header = struct.pack('<5I', 8, 9, 60, 1, len(tile))
    mesh = settings + struct.pack('<I', 1) + tile
    source = archive({'recast/rdnavmesh_1.hdr': header, 'recast/rdnavmesh_1.nav': mesh,
        'recast/rdnavmesh_opening_state_1.hdr': header, 'recast/rdnavmesh_opening_state_1.nav': mesh})
    native = archive({'recast/rdnavmesh_1.nav': b'\0' * 56 + struct.pack('<5I', 1, 0x444e4156, 14, 8, 9)})
    graph = archive({'ubernav.tmm': struct.pack('<I', 7) + b'source-paths', 'areasmission0.bai': b'source-areas'})
    target_graph = archive({'ubernav.tmm': struct.pack('<I', 7) + b'different-native-world'})
    profiles = E.fromstring('''<Root><GameProfileManager><GameProfiles><GameProfile>
      <Name>opening_state</Name><Id>4</Id><HasNavigation>1</HasNavigation></GameProfile>
      </GameProfiles></GameProfileManager></Root>''')
    if grouped:
        group = E.SubElement(E.SubElement(E.SubElement(profiles, 'GameProfileGroups'), 'Groups'), 'Group')
        E.SubElement(group, 'Name').text = 'compound'
        E.SubElement(E.SubElement(group, 'Profiles'), 'Profile').text = '4'
    return NavigationSource(source, native, graph, target_graph, profiles, 'DifferentCampaign', 'source_map')


class ProfileNavigationTests(unittest.TestCase):
    def setUp(self):
        # Retail read() handles CryEngine's nonstandard ZIP compression. The
        # bounded fixtures are normal in-memory ZIPs with no filesystem path.
        reader = patch('campaign_navigation.read', lambda handle, name: handle.read(name))
        reader.start()
        self.addCleanup(reader.stop)

    def test_profile_mesh_is_validated_and_renamed_without_replacing_source_geometry(self):
        source = fixtures()
        result = DependencyImporter(dict(navigation_base=BaseNavigationAdapter(source),
            profile_navigation=ProfileNavigationAdapter(source)))
        self.assertEqual(result.ensure('profile_navigation', 'opening_state'), 'differentcampaign_opening_state')
        path = 'world/navigation/recast/rdnavmesh_differentcampaign_opening_state_1.nav'
        self.assertEqual(result.files[path], source.recast.read('recast/rdnavmesh_opening_state_1.nav'))
        self.assertEqual(result.files['world/navigation/ubernav.tmm'], struct.pack('<I', 7) + b'source-paths')
        self.assertIn('world/navigation/recast/rdnavmesh_1.hdr', result.files)
        evidence = result.jobs[('profile_navigation', 'opening_state')]['evidence']
        self.assertEqual(evidence['tiles'], 1)
        self.assertTrue(evidence['profile_path_remapped'])
        self.assertFalse(evidence['runtime_validated'])

    def test_incompatible_tile_version_or_settings_refuse_registration(self):
        for source in (fixtures(version=13), fixtures(settings=b'\1' * 56)):
            result = DependencyImporter(dict(profile_navigation=ProfileNavigationAdapter(source)))
            self.assertIsNone(result.ensure('profile_navigation', 'opening_state'))
            self.assertFalse(result.files)

    def test_grouped_profile_does_not_fall_back_to_standalone_mesh(self):
        source = fixtures(grouped=True)
        result = DependencyImporter(dict(profile_navigation=ProfileNavigationAdapter(source)))
        self.assertIsNone(result.ensure('profile_navigation', 'opening_state'))
        self.assertIn('group combinations require conversion', result.jobs[('profile_navigation', 'opening_state')]['error'])


if __name__ == '__main__':
    unittest.main()
