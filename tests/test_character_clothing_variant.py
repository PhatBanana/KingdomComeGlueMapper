import sys
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from character_clothing_variant import resolve_variant


class VariantTests(unittest.TestCase):
    def setUp(self):
        self.part = dict(model='lowered_hood', morph_target='#V_001', armor_archetype_id='79', gender_id='1')
        self.base = dict(self.part, morph_target='', clothing_id='base')

    def test_authored_variant_is_applied_even_with_base_record(self):
        self.assertEqual(resolve_variant(self.part, ['#V_001'], [self.base])[0], '#V_001')

    def test_dedicated_source_shape_preserves_geometry(self):
        variant, report = resolve_variant(self.part, ['#A_shrink'], [self.base])
        self.assertIsNone(variant)
        self.assertEqual(report['base_clothing_ids'], ['base'])
        self.assertEqual(report['requested'], '#V_001')
        self.assertEqual(report['status'], 'source_base_geometry')

    def test_missing_shape_requires_matching_source_evidence(self):
        for rows in ([], [dict(self.base, model='other')], [dict(self.base, gender_id='2')],
                     [dict(self.base, armor_archetype_id='80')]):
            with self.assertRaises(ValueError): resolve_variant(self.part, ['#A_shrink'], rows)

    def test_never_substitutes_different_variant_or_adjustment(self):
        with self.assertRaises(ValueError): resolve_variant(self.part, ['#V_002'], [self.base])
        with self.assertRaises(ValueError):
            resolve_variant(dict(self.part, morph_target='#A_missing'), ['#A_shrink'], [self.base])


if __name__ == '__main__': unittest.main()
