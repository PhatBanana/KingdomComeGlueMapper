import sys
import tempfile
from pathlib import Path
import unittest
from unittest.mock import patch
import xml.etree.ElementTree as ET

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from character_weapon_inventory import stage


class CarriedInventoryTests(unittest.TestCase):
    def test_actor_without_weapons_keeps_source_inventory_and_clothing(self):
        source = dict(source_id='inventory', status='fixed_items',
                      definition={}, direct_items=[dict(item_id='key',amount='1',health='1')],
                      preset_choices=[], item_dependencies=['key'])
        person = dict(soul=dict(soul_id='actor', inventory_id='inventory'), instance=None)
        character = dict(inventory='original_clothing')
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            (output/'converted').mkdir()
            with patch('campaign_sources.RetailSourceReader'), patch('campaign_dependency_adapters.SourceTables'), \
                 patch('campaign_initial_loadout.resolve', return_value=dict(items=[])), \
                 patch('container_audit.inventory_policy', return_value=source), \
                 patch('container_items.build', return_value=dict(registered_items={'key':'native-key'},
                                                                  item_names={'native-key':'registered_key'})) as importer:
                result = stage(output, output, output, person, character, 'actor', output)
            self.assertEqual(importer.call_args.args[4], {'key'})
            self.assertEqual(character['inventory'], 'actor_equipped')
            root = ET.fromstring(result['files']['Libs/Tables/item/InventoryPreset__actor_equipped.xml'])
            self.assertEqual([n.get('Name') for n in root.findall('.//InventoryPresetRef')],
                             ['original_clothing','gm_container_loot_inventory'])
            loot = ET.fromstring(result['files']['Libs/Tables/item/InventoryPreset__gm_container_loot_inventory.xml'])
            self.assertEqual(loot.find('.//PresetItem').get('Name'),'registered_key')
            self.assertEqual(loot.find('.//PresetItem').get('Amount'),'1')
