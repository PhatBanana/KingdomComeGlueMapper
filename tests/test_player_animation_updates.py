"""Exercise player lifecycle chaining without changing NPC update policy."""
import sys
import unittest
from pathlib import Path
from lupa import LuaRuntime

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from player_animation_updates import HOOK, patch_player


class PlayerAnimationUpdatesTests(unittest.TestCase):
    def setUp(self):
        self.lua = LuaRuntime(unpack_returned_tuples=True)
        self.lua.execute('''
        calls=0; updates=0
        Player={}
        function Player:CharacterUpdateAlways(slot, value)
            assert(slot==0 and value==true); updates=updates+1; self.enabled=true
        end
        function Player:SetActorModel(model)
            calls=calls+1;self.model=model;self.enabled=false
            return model,nil,17
        end
        function Player:OnInit() calls=calls+1 end
        function Player:OnReset(value) calls=calls+1;return value end
        function Player:OnLoadAI(saved) calls=calls+1;self.saved=saved end
        NPC={SetActorModel=Player.SetActorModel}
        originalNPC=NPC.SetActorModel
        ''')
        self.lua.execute(HOOK.decode())

    def test_model_replacement_reapplies_and_preserves_returns(self):
        self.assertEqual(self.lua.execute('return Player:SetActorModel("a")'), ('a', None, 17))
        self.lua.execute('Player:SetActorModel("b")')
        self.assertTrue(self.lua.eval('Player.enabled'))
        self.assertEqual(self.lua.eval('updates'), 2)
        self.assertEqual(self.lua.eval('calls'), 2)

    def test_lifecycle_and_idempotence_without_global_player_binding(self):
        self.lua.execute(HOOK.decode())
        self.lua.execute('Player:OnInit(); Player:OnLoadAI("save")')
        self.assertEqual(self.lua.execute('return Player:OnReset(123)'), 123)
        self.assertEqual(self.lua.eval('updates'), 3)
        self.assertEqual(self.lua.eval('Player.saved'), 'save')
        self.assertTrue(self.lua.eval('NPC.SetActorModel==originalNPC'))

    def test_resource_patch_preserves_existing_hooks(self):
        source=b'function Player:OnInit() end\nfunction Player:OnLoadAI(saved) end\n-- existing horse hook'
        output=patch_player(source)
        self.assertTrue(output.startswith(source))
        self.assertEqual(patch_player(output), output)
        with self.assertRaises(ValueError): patch_player(b'partial')


if __name__ == '__main__': unittest.main()
