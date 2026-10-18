-- Menu lifecycle comes from a narrowly patched local copy of the retail UI.
-- The experimental New Game route is opt-in while quests/persistence are pending.
local mod = KingdomComeGlueMapper

function mod:OnCampaignMenuEvent(element, instance, event, args)
    if event == "OnButton" and args and args[0] == "GlueMapperPlayKDC1" then
        if not self.startProbe then return end
        local previous = System.GetCVar("wh_sys_BaseLevelId")
        if previous == nil then
            System.LogAlways("[GlueMapper] Native initial-level hook is unavailable; start aborted")
            return
        end
        -- Native New Game deletes every save of the active playline (retail logs
        -- "Deleting all N savegames of playline 0"). Never start without the
        -- engine's own protection switch reading back enabled.
        local keepSaves = System.GetCVar("wh_sys_NoPlaylineDeleting")
        if keepSaves == nil then
            System.LogAlways("[GlueMapper] Native save protection is unavailable; start aborted")
            return
        end
        System.SetCVar("wh_sys_NoPlaylineDeleting", 1)
        if tonumber(System.GetCVar("wh_sys_NoPlaylineDeleting")) ~= 1 then
            System.SetCVar("wh_sys_NoPlaylineDeleting", keepSaves)
            System.LogAlways("[GlueMapper] Native save protection rejected; start aborted")
            return
        end
        self.previousKeepSaves = keepSaves
        self.previousBaseLevel = previous
        local level = tonumber(self.campaignLevelId) or 1000
        System.SetCVar("wh_sys_BaseLevelId", level)
        if tonumber(System.GetCVar("wh_sys_BaseLevelId")) ~= level then
            System.SetCVar("wh_sys_BaseLevelId", previous)
            System.SetCVar("wh_sys_NoPlaylineDeleting", keepSaves)
            System.LogAlways("[GlueMapper] Native initial-level hook rejected the campaign; start aborted")
            return
        end
        self.pendingNewGame = true
        System.LogAlways("[GlueMapper] Requesting native New Game for level " .. tostring(level))
        UIAction.CallFunction("Menu", 0, "GlueMapperNativeCampaignNewGame")
        return
    end
    if event == "GlueMapperRootMenu" and self.pendingNewGame then
        System.SetCVar("wh_sys_BaseLevelId", self.previousBaseLevel)
        System.SetCVar("wh_sys_NoPlaylineDeleting", self.previousKeepSaves)
        self.pendingNewGame = false
        System.LogAlways("[GlueMapper] Restored native initial level on return to root menu")
    end
    if event ~= "GlueMapperNewGameAdded" then return end
    System.LogAlways("[GlueMapper] Native New Game button added")
    -- Script timers do not advance at the title screen. The root lifecycle
    -- event is emitted after its native function, so update directly.
    UIAction.CallFunction("Menu", 0, "AddBasicButton", "GlueMapperPlayKDC1", 0,
        self.campaignMenuLabel or "Play KCD1", self.startProbe and (self.campaignDescription or "Test converted world startup. Original quests are not running yet.") or "The KCD1 campaign is not ready to play yet.", not self.startProbe)
    System.LogAlways("[GlueMapper] Campaign menu entry added; startProbe=" .. tostring(self.startProbe == true))
end

if UIAction and UIAction.RegisterElementListener then
    UIAction.RegisterElementListener(mod, "Menu", 0, "", "OnCampaignMenuEvent")
else
    System.LogAlways("[GlueMapper] Required retail menu API unavailable")
end
