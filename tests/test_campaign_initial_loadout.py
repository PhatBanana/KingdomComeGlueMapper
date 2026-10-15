import sys
from pathlib import Path
import unittest
import xml.etree.ElementTree as E

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from campaign_initial_loadout import resolve, equipment_sequence, bind_player_before
from campaign_dependency_adapters import SoulAdapter


class Tables:
    def __init__(self):
        self.data = {
            'rpg/soul': [dict(soul_id='actor', initial_clothing_preset_id='outfit', initial_weapon_preset_id='weapons')],
            'item/clothing_preset': [dict(clothing_preset_id='outfit')],
            'item/weapon_preset': [dict(weapon_preset_id='weapons')],
            'item/armor2clothing_preset': [dict(clothing_preset_id='outfit', armor_id='coat')],
            'item/attachment2clothing_preset': [],
            'item/weapon2weapon_preset': [dict(weapon_preset_id='weapons', item_id='arrows', amount='12', is_equipped='False')]}
    def get(self, name): return dict(rows=self.data[name], provenance=[])
    def row(self, name, key, value):
        rows = [r for r in self.data[name] if r[key] == value]
        if len(rows) != 1: raise ValueError('Ambiguous preset')
        return rows[0]


class InitialLoadoutTests(unittest.TestCase):
    def test_native_start_binding_preserves_gate_and_equipped_flags(self):
        graph = b'''<Document><Skald><Project><Assets><SoulAsset Name="actor"/></Assets><Nodes>
          <If Name="new_game_gate"><Edge From="not_started.bool" To="Condition"/></If>
          <Function Name="next"><Edge From="new_game_gate.True" To="Exec"/></Function>
          <Function Name="restore"><Edge From="load.OnLoad" To="Exec"/></Function>
          </Nodes></Project></Skald></Document>'''
        definitions = b'''<Definitions>
          <Definition TypeName="EventMemberFunction"><Properties><Property Name="MethodName" Value="CreateItems"/></Properties></Definition>
          <Definition TypeName="MemberFunction"><Properties><Property Name="MethodName" Value="EquipPlayersItem"/></Properties></Definition>
          </Definitions>'''
        args = (resolve(Tables(),'actor'), {'coat':'native_coat','arrows':'native_arrows'},
                'actor','next','Exec','new_game_gate.True','initial',definitions)
        result = bind_player_before(graph,*args)
        nodes = E.fromstring(result).find('Skald/Project/Nodes')
        self.assertEqual(len(nodes.findall("EventMemberFunction[@MethodName='CreateItems']")),2)
        self.assertEqual(len(nodes.findall("MemberFunction[@MethodName='EquipPlayersItem']")),1)
        for node in nodes.findall("EventMemberFunction[@MethodName='CreateItems']"):
            self.assertEqual(node.find("Constant[@Name='Health']").get('Value'), '1')
            self.assertEqual(node.find("Constant[@Name='Condition']").get('Value'), '1')
        self.assertEqual(nodes.find("Function[@Name='next']/Edge").get('From'),'initial_1_create.OnExec')
        self.assertEqual(nodes.find("Function[@Name='restore']/Edge").get('From'),'load.OnLoad')
        self.assertEqual(nodes.find("If[@Name='new_game_gate']/Edge").get('From'),'not_started.bool')
        self.assertEqual(nodes.find("MemberFunction[@Name='initial_0_equip']/Edge[@To='ItemDescriptor']").get('From'),
                         'initial_0_create.ItemDescriptor')
        with self.assertRaises(ValueError): bind_player_before(result,*args)

    def test_soul_dependency_discovery_includes_instance_outfit(self):
        tables = Tables()
        tables.data['item/clothing_preset'].append(dict(clothing_preset_id='work_outfit'))
        tables.data['item/armor2clothing_preset'].append(dict(clothing_preset_id='work_outfit', armor_id='apron'))
        instances = E.fromstring('''<root><SoulList><Souls><Soul><SharedSoulGuid>actor</SharedSoulGuid>
          <StaticData><InitialClothingDescription><PresetId>work_outfit</PresetId></InitialClothingDescription></StaticData>
          </Soul></Souls></SoulList></root>''')
        plan = SoulAdapter(tables, instances).plan('actor')
        self.assertEqual({d for g,d in plan.dependencies if g == 'items'}, {'coat','arrows','apron'})
        self.assertEqual(len(plan.source['loadouts']), 2)

    def test_source_membership_amount_and_equipped_flag_are_preserved(self):
        plan = resolve(Tables(), 'actor')
        blob, variables = equipment_sequence(plan, {'coat':'native_coat','arrows':'native_arrows'}, 'arbitrary_actor', 'initial')
        sequence = E.fromstring(blob)
        self.assertEqual([n.tag for n in sequence], ['CreateItem','EquipItem','CreateItem'])
        self.assertEqual(sequence[0].get('Target'), '$arbitrary_actor')
        self.assertEqual(sequence[2].get('Amount'), '12')
        self.assertEqual(sequence[1].get('item'), '$initial_0')
        self.assertEqual([v['name'] for v in variables], ['initial_0','initial_1'])
        self.assertNotIn(b'GameStart', blob)

    def test_explicit_empty_weapon_preset_is_valid(self):
        tables = Tables(); tables.data['item/weapon2weapon_preset'] = []
        plan = resolve(tables, 'actor')
        self.assertEqual(plan['presets']['weapon']['members'], [])
        self.assertEqual(plan['dependencies'], ['coat'])

    def test_missing_dependency_and_unsupported_attachments_block_emission(self):
        with self.assertRaisesRegex(ValueError, 'Unconverted initial equipment'):
            equipment_sequence(resolve(Tables(), 'actor'), {}, '__player', 'initial')
        tables = Tables()
        tables.data['item/attachment2clothing_preset'] = [dict(clothing_preset_id='outfit', attachment_id='cape')]
        with self.assertRaisesRegex(ValueError, 'attachments require conversion'): resolve(tables, 'actor')

    def test_missing_preset_is_not_treated_as_empty_outfit(self):
        tables = Tables(); tables.data['item/clothing_preset'] = []
        with self.assertRaises(ValueError): resolve(tables, 'actor')


if __name__ == '__main__': unittest.main()
