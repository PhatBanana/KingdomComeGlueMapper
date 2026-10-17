-- Visible world geometry driven by gravity and a damped buoyancy spring.
-- The flight is analytic; the float settles using bounded simulation substeps.
GMFishingVisuals=GMFishingVisuals or {}
local V=GMFishingVisuals
local function vec(x,y,z) return {x=x,y=y,z=z} end
local function mix(a,b,t) return vec(a.x+(b.x-a.x)*t,a.y+(b.y-a.y)*t,a.z+(b.z-a.z)*t) end

function V:remove()
    for _,e in ipairs(self.entities or {}) do System.RemoveEntity(e.id) end
    self.entities={};self.flight=nil;self.points=nil;self.body=nil;self.cap=nil;self.stem=nil;self.knot=nil
    self.lineLength=nil;self.quill=nil;self.quillTip=nil
end

function V:clearRestored()
    -- Lua tables are not restored with save-game entities. Remove only this
    -- feature's exact names so an old float cannot survive without a session.
    self:remove()
    local names={'float','float_tip','float_stem','float_knot','float_quill','float_quill_tip'}
    for i=1,16 do names[#names+1]='line_'..i end
    for _,name in ipairs(names) do
        local e=System.GetEntityByName('gm_fishing_'..name)
        if e and e.id then System.RemoveEntity(e.id) end
    end
end

function V:entity(name,model,material)
    local e=System.SpawnEntity({class='BasicEntity',name='gm_fishing_'..name,
        position=self.start,properties={object_Model=model,Physics={bPhysicalize=false,bRigidBody=false,Mass=0,Density=0},MultiplayerOptions={bNetworked=false}}})
    if not e then error('Could not spawn fishing '..name) end
    self.entities[#self.entities+1]=e
    e:SetMaterial('Objects/GMFishing/'..material..'.mtl')
    return e
end

function V:tip()
    -- Inventory returns a WUID, not an entity ID. Resolve the drawn item and
    -- query its authored helper in world space, including hand/slot transforms.
    local item=player and player.human:GetItemInHand(HS_RIGHT)
    if not item or item==NULL_ENTITY then return nil end
    local rod=XGenAIModule.GetEntityByWUID(item)
    if not rod or not rod.GetHelperPos then return nil end
    local localTip=rod:GetHelperPos('gm_fishing_tip',true)
    if not localTip or math.abs(localTip.z-1.8395473)>.05 then return nil end
    local p=rod:GetHelperPos('gm_fishing_tip',false)
    if not p or p.x~=p.x or p.y~=p.y or p.z~=p.z then return nil end
    return vec(p.x,p.y,p.z)
end

function V:begin(target,now)
    self:remove();self.start=assert(self:tip(),'Drawn rod tip is unavailable');self.target=target
    self.flight=GMFishingRules.flight(self.start,target);self.started=now
    self.current=nil;self.retrieveFrom=nil;self.retrieving=nil
    self.last=now;self.spring=0;self.velocity=0;self.landed=false;self.biteStarted=nil;self.biteRipple=false
    self.body=self:entity('float','Objects/GMFishing/float.cgf','float')
    self.body:SetLocalScale(1)
    self.stem=self:entity('float_stem','Objects/GMFishing/stem.cgf','stem')
    self.knot=self:entity('float_knot','Objects/GMFishing/knot.cgf','knot')
    self.quill=self:entity('float_quill','Objects/GMFishing/quill.cgf','quill')
    self.quillTip=self:entity('float_quill_tip','Objects/GMFishing/quill_tip.cgf','quill_tip')
    self.lines={};self.points={}
    for i=1,16 do
        self.lines[i]=self:entity('line_'..i,'Objects/GMFishing/line.cgf','line')
    end
    for i=1,17 do self.points[i]={pos=self.start,old=self.start} end
    return self.flight.duration
end

function V:ripple(p,scale)
    -- Every pulse belongs to the fixed water contact point, never the moving
    -- float or rod. Horizontal facing handles the plane without a second tilt.
    local water=self.target
    Particle.SpawnEffect('gm_fishing.ripple',vec(water.x,water.y,water.z+.015),vec(0,0,1),scale or 1)
end

function V:update(now,session)
    if not self.flight then return end
    local dt=math.max(0,math.min(now-self.last,.1));self.last=now
    local tip=assert(self:tip(),'Drawn rod tip was lost');local age=now-self.started;local p
    if session.phase=='leaving' then
        self.retrieveFrom=self.retrieveFrom or self.current or GMFishingRules.projectile(self.flight,age)
        self.retrieving=self.retrieving or now
        p=mix(self.retrieveFrom,tip,math.min(1,(now-self.retrieving)/.8))
    elseif age<self.flight.duration then
        p=GMFishingRules.projectile(self.flight,age)
    else
        if not self.landed then self.landed=true;self.velocity=-.7 end
        if session.phase=='bite' and not self.biteStarted then
            self.biteStarted=now;self.velocity=-1.4
        end
        local desired=session.phase=='bite' and (-.13+.055*math.sin((now-self.biteStarted)*18)) or .003
        local steps=math.max(1,math.ceil(dt/.016));local h=dt/steps
        for i=1,steps do
            self.velocity=self.velocity+(45*(desired-self.spring)-8*self.velocity)*h
            self.spring=self.spring+self.velocity*h
        end
        -- Landing position is world-anchored. Only buoyancy/bites change height;
        -- player movement and camera rotation cannot drag the float sideways.
        p=vec(self.target.x,self.target.y,self.target.z+self.spring+.002*math.sin(age*5))
        -- One subtle surface disturbance when the fish submerges the cork.
        -- No idle, landing, repeated bite or catch pulses.
        if session.phase=='bite' and self.spring<-.015 and not self.biteRipple then
            self.biteRipple=true;self:ripple(self.target,1)
        end
    end
    self.current=p
    self.body:SetWorldPos(p)
    self.quill:SetWorldPos(vec(p.x,p.y,p.z+.052))
    self.quillTip:SetWorldPos(vec(p.x,p.y,p.z+.095))
    self.stem:SetWorldPos(vec(p.x,p.y,p.z-.019))
    -- The wooden stem passes through the cork. Tie the line to its upper end.
    p=vec(p.x,p.y,p.z+.018)
    self.knot:SetWorldPos(p)
    -- Verlet line with endpoint constraints. Its weight produces visible slack.
    local points=self.points
    for i=2,16 do
        local q=points[i];local a,b=q.pos,q.old
        q.old=a;q.pos=vec(a.x+(a.x-b.x)*.94,a.y+(a.y-b.y)*.94,a.z+(a.z-b.z)*.94-2*dt*dt)
    end
    local span=math.sqrt((p.x-tip.x)^2+(p.y-tip.y)^2+(p.z-tip.z)^2)
    -- Pay line out as the float travels. Preserve slack after landing when
    -- Henry steps closer; stepping farther pays out more without moving it.
    if session.phase=='leaving' then self.lineLength=span*1.02
    else self.lineLength=math.max(self.lineLength or 0,span*1.02) end
    -- A fish takes up the slack in a short tug. Keep the actual rod-tip and
    -- water anchors unchanged; never fake a detached moving rod endpoint.
    local taut=session.phase=='bite' and math.min(1,(now-self.biteStarted)/.12) or 0
    local segment=math.max(.001,(self.lineLength*(1-taut)+span*1.002*taut)/16)
    for pass=1,10 do
        points[1].pos=tip;points[17].pos=p
        for i=1,16 do
            local a,b=points[i].pos,points[i+1].pos
            local dx,dy,dz=b.x-a.x,b.y-a.y,b.z-a.z
            local length=math.sqrt(dx*dx+dy*dy+dz*dz)
            if length>.00001 then
                local factor=(length-segment)/length*.5
                if i>1 then points[i].pos=vec(a.x+dx*factor,a.y+dy*factor,a.z+dz*factor) end
                if i<16 then points[i+1].pos=vec(b.x-dx*factor,b.y-dy*factor,b.z-dz*factor) end
            end
        end
    end
    points[1].pos=tip;points[17].pos=p
    if taut>0 then
        for i=2,16 do
            local t=(i-1)/16
            local tight=mix(tip,p,t)
            tight.z=tight.z-.02*math.sin(t*math.pi)
            points[i].pos=mix(points[i].pos,tight,taut)
            points[i].old=points[i].pos
        end
    end
    for i,e in ipairs(self.lines) do
        local a,b=points[i].pos,points[i+1].pos
        local dx,dy,dz=b.x-a.x,b.y-a.y,b.z-a.z
        local length=math.sqrt(dx*dx+dy*dy+dz*dz)
        e:SetWorldPos(a)
        e:SetWorldAngles(vec(0,math.acos(math.max(-1,math.min(1,dz/math.max(length,.00001)))) ,math.atan2(dy,dx)))
        -- SetWorldAngles rebuilds the world matrix with unit scale. Scale LAST
        -- so the unit-length cylinder ends exactly at the next line point.
        e:SetLocalScale(math.max(.0001,length))
    end
end
