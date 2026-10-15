import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
import xml.etree.ElementTree as E
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from campaign_combat_contracts import validate_assets, validate_buffs, native_fight_effect
from campaign_combat_runtime import emit
from test_campaign_combat_runtime import fixture


class CombatContractTests(unittest.TestCase):
    def test_native_helper_rejects_unresolved_parent_asset_dependency(self):
        path = 'Quests/Final/Barbora/utils/combat/fighteffect.xml'
        blob = b'<Database><Skald><Module Name="fighteffect"><Nodes><Node><Asset Name="NPC" Alias="parent_only"/></Node></Nodes></Module></Skald></Database>'
        with tempfile.TemporaryDirectory() as directory:
            archive = Path(directory) / 'Scripts.pak'
            with zipfile.ZipFile(archive, 'w') as z:
                z.writestr(path, blob)
            with zipfile.ZipFile(archive) as z:
                with self.assertRaisesRegex(ValueError, 'unresolved dependencies'):
                    native_fight_effect(z)

    def test_fight_uses_native_helper_for_each_resolved_role(self):
        p = fixture(); p['partners'] = ['first', 'second']
        module = E.fromstring(emit('arbitrary_quest_fight', p))
        nodes = module.findall('./Skald/Module/Nodes/fighteffect')
        self.assertEqual(len(nodes), 3)
        self.assertEqual([n.find("Edge[@To='attacker']").get('From') for n in nodes],
                         ['actor', 'partner_0', 'partner_1'])
        self.assertEqual([n.find("Edge[@To='target']").get('From') for n in nodes],
                         ['player', 'actor', 'actor'])
        self.assertFalse(module.findall('./Skald/Module/Nodes/EnableBehavior'))
        self.assertIsNotNone(module.find("./Skald/Module/Definitions/Definition[@File='arbitrary_quest_fight/fighteffect.xml']"))

    def test_concrete_asset_bindings_reject_generic_pointer_mismatch(self):
        module = E.fromstring(emit('example', fixture()))
        assets = E.fromstring('<Assets><SmartObjectAsset Name="scheduler_asset"/><TagPointAsset Name="home_asset"/><SoulAsset Name="npc"/></Assets>')
        instance = E.fromstring('<example><Asset Name="scheduler" Alias="scheduler_asset"/><Asset Name="home" Alias="home_asset"/><Asset Name="actor" Alias="npc"/></example>')
        validate_assets(module, instance, assets)
        module.find("./Skald/Module/Ports/Port[@Name='scheduler']").set('Type', 'wh::xgenaimodule::SmartEntity*')
        with self.assertRaisesRegex(ValueError, 'Unsupported combat asset binding'):
            validate_assets(module, instance, assets)

    def test_persistent_buff_dependency_rejects_effect_and_missing_buff(self):
        buff = fixture()['buffs'][0]
        with tempfile.TemporaryDirectory() as directory:
            game = Path(directory); (game / 'Data').mkdir()
            with zipfile.ZipFile(game / 'Data/Tables.pak', 'w') as z:
                z.writestr('Libs/Tables/rpg/buff.xml', f'<database><buffs><buff buff_id="{buff}" is_persistent="true"/></buffs></database>')
            module = E.fromstring(emit('example', fixture()))
            validate_buffs(module, game, [buff])
            with self.assertRaisesRegex(ValueError, 'Unconverted combat buffs'):
                validate_buffs(module, game, ['missing'])
            effect = E.SubElement(module.find('./Skald/Module/Nodes'), 'BuffEffect')
            E.SubElement(effect, 'Constant', Name='BuffGUID', Value=buff)
            with self.assertRaisesRegex(ValueError, 'Persistent combat buff'):
                validate_buffs(module, game, [buff])


if __name__ == '__main__': unittest.main()
