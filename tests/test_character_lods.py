from pathlib import Path
import sys
import struct
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from character_lods import source_lods, filename, validate_chain, emit_regions
from clothing_regions import split_skin_regions, Skin, write_chunks
from test_clothing_regions import sample_skin


class CharacterLodTests(unittest.TestCase):
    def test_discovery_preserves_model_identity_and_order(self):
        index = {'objects\\Head_LOD2.skin': None, 'objects/head_lod1.skin': None,
                 'objects/head_other_lod1.skin': None}
        self.assertEqual(list(source_lods(index, 'Objects/HEAD.skin')), [1, 2])
        self.assertEqual(filename('objects/head.skin', 2), 'objects/head_lod2.skin')
        self.assertEqual(source_lods(index, 'objects/body.skin'), {})

    def test_gaps_and_duplicate_case_names_fail(self):
        for names in [('x_lod2.skin',), ('x_lod1.skin', 'X_LOD1.skin')]:
            with self.assertRaises(ValueError):
                source_lods(dict.fromkeys(names), 'x.skin')

    def test_base_and_lower_geometry_keep_their_own_payloads(self):
        blob, _ = sample_skin()
        lower = split_skin_regions(blob, ['keep', 'drop', 'drop', 'drop'])['keep']
        validate_chain(blob, {1: lower})
        files = {}
        emit_regions(files, 'objects/part', {'face': blob}, {1: {'face': lower}})
        self.assertEqual(files, {'objects/part_face.skin': blob, 'objects/part_face_lod1.skin': lower})
        with self.assertRaisesRegex(ValueError, 'triangle count'):
            validate_chain(lower, {1: blob})

    def test_missing_intermediate_region_is_rejected(self):
        blob, _ = sample_skin()
        with self.assertRaisesRegex(ValueError, 'disappears'):
            emit_regions({}, 'objects/part', {'face': blob}, {1: {}, 2: {'face': blob}})

    def test_lod_can_use_bound_slot_not_used_by_base(self):
        blob, _ = sample_skin()
        skin = Skin(blob)
        data = bytearray(skin.subsets.data)
        for i in range(len(skin.subset_records)):
            struct.pack_into('<I', data, 16 + i * 36 + 16, 0)
        blob = write_chunks(skin.chunks, {skin.subsets.id: bytes(data)})
        for i in range(len(skin.subset_records)):
            struct.pack_into('<I', data, 16 + i * 36 + 16, 1)
        lower = write_chunks(skin.chunks, {skin.subsets.id: bytes(data)})
        validate_chain(blob, {1: lower}, material_slots=2)
        with self.assertRaisesRegex(ValueError, 'unbound material'):
            validate_chain(blob, {1: lower}, material_slots=1)

    def test_zero_padded_source_lod_and_ambiguous_alias(self):
        self.assertEqual(source_lods({'x_lod01.skin': None}, 'x.skin'), {1: 'x_lod01.skin'})
        with self.assertRaisesRegex(ValueError, 'Ambiguous'):
            source_lods(dict.fromkeys(('x_lod1.skin', 'x_lod01.skin')), 'x.skin')
