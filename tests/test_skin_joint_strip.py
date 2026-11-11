"""Unbound joints outside the native rig are removed from converted skins.

KCD2 appends every skin joint its base skeleton lacks to the wearer's extended
skeleton. Synthetic skins only: no game assets.
"""
from pathlib import Path
import struct
import sys
import tempfile
import unittest

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'tools'))
from character_lods import strip_families
from character_skin_upgrade import (CompiledSkin, canonicalize_skin_skeletons, joint_usage, limit_skin_influences,
                                    strip_foreign_joints)
from clothing_regions import Chunk, read_chunks, write_chunks
from test_clothing_assembly import garment_skin

# name, parent. Breadth-first like a compiled palette: the children of a joint are adjacent.
SOURCE = (('Root', None), ('Hips', 0), ('FaceHelper', 0), ('Spine', 1), ('Skirt', 1), ('v_0', 2), ('SkirtEnd', 4))
NATIVE = (('Root', None), ('hips', 0), ('Spine', 1), ('NativeOnly', 0))


def depth_first(bones):
    """The order of the physical entries: depth-first, siblings in palette order."""
    order = []; pending = [i for i, (_, parent) in enumerate(bones) if parent is None][::-1]
    while pending:
        order.append(pending.pop())
        pending.extend(i for i in reversed(range(len(bones))) if bones[i][1] == order[-1])
    return order


def palette(bones):
    table = bytearray(32)
    for i, (name, parent) in enumerate(bones):
        record = bytearray(584)
        struct.pack_into('<I', record, 0, 0x1000+sum(name.encode())*7+len(name))
        bind = np.eye(4); bind[0, 3] = sum(name.encode())%97  # by name: the same joint has one bind pose in every palette
        struct.pack_into('<24f', record, 216, *np.linalg.inv(bind)[:3].ravel(), *bind[:3].ravel())
        record[312:312+len(name)] = name.encode()
        kids = [k for k, (_, p) in enumerate(bones) if p == i]
        struct.pack_into('<iIi', record, 572, parent-i if parent is not None else 0, len(kids), kids[0]-i if kids else 0)
        table.extend(record)
    return bytes(table)


def rigged(bones=SOURCE, influences=((3, 6, 5, 0), (200, 55, 0, 0)), physical=True, bounds=(3, 6), extra=None):
    """A six-vertex skin on ``bones``; every vertex has the same four slots."""
    chunks = read_chunks(garment_skin()); skin = CompiledSkin(garment_skin())
    ids, weights = influences
    stream = struct.pack('<6I', 0, 9, 6, 12, 0, 0)+struct.pack('<4H4B', *ids, *weights)*6
    replacements = {skin.bones.id: palette(bones)}
    if extra is not None:
        mesh = bytearray(skin.mesh.data); struct.pack_into('<I', mesh, 0, struct.unpack_from('<I', mesh)[0] | 4)
        replacements[skin.mesh.id] = bytes(mesh)
        stream = struct.pack('<6I', 0, 9, 12, 12, 0, 0)+struct.pack('<4H4B', *ids, *weights)*6+struct.pack('<4H4B', *extra[0], *extra[1])*6
    replacements[skin.streams[9].id] = stream
    internal = bytearray(skin.internal.data)
    for o in range(32, len(internal), 64):
        struct.pack_into('<4H4f', internal, o+36, *ids, *(w/255 for w in weights))
    replacements[skin.internal.id] = bytes(internal)
    ident = max(c.id for c in chunks)
    if physical:
        table = palette(bones); entries = bytearray(32)
        order = depth_first(bones)
        for position, joint in enumerate(order):
            parent = bones[joint][1]
            record = bytearray(152)
            struct.pack_into('<3i', record, 0, position, order.index(parent) if parent is not None else -1,
                             sum(1 for _, p in bones if p == joint))
            record[12:16] = table[32+584*joint:36+584*joint]
            record[16:20] = struct.pack('<I', 0xabc00000+joint)  # payload that must travel with its entry
            entries.extend(record)
        ident += 1; chunks.append(Chunk(0x2001, 0x800, ident, bytes(entries)))
    for joint in bounds:
        ident += 1
        chunks.append(Chunk(0x3004, 0x801, ident, struct.pack('<I6fI', joint, 0, 0, 1, 5, 0, 1, 6)+struct.pack('<6H', *range(6))))
    return write_chunks(chunks, replacements)


def native_rig():
    return rigged(NATIVE, influences=((0, 0, 0, 0), (255, 0, 0, 0)), physical=False, bounds=())


def names(blob):
    return [b['name'] for b in CompiledSkin(blob).info['bones']]


def bound_names(blob):
    skin = CompiledSkin(blob); table = np.array(names(blob))
    return [sorted(zip(table[i[w > 0]].tolist(), w[w > 0].tolist())) for i, w in zip(skin.ids, skin.weights)]


def physical(blob):
    """Check the retail form of the physical-bone array; return (joint name, body marker) per entry."""
    skin = CompiledSkin(blob); bones = skin.info['bones']; data = skin.one(0x2001).data
    joint = {skin.bones.data[32+584*i:36+584*i]: i for i in range(len(bones))}
    assert len(joint) == len(bones) and not any(data[:32]) and len(data) == 32+152*len(bones), 'one entry per palette joint'
    entries = [(*struct.unpack_from('<3i', data, o), joint[data[o+12:o+16]], struct.unpack_from('<I', data, o+16)[0])
               for o in range(32, len(data), 152)]
    children = {i: [b['index'] for b in bones if b['parent_index'] == i] for i in range(len(bones))}
    order = []; pending = [b['index'] for b in bones if b['parent_index'] is None][::-1]
    while pending:
        order.append(pending.pop()); pending.extend(reversed(children[order[-1]]))
    assert [e[3] for e in entries] == order, 'depth-first over the palette, siblings in palette order'
    for position, (bone, parent, kids, index, _) in enumerate(entries):
        assert bone == position, 'BoneID is the entry position'
        assert -1 <= parent < position, 'ParentID is an earlier entry'
        assert (entries[parent][3] if parent >= 0 else None) == bones[index]['parent_index'], 'parent entry names the palette parent'
        assert kids == len(children[index]), 'child count'
    return [(bones[e[3]]['name'], e[4]) for e in entries]


# A second garment whose extra joint shifts palette indices when the two are unified.
OTHER = (('Root', None), ('Extra', 0), ('Hips', 0), ('Spine', 2))


class StripForeignJointsTests(unittest.TestCase):
    def test_unbound_foreign_joints_leave_and_every_binding_keeps_its_joint(self):
        source = rigged()
        self.assertEqual(sum(n.casefold() not in {b.casefold() for b, _ in NATIVE} for n in names(source)), 4)
        (output,), (report,) = strip_foreign_joints([source], native_rig())
        # FaceHelper and v_0 bind nothing; Skirt binds nothing but carries the bound SkirtEnd.
        self.assertEqual(names(output), ['Root', 'Hips', 'Spine', 'Skirt', 'SkirtEnd'])
        self.assertEqual(report, dict(joints=7, retained=5, removed=['FaceHelper', 'v_0'], foreign_retained=['Skirt', 'SkirtEnd']))
        before, after = CompiledSkin(source), CompiledSkin(output)
        self.assertEqual(bound_names(output), bound_names(source))
        np.testing.assert_array_equal(after.weights, before.weights)
        np.testing.assert_array_equal(after.vertices, before.vertices)
        np.testing.assert_array_equal(after.faces, before.faces)
        # The unbound third slot named the removed v_0; it now names the root.
        np.testing.assert_array_equal(after.ids, np.tile([2, 4, 0, 0], (6, 1)))
        for o in range(32, len(after.internal.data), 64):
            self.assertEqual(struct.unpack_from('<4H', after.internal.data, o+36), (2, 4, 0, 0))
            self.assertEqual(after.internal.data[o:o+36], before.internal.data[o:o+36])
            self.assertEqual(after.internal.data[o+44:o+64], before.internal.data[o+44:o+64])
        for kind in (0, 1, 2, 5, 6):
            self.assertEqual(after.streams[kind].data, before.streams[kind].data)

    def test_hierarchy_bind_pose_and_controllers_survive(self):
        source = rigged(); (output,), _ = strip_foreign_joints([source], native_rig())
        old = {b['name']: b for b in CompiledSkin(source).info['bones']}
        new = CompiledSkin(output)
        for bone in new.info['bones']:
            self.assertEqual(bone['parent'], old[bone['name']]['parent'])
            self.assertEqual(bone['bind'], old[bone['name']]['bind'])
            self.assertEqual(bone['inverse_bind'], old[bone['name']]['inverse_bind'])
            o, p = 32+584*bone['index'], 32+584*old[bone['name']]['index']
            self.assertEqual(new.bones.data[o:o+572], CompiledSkin(source).bones.data[p:p+572])
        links = [struct.unpack_from('<iIi', new.bones.data, 32+584*i+572) for i in range(5)]
        # Root keeps one child of two; Hips keeps Spine and Skirt, which stay adjacent.
        self.assertEqual(links, [(0, 1, 1), (-1, 2, 1), (-1, 0, 0), (-2, 1, 1), (-1, 0, 0)])

    def test_physical_entries_and_bounds_follow_their_joints(self):
        source = rigged(); (output,), _ = strip_foreign_joints([source], native_rig())
        skin = CompiledSkin(output); physical = skin.one(0x2001).data
        controllers = {skin.bones.data[32+584*i:36+584*i]: b['name'] for i, b in enumerate(skin.info['bones'])}
        entries = [(struct.unpack_from('<3i', physical, o), controllers[physical[o+12:o+16]], physical[o+16:o+20])
                   for o in range(32, len(physical), 152)]
        self.assertEqual([(e[0], e[1]) for e in entries],
                         [((0, -1, 1), 'Root'), ((1, 0, 2), 'Hips'), ((2, 1, 0), 'Spine'), ((3, 1, 1), 'Skirt'), ((4, 3, 0), 'SkirtEnd')])
        self.assertEqual([struct.unpack('<I', e[2])[0]-0xabc00000 for e in entries], [0, 1, 3, 4, 6])
        bounds = [c for c in skin.chunks if c.kind == 0x3004]
        self.assertEqual([skin.info['bones'][struct.unpack_from('<I', c.data)[0]]['name'] for c in bounds], ['Spine', 'SkirtEnd'])
        self.assertEqual([c.data[4:] for c in bounds], [c.data[4:] for c in read_chunks(source) if c.kind == 0x3004])

    def test_bound_of_a_removed_joint_is_removed_with_it(self):
        source = rigged(bounds=(3, 5)); (output,), _ = strip_foreign_joints([source], native_rig())
        skin = CompiledSkin(output)
        self.assertEqual([struct.unpack_from('<I', c.data)[0] for c in skin.chunks if c.kind == 0x3004], [2])

    def test_a_palette_with_nothing_to_remove_is_returned_untouched(self):
        native = rigged(NATIVE, influences=((1, 2, 0, 0), (200, 55, 0, 0)), physical=False, bounds=())
        (output,), (report,) = strip_foreign_joints([native], native_rig())
        self.assertIs(output, native)
        self.assertEqual((report['removed'], report['foreign_retained']), ([], []))
        # A second pass over an already stripped skin changes nothing either.
        (once,), _ = strip_foreign_joints([rigged()], native_rig())
        (twice,), _ = strip_foreign_joints([once], native_rig())
        self.assertIs(twice, once)

    def test_native_names_match_without_case_and_unbound_native_joints_stay(self):
        (output,), _ = strip_foreign_joints([rigged(influences=((3, 0, 0, 0), (255, 0, 0, 0)))], native_rig())
        # 'Hips' is the rig's 'hips' and binds nothing here; it is a base joint and costs nothing.
        self.assertEqual(names(output), ['Root', 'Hips', 'Spine'])

    def test_a_joint_bound_only_in_the_second_influence_block_stays(self):
        source = rigged(influences=((3, 0, 0, 0), (200, 0, 0, 0)), extra=((5, 0, 0, 0), (55, 0, 0, 0)))
        (output,), (report,) = strip_foreign_joints([source], native_rig())
        self.assertEqual(report['foreign_retained'], ['FaceHelper', 'v_0'])
        self.assertEqual(report['removed'], ['Skirt', 'SkirtEnd'])
        self.assertEqual(bound_names(output), bound_names(source))
        packed, _ = limit_skin_influences(output)
        self.assertEqual(bound_names(packed), bound_names(source))

    def test_a_joint_bound_only_by_internal_vertices_stays(self):
        source = rigged(influences=((3, 0, 0, 0), (255, 0, 0, 0))); skin = CompiledSkin(source)
        internal = bytearray(skin.internal.data)
        struct.pack_into('<4H4f', internal, 32+36, 3, 6, 0, 0, .5, .5, 0, 0)
        source = write_chunks(skin.chunks, {skin.internal.id: bytes(internal)})
        self.assertTrue(joint_usage(CompiledSkin(source))[6])
        (output,), _ = strip_foreign_joints([source], native_rig())
        self.assertEqual(names(output), ['Root', 'Hips', 'Spine', 'Skirt', 'SkirtEnd'])
        self.assertEqual(struct.unpack_from('<4H', CompiledSkin(output).internal.data, 32+36), (2, 4, 0, 0))

    def test_lod_family_keeps_one_palette(self):
        base = rigged(); lower = rigged(influences=((3, 0, 0, 0), (255, 0, 0, 0)), bounds=(3,))
        (alone,), _ = strip_foreign_joints([lower], native_rig())
        self.assertEqual(names(alone), ['Root', 'Hips', 'Spine'])
        outputs, _ = strip_foreign_joints([base, lower], native_rig())
        # SkirtEnd is bound at LOD0 only; both levels list it, so they still share palette indices.
        self.assertEqual(names(outputs[0]), names(outputs[1]))
        self.assertEqual(CompiledSkin(outputs[0]).bones.data, CompiledSkin(outputs[1]).bones.data)
        self.assertEqual(bound_names(outputs[1]), bound_names(lower))

    def test_physical_entry_of_a_removed_unbound_joint_leaves_and_the_array_keeps_the_retail_form(self):
        source = rigged(); marks = dict(physical(source))
        self.assertEqual(marks['v_0']-0xabc00000, 5)
        (output,), _ = strip_foreign_joints([source], native_rig())
        self.assertEqual(physical(output), [(name, marks[name]) for name in ('Root', 'Hips', 'Spine', 'Skirt', 'SkirtEnd')])

    def test_a_stripped_garment_can_be_unified_again(self):
        # The female path unifies a garment with its attachments, strips it, then unifies the garments
        # of one draw region. unified-12 stopped there with "Physical bone outside palette".
        other = rigged(OTHER, influences=((3, 0, 0, 0), (255, 0, 0, 0)), bounds=())
        marks = dict(physical(rigged()))
        garment, attachment = canonicalize_skin_skeletons([rigged(), other])
        self.assertEqual(names(garment), ['Root', 'Hips', 'FaceHelper', 'Extra', 'Spine', 'Skirt', 'v_0', 'SkirtEnd'])
        (stripped,), (report,) = strip_foreign_joints([garment], native_rig())
        self.assertEqual(report['removed'], ['FaceHelper', 'Extra', 'v_0'])
        layer, under = canonicalize_skin_skeletons([stripped, rigged(influences=((3, 0, 0, 0), (255, 0, 0, 0)), bounds=())])
        self.assertEqual(bound_names(layer), bound_names(rigged()))
        for blob in (garment, attachment, stripped, layer, under):
            for name, mark in physical(blob):
                if name != 'Extra':
                    self.assertEqual(mark, marks[name])
        self.assertEqual([name for name, _ in physical(layer)], ['Root', 'Hips', 'Spine', 'Skirt', 'SkirtEnd', 'FaceHelper', 'v_0'])

    def test_unified_garments_describe_every_joint_of_the_shared_palette(self):
        other = rigged(OTHER, influences=((3, 0, 0, 0), (255, 0, 0, 0)), bounds=())
        skin = CompiledSkin(other); chunk = skin.one(0x2001); entries = bytearray(chunk.data)
        extra = skin.bones.data[32+584:36+584]
        for o in range(32, len(entries), 152):
            if entries[o+12:o+16] == extra:
                struct.pack_into('<I', entries, o+16, 0xe0e0e0e0)
        other = write_chunks(skin.chunks, {chunk.id: bytes(entries)})
        first, second = canonicalize_skin_skeletons([rigged(), other])
        self.assertEqual(CompiledSkin(first).one(0x2001).data, CompiledSkin(second).one(0x2001).data)
        self.assertEqual(dict(physical(first))['Extra'], 0xe0e0e0e0)
        self.assertEqual(dict(physical(first))['SkirtEnd']-0xabc00000, 6)
        # A garment without the chunk gains none; one whose chunk misses a joint takes the bone record's physics.
        bare = CompiledSkin(rigged(OTHER, influences=((3, 0, 0, 0), (255, 0, 0, 0)), physical=False, bounds=()))
        table = bytearray(bare.bones.data); table[32+584+4:32+584+108] = bytes(range(104))
        first, second = canonicalize_skin_skeletons([write_chunks(bare.chunks, {bare.bones.id: bytes(table)}), rigged()])
        self.assertFalse([c for c in read_chunks(first) if c.kind == 0x2001])
        skin = CompiledSkin(second); data = skin.one(0x2001).data
        self.assertEqual([name for name, _ in physical(second)][:2], ['Root', 'Extra'])
        self.assertEqual(data[32+152+16:32+152+48], bytes(32))
        self.assertEqual(data[32+152+48:32+2*152], bytes(range(104)))

    def test_entries_scrambled_by_an_older_palette_unification_are_rebuilt(self):
        # Before the array was rebuilt, unification passed its positions through the palette mapping.
        source = CompiledSkin(rigged()); chunk = source.one(0x2001); entries = bytearray(chunk.data)
        for position, o in enumerate(range(32, len(entries), 152)):
            struct.pack_into('<3i', entries, o, 250-position, 243, 9)
        rewritten = write_chunks(source.chunks, {chunk.id: bytes(entries)})
        (output,), _ = strip_foreign_joints([rewritten], native_rig())
        self.assertEqual(bound_names(output), bound_names(rewritten))
        (expected,), _ = strip_foreign_joints([rigged()], native_rig())
        self.assertEqual(output, expected)

    def test_missing_native_rig_and_unordered_parents_fail(self):
        with self.assertRaisesRegex(ValueError, 'Missing native skeleton'):
            strip_foreign_joints([rigged()], write_chunks([c for c in read_chunks(rigged()) if c.kind != 0x2000], {}))
        skin = CompiledSkin(rigged()); table = bytearray(skin.bones.data)
        struct.pack_into('<i', table, 32+584*2+572, 3)  # FaceHelper under the later v_0
        with self.assertRaisesRegex(ValueError, 'parent before child'):
            strip_foreign_joints([write_chunks(skin.chunks, {skin.bones.id: bytes(table)})], native_rig())


class StripFamiliesTests(unittest.TestCase):
    def test_base_and_lod_files_are_decided_together_and_other_files_are_left(self):
        base = rigged(); lower = rigged(influences=((3, 0, 0, 0), (255, 0, 0, 0)), bounds=(3,))
        with tempfile.TemporaryDirectory() as folder:
            staged = Path(folder)/'0'; staged.write_bytes(lower)
            files = {'objects/characters/x/Coat.skin': base, 'objects\\characters\\x\\coat_LOD1.skin': staged,
                     'objects/characters/x/hat.skin': lower, 'objects/characters/x/coat.mtl': b'<Material/>',
                     'objects/characters/y/other.skin': base}
            report = strip_families(files, native_rig(), 'objects/characters/x/')
            self.assertEqual(names(files['objects/characters/x/Coat.skin']), ['Root', 'Hips', 'Spine', 'Skirt', 'SkirtEnd'])
            self.assertEqual(names(files['objects\\characters\\x\\coat_LOD1.skin']), ['Root', 'Hips', 'Spine', 'Skirt', 'SkirtEnd'])
            self.assertEqual(names(files['objects/characters/x/hat.skin']), ['Root', 'Hips', 'Spine'])
            self.assertIs(files['objects/characters/y/other.skin'], base)
            self.assertEqual(files['objects/characters/x/coat.mtl'], b'<Material/>')
            self.assertEqual(report['objects/characters/x/hat.skin'], dict(joints=7, retained=3, foreign_retained=[]))
            self.assertEqual(set(report), {'objects/characters/x/Coat.skin', 'objects\\characters\\x\\coat_LOD1.skin',
                                           'objects/characters/x/hat.skin'})

    def test_staged_assets_are_rewritten_in_place(self):
        from static_assets import StagedAssets
        with tempfile.TemporaryDirectory() as folder:
            files = StagedAssets(folder); files['p/part0_torso.skin'] = rigged()
            path = files['p/part0_torso.skin']
            strip_families(files, native_rig(), 'p/')
            self.assertEqual(files['p/part0_torso.skin'], path)
            self.assertEqual(names(path.read_bytes()), ['Root', 'Hips', 'Spine', 'Skirt', 'SkirtEnd'])


class ConverterTests(unittest.TestCase):
    def test_imported_body_pieces_list_no_unbound_source_joint(self):
        from contextlib import ExitStack
        from types import SimpleNamespace
        from unittest.mock import patch
        from campaign_character_dependencies import CharacterPartAdapter
        from campaign_dependencies import DependencyImporter
        from campaign_dependency_adapters import LazyAdapter
        from test_campaign_dependencies import Adapter, Tables
        from test_character_upgrade import sample_skin, target_skin
        native = target_skin(sample_skin()); skin = CompiledSkin(sample_skin()); table = bytearray(skin.bones.data)
        helper = bytearray(table[32+584:32+2*584]); struct.pack_into('<I', helper, 0, 77)
        helper[312:568] = b'jaw_blendWeightVertex'.ljust(256, b'\0'); struct.pack_into('<iIi', helper, 572, -2, 0, 0)
        struct.pack_into('<iIi', table, 32+572, 0, 2, 1)
        source = write_chunks(skin.chunks, {skin.bones.id: bytes(table+helper)})
        self.assertEqual(names(source), ['Hips', 'Child', 'jaw_blendWeightVertex'])
        with tempfile.TemporaryDirectory() as tmp, ExitStack() as stack:
            root = Path(tmp); material = root/'source.mtl'; material.write_bytes(b'<Material Shader="HumanSkin"/>')
            mesh = 'objects/characters/humans/body/arbitrary.skin'; mat = 'objects/characters/humans/body/arbitrary.mtl'
            pack = SimpleNamespace(index={mesh: (SimpleNamespace(filename='retail.pak'), SimpleNamespace(filename=mesh)), mat: None},
                                   emitted={'converted-'+mat: material}, mesh=lambda name: source)
            identity = '12345678-1234-1234-1234-123456789abc'
            tables = Tables({'character_body': [dict(character_body_id=identity, model='arbitrary', material='arbitrary',
                                                     gender_id='1', race_id='0')]})
            importer = DependencyImporter(dict(character_parts=CharacterPartAdapter(tables, root, stack, LazyAdapter(lambda: pack), 'AnyStory'),
                                               assets=Adapter()))
            with patch('campaign_character_dependencies.Assets') as reader:
                reader.return_value.get.return_value = (native, [dict(archive='native-retail')])
                self.assertIsNotNone(importer.ensure('character_parts', 'body:'+identity), importer.report())
            skins = [v for k, v in importer.files.items() if k.endswith('.skin')]
            self.assertTrue(skins)
            for blob in skins:
                self.assertEqual(names(blob), ['Hips', 'Child'])
            self.assertEqual(sum(len(CompiledSkin(v).faces) for v in skins), len(skin.faces))


if __name__ == '__main__':
    unittest.main()
