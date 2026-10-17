"""Executable checks that Play KCD1 never starts native New Game without save protection."""
from pathlib import Path
import unittest
from lupa import LuaRuntime

class CampaignMenuSaveTests(unittest.TestCase):
    def setUp(self, cvars="{wh_sys_BaseLevelId=1, wh_sys_NoPlaylineDeleting=0}", locked="{}"):
        self.lua=LuaRuntime(unpack_returned_tuples=True)
        self.lua.execute('''
        cvars=%s; locked=%s; calls={}; logs={}
        KingdomComeGlueMapper={startProbe=true, campaignLevelId=1001}
        System={GetCVar=function(n) return cvars[n] end,
            SetCVar=function(n,v) if not locked[n] then cvars[n]=v end end,
            LogAlways=function(s) table.insert(logs,s) end}
        UIAction={RegisterElementListener=function() end,
            CallFunction=function(e,i,f) table.insert(calls,{f=f,keep=cvars.wh_sys_NoPlaylineDeleting,level=cvars.wh_sys_BaseLevelId}) end}
        ''' % (cvars, locked))
        self.lua.execute((Path(__file__).resolve().parents[1]/'runtime/campaign_menu.lua').read_text())
    def press(self):
        self.lua.execute('KingdomComeGlueMapper:OnCampaignMenuEvent(nil,0,"OnButton",{[0]="GlueMapperPlayKDC1"})')
    def test_new_game_requested_only_with_protection_enabled(self):
        self.press()
        self.assertEqual(self.lua.eval('#calls'),1)
        self.assertEqual(self.lua.eval('calls[1].f'),'GlueMapperNativeNewGame')
        self.assertEqual(self.lua.eval('calls[1].keep'),1)
        self.assertEqual(self.lua.eval('calls[1].level'),1001)
    def test_root_menu_restores_previous_values(self):
        self.press()
        self.lua.execute('KingdomComeGlueMapper:OnCampaignMenuEvent(nil,0,"GlueMapperRootMenu",nil)')
        self.assertEqual(self.lua.eval('cvars.wh_sys_NoPlaylineDeleting'),0)
        self.assertEqual(self.lua.eval('cvars.wh_sys_BaseLevelId'),1)
    def test_missing_protection_aborts(self):
        self.setUp(cvars="{wh_sys_BaseLevelId=1}")
        self.press()
        self.assertEqual(self.lua.eval('#calls'),0)
        self.assertEqual(self.lua.eval('cvars.wh_sys_BaseLevelId'),1)
        self.assertIn('save protection is unavailable',self.lua.eval("table.concat(logs,';')"))
    def test_rejected_protection_aborts(self):
        self.setUp(locked="{wh_sys_NoPlaylineDeleting=true}")
        self.press()
        self.assertEqual(self.lua.eval('#calls'),0)
        self.assertEqual(self.lua.eval('cvars.wh_sys_BaseLevelId'),1)
        self.assertIn('save protection rejected',self.lua.eval("table.concat(logs,';')"))

if __name__=='__main__':
    unittest.main()
