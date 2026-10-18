import sys
from pathlib import Path
import unittest
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from campaign_lua_contracts import tokens, NativeLuaContracts
from test_campaign_behavior import source, catalog
from campaign_behavior import convert_behaviors
import xml.etree.ElementTree as E


class LuaContractTests(unittest.TestCase):
    def test_registered_roles_reuse_native_api_without_changing_lifecycle(self):
        native = {'metaroles': ['CUSTOMER', 'WORKER'], 'lua_contracts': {'LuaWrapper': {
            'onEnter': ["entity.soul:AddMetaRoleByName('NATIVE_EXAMPLE')"],
            'onExit': ["entity.soul:RemoveMetaRoleByName('NATIVE_EXAMPLE')"]}}}
        contracts = NativeLuaContracts(native)
        script = "entity.soul:AddMetaRoleByName('CUSTOMER'); entity.soul:AddMetaRoleByName('WORKER')"
        self.assertTrue(contracts.accepts('LuaWrapper', 'onEnter', script))
        self.assertTrue(contracts.accepts('LuaWrapper', 'onExit', "entity.soul:RemoveMetaRoleByName('CUSTOMER')"))
        for script in ["entity.soul:AddMetaRoleByName('MISSING')",
                       "entity.soul:AddMetaRoleByName('CUSTOMER', false)",
                       "entity.soul:AddMetaRoleByName(data.role)",
                       "entity.soul:AddMetaRoleByName('CUSTOMER'); Unknown()",
                       "other.soul:AddMetaRoleByName('CUSTOMER')"]:
            with self.subTest(script=script):
                self.assertFalse(contracts.accepts('ExecuteLua', 'code', script))
        self.assertFalse(contracts.accepts('LuaGate', 'code', "entity.soul:AddMetaRoleByName('CUSTOMER')"))
        native['lua_contracts']['LuaWrapper'].pop('onExit')
        self.assertFalse(NativeLuaContracts(native).accepts('LuaWrapper', 'onExit',
            "entity.soul:RemoveMetaRoleByName('CUSTOMER')"))

    def test_whitespace_and_comments_do_not_change_native_program(self):
        contracts = NativeLuaContracts({'lua_contracts': {'LuaGate': {'code': ['return not entity:IsReady()']}}})
        self.assertTrue(contracts.accepts('LuaGate', 'code', 'return -- wait\n not entity : IsReady ( )'))
        self.assertTrue(contracts.accepts('LuaGate', 'code', 'return --[=[ comment ]=] not entity:IsReady()'))
        self.assertFalse(contracts.accepts('LuaGate', 'code', 'return notentity:IsReady()'))
        self.assertFalse(contracts.accepts('LuaGate', 'code', 'return not entity:IsReady() --end\r entity:Attack()'))

    def test_string_contents_escapes_and_comment_markers_remain_significant(self):
        for a, b in [("f('a b')", "f('ab')"), ("f('--text')", 'f()'),
                     ("f('a\\nb')", "f('anb')"), ('f([=[a b]=])', 'f([=[ab]=])')]:
            self.assertNotEqual(tokens(a), tokens(b))
        for malformed in ["f('missing)", '--[=[unfinished', 'f(@value)', "f('newline\n')"]:
            self.assertIsNone(tokens(malformed))

    def test_actor_calls_share_verified_api_without_moving_lifecycle(self):
        contracts = NativeLuaContracts({'lua_contracts': {'LuaWrapper': {
            'onEnter': ['entity.soul:RestrictDialog(true)', 'data.flag = true'],
            'onExit': ['entity.soul:RestrictDialog(false)']}}})
        self.assertTrue(contracts.accepts('ExecuteLua', 'code', 'entity.soul : RestrictDialog ( false )'))
        self.assertFalse(contracts.accepts('ExecuteLua', 'code', 'entity.soul:RestrictDialog(data.flag)'))
        self.assertFalse(contracts.accepts('ExecuteLua', 'code', 'data.flag = true'))
        self.assertFalse(contracts.accepts('LuaGate', 'code', 'entity.soul:RestrictDialog(false)'))
        self.assertFalse(contracts.accepts('LuaWrapper', 'onEnter', 'entity.soul:RestrictDialog(false)'))

    def test_execute_lua_retains_source_order_and_exact_code(self):
        script = 'entity.soul : RestrictDialog ( false )'
        model = source('<Root><Sequence><Wait duration="&quot;1&quot;"/><ExecuteLua code="&quot;'+script+'&quot;"/><Success/></Sequence></Root>')
        native = catalog()
        native['nodes']['ExecuteLua'] = dict(attributes=['code'], children=[])
        native['lua_contracts'] = {'LuaWrapper': {'onExit': ['entity.soul:RestrictDialog(false)']}}
        files, _, report = convert_behaviors([model], 'Converted', native)
        self.assertEqual(report['whole_trees_emitted'], 1)
        sequence = E.fromstring(next(iter(files.values()))).find('.//Root/Sequence')
        self.assertEqual([n.tag for n in sequence], ['Wait','ExecuteLua','Success'])
        self.assertEqual(sequence[1].get('code'),script)


if __name__ == '__main__': unittest.main()
