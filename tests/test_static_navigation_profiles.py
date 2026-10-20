import copy
from pathlib import Path
import struct
import sys
import tempfile
import unittest
import xml.etree.ElementTree as E
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'tools'))
from static_navigation_profiles import BASE, compose, connections, decode, encode, plan, upgrade, validate_door_transforms
from campaign_entity_links import native_guid

SETTINGS = b'\0' * 56
DOOR = 0x47AF70868B71A425


def tile(x, y, layer=0, doors=(), marker=0):
    links = len(doors)
    # Minimal native-layout fixture: one surface polygon plus link polygons.
    header = (0x444e4156, 14, x, y, layer, marker, 1+links, 3+2*links,
              3, 0, 0, 0, 0, 0, 0, links, 1)
    blob = bytearray(struct.pack('<17I11f', *header, 1.76, .32, .32, .8,
                                 x*16, y*16, 0, x*16+16, y*16+16, 8, 12.5))
    blob.extend(b'\0' * (3*4 + links*24 + (1+links)*28))
    for index, door in enumerate(doors):
        blob.extend(struct.pack('<7fHBBQIIHH', x*16+2, y*16+3, 1,
            x*16+2, y*16+4.4, 1, .5, 1+index, 1, 255, door, 8, 0x7fffffff, 1, 65535))
    return bytes(blob)


def pair_files(stem, cells):
    h, n = encode(cells, SETTINGS)
    return {stem+'.hdr': h, stem+'.nav': n}


def fixture():
    files = pair_files(BASE, {(4, 5): (tile(4, 5), tile(4, 5, 1)), (7, 8): (tile(7, 8),)})
    files.update(pair_files('recast/rdnavmesh_other_town_intact_1',
        {(4, 5): (tile(4, 5, doors=(DOOR,)),), (6, 9): (tile(6, 9),)}))
    profiles = E.fromstring('<Root><GameProfileManager><GameProfiles><GameProfile>'
        '<Name>other_town_intact</Name><Id>14</Id><HasNavigation>1</HasNavigation>'
        '</GameProfile></GameProfiles></GameProfileManager></Root>')
    mission = E.Element('Objects')
    E.SubElement(mission, 'Entity', EntityClass='AnimDoor', EntityGuid=native_guid(DOOR))
    return files, profiles, ['other_town_intact'], files[BASE+'.nav'], mission


class StaticNavigationTests(unittest.TestCase):
    def test_static_selection_restores_door_links_and_replaces_entire_height_stack(self):
        files, profiles, selected, native, mission = fixture()
        changes, report = compose(files, profiles, selected, native, mission)
        old = decode(files[BASE+'.hdr'], files[BASE+'.nav'], SETTINGS, 14)
        new = decode(changes[BASE+'.hdr'], changes[BASE+'.nav'], SETTINGS, 14)
        self.assertEqual(len(new[4, 5]), 1)  # no stale upper-floor tile from the old layout
        self.assertEqual(connections(new[4, 5][0])[0]['entity'], DOOR)
        self.assertEqual(new[7, 8], old[7, 8])
        self.assertIn((6, 9), new)
        self.assertEqual(report['added_door_links'], [native_guid(DOOR)])
        self.assertTrue(report['untouched_cells_preserved'])
        self.assertFalse(report['runtime_verified'])
        self.assertEqual(compose(dict(files, **changes), profiles, selected, native, mission)[0], changes)

    def test_missing_profile_dependency_fails_instead_of_publishing_base_only(self):
        for missing in ('.hdr', '.nav'):
            args = list(fixture())
            del args[0]['recast/rdnavmesh_other_town_intact_1'+missing]
            with self.assertRaisesRegex(ValueError, 'Missing navigation pair'):
                compose(*args)

    def test_missing_door_dependency_fails(self):
        args = list(fixture()); args[-1] = E.Element('Objects')
        with self.assertRaisesRegex(ValueError, 'unconverted doors'):
            compose(*args)

    def test_explicit_valid_profile_selection_required(self):
        for selection in ([], ['unknown'], ['other_town_intact']*2):
            args = list(fixture()); args[2] = selection
            with self.assertRaises(ValueError): compose(*args)
        args = list(fixture()); args[1].find('.//HasNavigation').text = '0'
        with self.assertRaisesRegex(ValueError, 'no authored navigation'): compose(*args)

    def test_group_combinations_are_not_treated_as_standalone_overlays(self):
        args = list(fixture())
        groups = E.SubElement(args[1].find('GameProfileManager'), 'GameProfileGroups')
        group = E.SubElement(E.SubElement(groups, 'Groups'), 'Group')
        E.SubElement(E.SubElement(group, 'Profiles'), 'Profile').text = '14'
        with self.assertRaisesRegex(ValueError, 'group combinations'): compose(*args)

    def test_conflicting_profile_cells_fail_instead_of_last_writer_winning(self):
        files, profiles, selected, native, mission = fixture()
        second = copy.deepcopy(profiles.find('.//GameProfile'))
        second.find('Name').text = 'different_state'; second.find('Id').text = '15'
        profiles.find('.//GameProfiles').append(second)
        files.update(pair_files('recast/rdnavmesh_different_state_1', {(4, 5): (tile(4, 5, marker=2),)}))
        with self.assertRaisesRegex(ValueError, 'Conflicting static navigation'):
            compose(files, profiles, selected+['different_state'], native, mission)

    def test_removing_a_resident_doors_link_is_rejected(self):
        files, profiles, selected, native, mission = fixture()
        other = DOOR+1
        E.SubElement(mission, 'Entity', EntityClass='AnimDoor', EntityGuid=native_guid(other))
        files.update(pair_files(BASE, {(4, 5): (tile(4, 5, doors=(other,)),)}))
        with self.assertRaisesRegex(ValueError, 'removes converted door links'):
            compose(files, profiles, selected, native, mission)

    def test_tile_count_bounds_and_connection_contracts_are_checked(self):
        original = tile(4, 5, doors=(DOOR,))
        for offset, fmt, value in [(4, '<I', 15), (28, '<I', 0), (64, '<I', 9),
                                    (84, '<f', float('nan')), (len(original)-24, '<H', 0)]:
            invalid = bytearray(original); struct.pack_into(fmt, invalid, offset, value)
            with self.subTest(offset=offset), self.assertRaises(ValueError): connections(invalid)
        with self.assertRaises(ValueError): connections(original[:-1])

    def test_duplicate_cells_and_height_layers_fail(self):
        h, n = encode({(4, 5): (tile(4, 5), tile(4, 5))}, SETTINGS)
        with self.assertRaisesRegex(ValueError, 'Duplicate navigation height layer'): decode(h, n, SETTINGS, 14)
        h, n = encode({(4, 5): (tile(4, 5),), (6, 7): (tile(6, 7),)}, SETTINGS)
        h, n = bytearray(h), bytearray(n)
        second_offset = struct.unpack_from('<I', h, 28)[0]
        struct.pack_into('<2I', h, 20, 4, 5)
        struct.pack_into('<2I', n, second_offset+8, 4, 5)
        with self.assertRaisesRegex(ValueError, 'Duplicate navigation cell'): decode(h, n, SETTINGS, 14)

    def test_package_upgrade_preserves_variants_and_is_idempotent(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); package, source, target = (root/n for n in ('package','source','target'))
            files, profiles, selected, native, mission = fixture()
            def archive(path, entries):
                path.parent.mkdir(parents=True, exist_ok=True)
                with zipfile.ZipFile(path,'w') as z:
                    for n,b in entries.items(): z.writestr(n,b)
            relative = 'Data/Levels/kcd1_travel/recast.pak'
            archive(package/relative, dict(files, unrelated=b'keep-me'))
            archive(package/'Data/Levels/kcd1_travel/level.pak', {'objects_mission0.xml': E.tostring(mission)})
            original = E.Element('Objects')
            E.SubElement(original, 'Entity', EntityId='17', EntityClass='AnimDoor', EntityGuid=f'{DOOR:016x}')
            archive(source/'Data/Levels/rataje/level.pak', {'whdata_1': E.tostring(profiles), 'objects_mission0.xml': E.tostring(original)})
            archive(source/'Data/Levels/rataje/recast.pak', files)
            archive(target/'Data/Levels/trosecko/recast.pak', files)
            digests, report = upgrade(package, source, target, selected)
            self.assertEqual(report['added_door_links'], [native_guid(DOOR)])
            self.assertEqual(plan(package, source, target, selected)[1], {})
            self.assertEqual(upgrade(package, source, target, selected)[0], digests)
            with zipfile.ZipFile(package/relative) as z:
                self.assertEqual(z.read('unrelated'), b'keep-me')
                for n,b in files.items():
                    if n not in (BASE+'.hdr', BASE+'.nav'): self.assertEqual(z.read(n), b)
                saved = {n:z.read(n) for n in z.namelist()}
            modified = dict(saved)
            modified.update(pair_files(BASE, {(4, 5):(tile(4, 5, marker=99),)}))
            archive(package/relative, modified)
            with self.assertRaisesRegex(ValueError, 'unrecognized edits'):
                plan(package, source, target, selected)
            modified = dict(saved)
            modified['recast/rdnavmesh_other_town_intact_1.nav'] += b'changed'
            archive(package/relative, modified)
            with self.assertRaisesRegex(ValueError, 'differs from its source'):
                plan(package, source, target, selected)
            archive(package/relative, saved)
            # A dynamically switched world must not also receive a flattened base.
            archive(package/'Data/Levels/kcd1_travel/level.pak',
                {'objects_mission0.xml': E.tostring(mission), 'whdata_1': E.tostring(profiles)})
            with self.assertRaisesRegex(ValueError, 'Runtime navigation profiles'):
                plan(package, source, target, selected)

    def test_moved_door_cannot_reuse_the_old_baked_connection(self):
        mission = fixture()[-1]
        original = E.Element('Entity', EntityId='17', EntityClass='AnimDoor', EntityGuid=f'{DOOR:016x}')
        validate_door_transforms({DOOR}, mission, {'17': original}, [original])
        mission[0].set('Pos', '2,0,0')
        with self.assertRaisesRegex(ValueError, 'transform differs'):
            validate_door_transforms({DOOR}, mission, {'17': original}, [original])


if __name__ == '__main__': unittest.main()
