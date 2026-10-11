from pathlib import Path
import json
import sys
import unittest
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from skalitz_acceptance import source_inventory, acceptance_cases, controller_gaps, probe_lua, evaluate, lua_string


class SkalitzAcceptanceTests(unittest.TestCase):
    def fixture(self):
        profiles = b'<Root><GameProfile><Name>opening</Name><GameLayers><GameLayer>Actors{AB}</GameLayer></GameLayers></GameProfile></Root>'
        souls = b'''<Root><SoulList><Souls><Soul><EntityGuid>255</EntityGuid><Guid>soul</Guid><Name>mother</Name>
        <StaticData><InventoryId>source-items</InventoryId><InitialAIData><BrainId>source-brain</BrainId>
        <Activities><Activity><Time>0:00</Time></Activity><Activity><Time>8:00</Time></Activity></Activities>
        </InitialAIData></StaticData></Soul></Souls></SoulList></Root>'''
        layer = b'''<Objects><Entity Name="mother" EntityClass="NPC_Female" EntityGuid="FF" Pos="1,2,3">
        <EntityLinks><Link Name="bed" TargetGuid="AB"/></EntityLinks></Entity>
        <Entity Name="door" EntityClass="AnimDoor" EntityGuid="AB" Pos="4,5,6"><Properties Locked="1"/></Entity></Objects>'''
        return profiles, souls, {'Layers/Actors{AB}.xml': layer}

    def manifest(self):
        inventory = source_inventory(*self.fixture(), 'opening')
        return dict(destination_level='kcd1_rataje', inventory=inventory, acceptance=acceptance_cases(inventory))

    def test_keeps_source_soul_schedule_and_links(self):
        record = self.manifest()['inventory']['entities'][0]
        self.assertEqual(record['soul']['fields']['StaticData/InventoryId'], 'source-items')
        self.assertEqual(record['soul']['fields']['StaticData/InitialAIData/BrainId'], 'source-brain')
        self.assertEqual(record['soul']['fields']['StaticData/InitialAIData/Activities/Activity[1]/Time'], '8:00')
        self.assertEqual(record['links'][0]['TargetGuid'], 'AB')
        self.assertEqual(record['position'], dict(x=1, y=2, z=3))
        self.assertEqual(self.manifest()['inventory']['unresolved'], [])

    def test_missing_soul_is_explicit_not_generic_actor(self):
        profiles, _, documents = self.fixture()
        result = source_inventory(profiles, b'<Root/>', documents, 'opening')
        self.assertNotIn('soul', result['entities'][0])
        self.assertEqual(result['unresolved'][0]['kind'], 'soul_join')

    def test_duplicate_identity_and_missing_layer_are_reported(self):
        profiles, souls, docs = self.fixture()
        key = next(iter(docs))
        docs[key] = docs[key].replace(b'EntityGuid="AB"', b'EntityGuid="FF"')
        result = source_inventory(profiles, souls, docs, 'opening')
        self.assertTrue(any(x['kind'] == 'duplicate_entity_guid' for x in result['unresolved']))
        result = source_inventory(profiles, souls, {}, 'opening')
        self.assertEqual(result['unresolved'][0]['kind'], 'missing_layer')

    def test_unknown_profile_is_not_substituted(self):
        with self.assertRaisesRegex(ValueError, 'missing or ambiguous'):
            source_inventory(*self.fixture(), 'different')

    def test_read_only_probe_gates_level_and_distance(self):
        code = probe_lua(self.manifest(), radius=180)
        self.assertIn('wrong_level', code)
        self.assertIn('not_tested_outside_radius', code)
        self.assertNotIn('SpawnEntity', code)
        self.assertNotIn('SendMessageToEntity', code)
        self.assertNotIn('SetWorldPos', code)
        self.assertIn('behavior_verified=false', code)
        with self.assertRaises(ValueError):
            probe_lua(self.manifest(), count=65)

    def test_presence_never_passes_untested_behaviors(self):
        manifest = self.manifest()
        identity = manifest['inventory']['entities'][0]['source_id']
        result = evaluate(manifest, [dict(ok=True, observations=[dict(source_id=identity, status='present')])])
        self.assertEqual(result['presence_counts']['present'], 1)
        self.assertEqual(result['presence_counts']['not_tested_no_observation'], 1)
        self.assertFalse(result['fully_verified'])
        self.assertTrue(all(c['status'] == 'not_tested' for c in result['acceptance']))

    def test_duplicate_observation_is_error(self):
        manifest = self.manifest()
        identity = manifest['inventory']['entities'][0]['source_id']
        item = dict(source_id=identity, status='present')
        result = evaluate(manifest, [dict(ok=True, observations=[item, item])])
        self.assertEqual(len(result['errors']), 1)

    def test_missing_controller_operations_preserve_exact_tree(self):
        result = controller_gaps({'source.xml': b'<BehaviorTrees><BehaviorTree name="start"><Root><Sequence><EnableProfile profileEnable="authored"/><ExecuteLua code="source"/></Sequence></Root></BehaviorTree></BehaviorTrees>'})
        self.assertEqual(result[0]['tree'], 'start')
        self.assertEqual(result[0]['missing_operation_adapters'], dict(EnableProfile=1, ExecuteLua=1))

    def test_lua_names_cannot_escape_literal(self):
        encoded = lua_string('mother"; error("bad") --\n')
        self.assertNotIn('error', encoded)
        self.assertTrue(encoded.startswith('"\\109'))
        self.assertNotIn('\n', encoded)

    def test_lua_probe_runs_with_streaming_scope(self):
        from lupa import LuaRuntime
        lua = LuaRuntime(unpack_returned_tuples=True)
        lua.execute('''System={GetCVar=function() return 'kcd1_rataje' end}
        local player={GetWorldPos=function() return {x=1,y=2,z=3} end}
        System.GetEntityByName=function(name) if name=='Henry' then return player end end''')
        result = lua.execute(probe_lua(self.manifest(), radius=2))
        self.assertTrue(result['ok'])
        self.assertEqual(result['observations'][1]['status'], 'missing_nearby_entity')
        self.assertEqual(result['observations'][2]['status'], 'not_tested_outside_radius')
        lua.execute("System.GetCVar=function() return 'trosecko' end")
        self.assertEqual(lua.execute(probe_lua(self.manifest()))['status'], 'wrong_level')


if __name__ == '__main__':
    unittest.main()
