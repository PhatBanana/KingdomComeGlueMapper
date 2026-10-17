-- Native interaction trigger: the engine supplies the rebound keyboard or
-- controller button icon, focus arbitration and action dispatch.
GMFishingInteraction=GMFishingInteraction or {}
local I=GMFishingInteraction

function I:reset()
    local e=self.entity or System.GetEntityByName('gm_fishing_interaction')
    if e then System.RemoveEntity(e.id) end
    self.entity=nil
end

function I:hint(f)
    if not f:safe() or not f:ownsRod() then return nil end
    if f.pendingDraw then return 'retrieve' end
    if f.session then
        return f.session.phase=='bite' and 'catch' or 'retrieve'
    end
    if f.cooldown and _time<f.cooldown then return nil end
    if f:bank() then return 'fish' end
end

function I.actions(entity,user,firstFast)
    local f=GMFishing
    if user~=player then return {} end
    local hint=I:hint(f)
    if not hint then return {} end
    local output={}
    AddInteractorAction(output,firstFast,Action():hint('@gm_fishing_action_'..hint)
        :action('trigger_use'):func(I.used):interaction(inr_scriptTrigger)
        :hintType(AHT_PRESS):enabled(true))
    return output
end

function I.used(entity,user)
    if user~=player then return end
    local f=GMFishing
    local hint=I:hint(f)
    if hint=='retrieve' then f:cancel()
    elseif hint then f:act() end
end

function I:update(f,available)
    if not available or not self:hint(f) then
        if self.entity then self:reset() end
        return
    end
    local p,d=System.GetViewCameraPos(),System.GetViewCameraDir()
    local position={x=p.x+d.x*.9,y=p.y+d.y*.9,z=p.z+d.z*.9}
    if not self.entity then
        local e=System.SpawnEntity({class='InteractionTrigger',name='gm_fishing_interaction',
            position=position,properties={object_Model='objects/special/primitive_sphere.cgf',
                InteractorPriorityOverride=1,
                Click={bIsActive=true,UseMessage='@gm_fishing_action_fish',fActiveDistance=2},
                Hold={bIsActive=false}}})
        if not e then error('Could not create fishing interaction') end
        self.entity=e
        e.GetActions=I.actions
        e:SetMaterial('materials/special/nodraw')
        e:SetLocalScale(.2)
    end
    self.entity:SetWorldPos(position)
end
