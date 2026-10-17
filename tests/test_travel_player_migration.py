"""Travel must not reposition companions or erase later gameplay hooks."""
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from region_travel_companions import remove_horse_recovery, travel_player_resources
from player_animation_updates import HOOK
from lupa import LuaRuntime


class TravelPlayerMigrationTests(unittest.TestCase):
    def setUp(self):
        self.native = b'''Player={}
function Player:OnInit() nativeInit=nativeInit+1 end
function Player:OnLoadAI(...) nativeLoad=nativeLoad+1 end
'''
        self.legacy = (Path(__file__).resolve().parents[1] /
                       'tools/region_travel_horse_recovery.lua').read_bytes()
        self.fishing = b'''
local previous=Player.OnInit
function Player:OnInit(...) previous(self, ...); fishingInit=fishingInit+1 end
'''

    def test_removal_preserves_native_animation_and_later_wrappers(self):
        old = self.native + b'GlueTravelHorseRoadArrivals={}\n' + self.legacy + HOOK + self.fishing
        result = remove_horse_recovery(old)
        self.assertEqual(result, self.native + HOOK + self.fishing)
        self.assertEqual(remove_horse_recovery(result), result)
        lua = LuaRuntime()
        lua.execute('nativeInit=0;nativeLoad=0;fishingInit=0')
        lua.execute(result.decode())
        # No System, Script timers or horse API exists in this harness: neither
        # loading nor initializing a player may attempt to touch a companion.
        lua.execute('Player:OnInit();Player:OnLoadAI();Player:OnInit()')
        self.assertEqual(lua.eval('nativeInit'), 2)
        self.assertEqual(lua.eval('nativeLoad'), 1)
        self.assertEqual(lua.eval('fishingInit'), 2)

    def test_windows_line_endings(self):
        old = (self.native + b'GlueTravelHorseRoadArrivals={}\n' + self.legacy).replace(b'\r\n', b'\n').replace(b'\n', b'\r\n')
        self.assertEqual(remove_horse_recovery(old), self.native.replace(b'\n', b'\r\n'))

    def test_unknown_hook_is_rejected_without_cutting_script(self):
        with self.assertRaises(ValueError):
            remove_horse_recovery(self.native + b'GlueTravelHorseRecovery = unknown')

    def test_fresh_build_only_adds_animation_updates(self):
        result = travel_player_resources(self.native)['Scripts/Entities/actor/player.lua']
        self.assertEqual(result, self.native + HOOK)
        self.assertNotIn(b'GlueTravelHorse', result)


if __name__ == '__main__':
    unittest.main()
