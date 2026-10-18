import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
import xml.etree.ElementTree as ET
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'tools'))
from setup_actor_materials import upgrade


class ActorMigrationTests(unittest.TestCase):
    def test_migration_keeps_registration_breaks_links_and_is_idempotent(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); package = root/'package'; (package/'Data').mkdir(parents=True)
            namespace = 'gm_person_123abc'
            table = 'Libs/Tables/Character/CharacterComponent__'+namespace+'.xml'
            material_table = 'Libs/Tables/Character/ClothingMaterial__'+namespace+'.xml'
            travel = package/'Data/gluemappertravel.pak'
            actor = package/('Data/'+namespace+'.pak')
            with zipfile.ZipFile(travel, 'w') as z:
                z.writestr(table, '<database><CharacterComponents><Component Gender="Male"><DerivedComponents><Clothing/></DerivedComponents></Component></CharacterComponents></database>')
                z.writestr('Quests/keep.xml', b'unchanged quest')
                z.writestr('Libs/AI/scheduler.xml', b'unchanged AI')
            with zipfile.ZipFile(actor, 'w') as z: z.writestr('objects/old.skin', b'geometry')
            original = actor.read_bytes(); linked = root/'linked.pak'; os.link(actor, linked)
            def convert(output, component, assets, ns, sex):
                ET.SubElement(component, 'Feature', Name='GarmentBase')
                (output/material_table).write_bytes(b'<database/>')
                (output/'objects/new.dds').write_bytes(b'new texture')
                return [dict(source_shader='illum')]
            with patch('audit_character_bodies.Assets'), patch('character_native_materials.convert_character_materials', side_effect=convert) as converter:
                changed, removed, report = upgrade(package, root)
                self.assertEqual(len(report['actors']), 1)
                self.assertEqual(linked.read_bytes(), original)
                self.assertEqual(removed, [])
                with zipfile.ZipFile(travel) as z:
                    self.assertEqual(z.read('Quests/keep.xml'), b'unchanged quest')
                    self.assertEqual(z.read('Libs/AI/scheduler.xml'), b'unchanged AI')
                    self.assertEqual(z.read(material_table), b'<database/>')
                with zipfile.ZipFile(actor) as z: self.assertEqual(z.read('objects/old.skin'), b'geometry')
                hashes = {n:(package/n).read_bytes() for n in changed}
                self.assertEqual(upgrade(package, root)[0], {})
                self.assertEqual(converter.call_count, 1)
                self.assertEqual(hashes, {n:(package/n).read_bytes() for n in changed})
            self.assertFalse(list(root.glob('actor-upgrade-*')))

    def test_no_actors_needs_no_game_folder(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); (root/'Data').mkdir()
            with zipfile.ZipFile(root/'Data/gluemappertravel.pak', 'w'): pass
            self.assertEqual(upgrade(root, None)[0], {})
