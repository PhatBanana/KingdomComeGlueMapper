from pathlib import Path
import sys
import unittest
import xml.etree.ElementTree as ET
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from character_accessories import partition_accessories
from character_person_appearance import source_default_body


class SourceAppearanceFallbackTests(unittest.TestCase):
    def test_nonvisual_equipment_is_preserved_and_missing_garments_are_not_skipped(self):
        class Tables:
            def row(self, *args): return {'armor_archetype_name': 'Ring'}
        ring = dict(kind='cloth', model='', material='', morph_target='', gender_id='3',
                    armor_settings={'armor_type_id':'6'}, armor_archetype_id='x', armor_id='original-item')
        meshes, items = partition_accessories([dict(kind='body', model='body.skin'), ring], Tables())
        self.assertEqual(len(meshes), 1)
        self.assertEqual(items[0]['armor_id'], 'original-item')
        self.assertEqual(items[0]['native_role'], 'Ring')
        with self.assertRaises(ValueError):
            partition_accessories([dict(ring, material='missing.mtl')], Tables())

    def test_missing_modular_body_uses_only_explicit_source_cdf_attachment(self):
        class Assets:
            def get(self, path):
                self.path = path
                return (b'<CharacterDefinition><AttachmentList><Attachment Type="CA_SKIN" AName="body" '
                        b'Binding="source/default.skin" Material="source/default.mtl"/></AttachmentList></CharacterDefinition>',
                        [{'sha256': 'source-evidence'}])
        actor = ET.fromstring('<Entity><Properties fileModel="source/person.cdf" esClothingConfig="male"/></Entity>')
        assets = Assets()
        part = source_default_body(actor, assets)
        self.assertEqual(part['model'], 'source/default.skin')
        self.assertEqual(assets.path, 'source/person.cdf')
        self.assertEqual(part['source_cdf_provenance'][0]['sha256'], 'source-evidence')
        actor.find('Properties').set('esClothingConfig', 'unknown')
        with self.assertRaises(ValueError): source_default_body(actor, assets)


if __name__ == '__main__': unittest.main()
