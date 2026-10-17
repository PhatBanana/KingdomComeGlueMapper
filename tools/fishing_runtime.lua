-- Engine adapter. Only operates on this mod's world and owned fishing rod.
Script.ReloadScript('Scripts/GMFishing/rules.lua')
Script.ReloadScript('Scripts/GMFishing/water.lua')
Script.ReloadScript('Scripts/GMFishing/visuals.lua')
Script.ReloadScript('Scripts/GMFishing/interaction.lua')
GMFishing = GMFishing or {}
local F=GMFishing
F.rod='__ROD_GUID__'
F.castRelease=tonumber('__CAST_RELEASE__') or .858834
F.castHold=tonumber('__CAST_HOLD__') or 2.1
F.fish='f2e16499-8a27-4acc-a4af-f29e00300507'
function F:message(key)
    -- Visual cast, float dip and ripples carry these states; avoid narrating
    -- every transition across the middle of the screen.
    local quiet={casting=true,wait=true,bite=true,missed=true,cancelled=true,holding=true,put_away=true}
    if quiet[key] then System.LogAlways('GM_FISHING '..key);return end
    if key=='need_bank' then
        local target,reason=self:bank()
        key='bank_'..(reason or 'aim')
    end
    Game.SendInfoText('@gm_fishing_'..key,false)
    System.LogAlways('GM_FISHING '..key)
end

-- Use the engine's primary attack action so mouse press/release drive casting.
-- Other weapons and unrelated actions continue through the existing callback.
function F:input(action,activation,value)
    -- Refresh the proximity prompt even after a level discarded its timer.
    if self:ownsRod() then self:ensureUpdates() end
    if action=='moveforward' or action=='moveback' or action=='moveleft' or action=='moveright'
        or action=='move_forward' or action=='move_backward' or action=='move_left' or action=='move_right'
        or action=='xi_movex' or action=='xi_movey' then
        if activation~='release' and (value==nil or math.abs(value)>.1) then
            if self.session or self.pendingDraw or self.animation or self.chargeStart then self:cancel() end
        end
        return false -- Let the original movement action execute immediately.
    end
    if action=='attack_secondary_mouse' or action=='chat_init_with_focus'
        or action=='focus_follow_init_interactor_press' or action=='chat_focus_follow_init_press' then
        if self.session or self.pendingDraw or self.animation or self.chargeStart then
            if activation=='press' then self:cancel() end
            return true
        end
    end
    if not self:held() or not self:safe() then self.chargeStart=nil;return false end
    self:ensureUpdates()
    if action~='attack_primary_mouse' then return false end
    if self.session then
        if activation=='press' then self:act() end
    elseif not self.pendingDraw then
        self:putAwayRod()
    end
    return true
end

function F:aimFeedback()
    if not self.chargeStart then return end
    if self.aimAt and _time<self.aimAt then return end
    self.aimAt=_time+.2
    local target,reason=self:bank()
    local key=target and 'aim_ready' or ('bank_'..(reason or 'aim'))
    if key~=self.aimKey then
        self:message(key);self.aimKey=key
    end
end

function F:safe()
    return player and player.human and player.inventory and player.soul
        and System.GetEntityByName('gm_rattay_smithing_supplies')
        and player.actor and not player.actor:IsDead()
        and not player.human:IsInDialog() and not player.human:IsMounted()
        and not player.soul:IsInCombatDanger()
end

function F:ownsRod()
    return player and player.inventory and player.inventory:FindItem(self.rod)~=nil
end

function F:putAwayRod()
    if self:held() then player.human:HolsterToInventory(HS_RIGHT,false) end
    self.wasHeld=false
end

function F:held()
    if not player or not player.inventory or not player.human then return false end
    local item=player.inventory:FindItem(self.rod)
    return item~=nil and player.human:GetItemInHand(HS_RIGHT)==item
end

function F:stopAnimation()
    self.holdAt=nil
    if not self.animation then return end
    local layer=self.animation=='GMFishingCast' and 0 or 6
    self.animation=nil
    if player and player.human then
        -- A zero-speed loop never reaches its natural end. Release the action
        -- and its owned layer explicitly; do not stop unrelated body layers.
        player.human:StopAnim()
        player:SetAnimationSpeed(0,layer,1)
        player:StopAnimation(0,layer)
    end
end

function F:animate(fragment)
    self:stopAnimation()
    self.animation=fragment
    player.human:PlayAnim(fragment,'')
end

function F:releaseCast()
    local now=_time
    local ok,duration=pcall(function() return GMFishingVisuals:begin(self.target,now) end)
    if not ok then
        self:cancel(true)
        System.LogAlways('GM_FISHING_VISUAL_ERROR '..tostring(duration))
        self:message('visual_failed');return
    end
    self.session.phase='casting';self.session.deadline=now+duration
    System.LogAlways('GM_FISHING_RELEASE visuals='..tostring(#(GMFishingVisuals.entities or {}))..' flight='..tostring(duration))
end

function F:hold()
    -- Older saves may retain F7's command binding. It no longer draws the rod.
    if self.session or self.pendingDraw then self:cancel() else self:putAwayRod() end
end

function F:bank()
    local p=System.GetViewCameraPos();local dir=System.GetViewCameraDir()
    return GMFishingRules.aim(GMFishingWaters,p,dir,function(x,y)
        return System.GetTerrainElevation({x=x,y=y,z=p.z})
    end)
end

function F:act()
    if not self:safe() then return end
    self:ensureUpdates()
    local now=_time
    if self.lastPress and now-self.lastPress<.2 then return end
    self.lastPress=now
    if self.session then
        if not self:held() then self:cancel();return end
        local event=GMFishingRules.press(self.session,now)
        if event then self:event(event) end
        return
    end
    if self.pendingDraw then return end
    if self.cooldown and now<self.cooldown then return end
    local target=self:bank()
    if not target then self:message('need_bank');return end
    if not self:ownsRod() then self:message('need_rod');return end
    local other=player.human:GetItemInHand(HS_RIGHT)
    if other and other~=NULL_ENTITY and not self:held() then
        if player.human:IsWeaponDrawn() then player.human:HolsterWeapon()
        else self:message('empty_hand');return end
    end
    self.origin=player:GetWorldPos()
    self.pendingDraw={target=target,deadline=now+2,requested=false}
    self:updateDraw()
end

function F:updateDraw()
    local pending=self.pendingDraw
    if not pending then return end
    local p=player:GetWorldPos();local o=self.origin
    if not self:safe() or not self:ownsRod() or _time>=pending.deadline
        or (o and ((p.x-o.x)^2+(p.y-o.y)^2>.0025 or math.abs(p.z-o.z)>.15)) then
        local timedOut=_time>=pending.deadline
        self:cancel()
        if timedOut then self:message('rod_unavailable') end
        return
    end
    if not self:held() then
        local other=player.human:GetItemInHand(HS_RIGHT)
        if not pending.requested and (not other or other==NULL_ENTITY) then
            pending.requested=true
            player.human:DrawFromInventory(player.inventory:FindItem(self.rod),HS_RIGHT,false)
        end
        return
    end
    if not GMFishingVisuals:tip() then return end
    local target=self:bank()
    if not target then self:cancel();return end
    self.pendingDraw=nil
    self:startCast(target)
end

function F:startCast(target)
    local now=_time
    self.origin=player:GetWorldPos();self.target=target
    -- No projectile exists during wind-up. Release it from the moving rod tip
    -- at the native throwing sound, rather than at the mouse release.
    self.session=GMFishingRules.new(now,nil,self.castRelease)
    self.session.phase='windup'
    self:animate('GMFishingCast');self:message('casting')
    self.holdAt=now+self.castHold
end

function F:event(event)
    if event=='wait' then self.origin=player:GetWorldPos() end
    -- The cast fragment freezes its own follow-through; do not interrupt it
    -- when the float lands, which can occur before the hold frame.
    if event=='leave' then
        self.session.deadline=_time
        return self:event(GMFishingRules.tick(self.session,_time))
    end
    if event=='reward' or event=='failed' then
        -- Clear state before inventory mutation: no duplicate reward on retries.
        local result=self.session.result
        local fish,kind=GMFishingRules.catch(self.target and self.target.kind)
        GMFishingVisuals:remove()
        self.session=nil;self.cooldown=_time+2
        self:stopAnimation()
        self:putAwayRod()
        if event=='reward' then
            local before=player.inventory:GetCountOfClass(fish)
            player.inventory:CreateItem(fish,1,1)
            local after=player.inventory:GetCountOfClass(fish)
            if after~=before+1 then self:message('reward_failed');return end
            Game.ShowItemsTransfer(fish,1)
            System.LogAlways('GM_FISHING caught_'..kind)
        else self:message(result or 'escaped') end
    elseif event=='leave' then
        self:message(self.session.result=='caught' and 'landing' or self.session.result)
    else self:message(event) end
end

function F:cancel(immediate)
    self.chargeStart=nil;self.pendingDraw=nil
    self:stopAnimation()
    -- Also cancel the held pose before a cast or after a failed session.
    self:putAwayRod()
    if not self.session then GMFishingVisuals:remove();return end
    self.session=nil;self.cooldown=_time
    GMFishingVisuals:remove()
    self:message('cancelled')
end

function F:update()
    if self.pendingDraw then self:updateDraw() end
    if self.chargeStart and (not self:safe() or not self:held()) then self.chargeStart=nil end
    local held=self:held() and self:safe()
    -- A restored save/native weapon draw must not leave the fishing rod out.
    if held and not self.session and not self.pendingDraw then self:putAwayRod();held=false end
    if not held and self.wasHeld then self:stopAnimation() end
    self.wasHeld=held
    self:aimFeedback()
    if GMFishingInteraction then GMFishingInteraction:update(self,self:ownsRod() and self:safe()) end
    if self.session then
        if not self:safe() or not self:held() then self:cancel(true);return end
        local p=player:GetWorldPos();local o=self.origin
        -- Movement input cancels in every phase. The position fallback only
        -- applies once landed, so the native throw's root motion is not walking.
        if o and (self.session.phase=='waiting' or self.session.phase=='bite')
            and ((p.x-o.x)^2+(p.y-o.y)^2>.0025 or math.abs(p.z-o.z)>.15) then
            self:cancel();return
        end
        if self.holdAt and _time>=self.holdAt then self:animate('GMFishingIdle') end
        if self.session.phase=='windup' and _time>=self.session.deadline then
            self:releaseCast()
            if not self.session then return end
        end
        local event=GMFishingRules.tick(self.session,_time)
        if event then self:event(event) end
        if self.session then GMFishingVisuals:update(_time,self.session) end
    end
end

function F:init()
    self:stopAnimation()
    GMFishingVisuals:clearRestored()
    if GMFishingInteraction then GMFishingInteraction:reset() end
    self.session=nil;self.pendingDraw=nil;self.origin=nil;self.lastPress=nil;self.chargeStart=nil;self.wasHeld=false
    self:putAwayRod()
    self.aimKey=nil;self.aimAt=0;self.aimMessageAt=nil
    if not self.inputHook then
        local previous=Player.OnAction
        self.inputHook=function(actor,action,activation,value)
            if F:input(action,activation,value) then return false end
            if previous then return previous(actor,action,activation,value) end
        end
    end
    Player.OnAction=self.inputHook
    if player then player.OnAction=self.inputHook end
    if not self.commands then
        System.AddCCommand('gm_fishing_hold','GMFishing:hold()','Put away the fishing rod')
        System.AddCCommand('gm_fishing_action','GMFishing:act()','Cast, strike or pull when prompted')
        System.AddCCommand('gm_fishing_cancel','GMFishing:cancel()','Cancel fishing')
        self.commands=true
    end
    self:startUpdates()
    System.LogAlways('GM_FISHING_READY native interaction, mouse cast/catch, right click cancel')
end

function F:ensureUpdates()
    -- Level initialization can discard Script timers after OnLoadAI. Restart
    -- on interaction if the heartbeat went stale; invalidate any older loop.
    if not self.lastUpdate or _time-self.lastUpdate>.25 then self:startUpdates() end
end

function F:startUpdates()
    self.generation=(self.generation or 0)+1
    local generation=self.generation
    self.lastUpdate=_time
    System.LogAlways('GM_FISHING_TICKER generation='..tostring(generation))
    local function update()
        if F.generation~=generation then return end
        F.lastUpdate=_time
        local ok,err=pcall(function() F:update() end)
        if not ok then
            F.session=nil
            pcall(function() GMFishingVisuals:remove() end)
            pcall(function() F:stopAnimation() end)
            F.pendingDraw=nil
            pcall(function() F:putAwayRod() end)
            System.LogAlways('GM_FISHING_ERROR '..tostring(err))
        end
        Script.SetTimer(33,update)
    end
    Script.SetTimer(33,update)
end
