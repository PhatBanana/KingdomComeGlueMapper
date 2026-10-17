-- Pure fishing rules; the engine adapter supplies time, position and input.
GMFishingRules = {}
local R = GMFishingRules

function R.inside(poly, x, y)
    local inside = false
    local j = #poly
    for i = 1, #poly do
        local a, b = poly[i], poly[j]
        if (a[2] > y) ~= (b[2] > y) and x < (b[1]-a[1])*(y-a[2])/(b[2]-a[2])+a[1] then inside = not inside end
        j = i
    end
    return inside
end

function R.surface(poly, x, y)
    local best, height = math.huge, nil
    for i = 1, #poly do
        local a,b = poly[i],poly[i % #poly+1]
        local dx,dy=b[1]-a[1],b[2]-a[2]
        local den=dx*dx+dy*dy
        local t=den>0 and math.max(0,math.min(1,((x-a[1])*dx+(y-a[2])*dy)/den)) or 0
        local distance=(x-a[1]-t*dx)^2+(y-a[2]-t*dy)^2
        if distance<best then best=distance; height=a[3]+t*(b[3]-a[3]) end
    end
    return height
end

-- Ray-march from the actual view camera, stopping at visible terrain/water.
-- Feet, bank slope and the actor's facing direction are deliberately irrelevant.
function R.aim(waters, eye, dir, ground)
    local function finite(n) return type(n)=='number' and n==n and math.abs(n)<math.huge end
    for _,v in ipairs({eye.x,eye.y,eye.z,dir.x,dir.y,dir.z}) do
        if not finite(v) then return nil,'invalid' end
    end
    local length=math.sqrt(dir.x^2+dir.y^2+dir.z^2)
    if length<.001 then return nil,'invalid' end
    local dx,dy,dz=dir.x/length,dir.y/length,dir.z/length
    for step=1,160 do
        local distance=step*.25
        local x,y,z=eye.x+dx*distance,eye.y+dy*distance,eye.z+dz*distance
        local floor=ground(x,y)
        if not finite(floor) then return nil,'invalid' end
        for _,water in ipairs(waters) do
            local b=water.bounds
            if x>=b[1] and y>=b[2] and x<=b[3] and y<=b[4]
                and R.inside(water.points,x,y) then
                local height=R.surface(water.points,x,y)
                if finite(height) and height>floor+.02 and z<=height and eye.z>=height then
                    return {x=x,y=y,z=height,kind=water.kind or 'pond'}
                end
            end
        end
        if z<=floor then return nil,'land' end
    end
    return nil,'aim'
end

function R.flight(start,target)
    local distance=math.sqrt((target.x-start.x)^2+(target.y-start.y)^2)
    local duration=math.max(.7,math.min(2.5,.7+distance/20))
    return {start=start,target=target,duration=duration,
        velocity={x=(target.x-start.x)/duration,y=(target.y-start.y)/duration,
            z=(target.z-start.z)/duration+4.905*duration}}
end

function R.projectile(f,t)
    t=math.max(0,math.min(t,f.duration))
    return {x=f.start.x+f.velocity.x*t,y=f.start.y+f.velocity.y*t,
        z=f.start.z+f.velocity.z*t-4.905*t*t}
end

function R.catch(kind,random)
    local trout=(random or math.random)()<(kind=='river' and .75 or .2)
    return trout and 'f2e16499-8a27-4acc-a4af-f29e00300507' or '9bf17d06-8f2c-4b00-af30-5571fc2bfb0a',
        trout and 'trout' or 'perch'
end

-- One cast lasts at most 60 seconds after landing. One randomly timed bite,
-- one click to catch; no repeated tug/fight sequence.
function R.new(now,random,duration)
    return {phase='casting',deadline=now+(duration or 11),random=random or math.random}
end

function R.finish(s,now,result)
    s.phase='leaving';s.deadline=now;s.result=result
    return 'leave'
end

function R.tick(s,now)
    if s.phase=='done' or s.phase=='windup' then return nil end
    if s.endsAt and now>=s.endsAt and s.phase~='leaving' then
        return R.finish(s,now,'timeout')
    end
    if now<s.deadline then return nil end
    if s.phase=='casting' then
        s.landedAt=s.deadline;s.endsAt=s.landedAt+60
        s.biteAt=s.landedAt+3+math.max(0,math.min(1,s.random()))*55
        s.phase='waiting';s.deadline=s.biteAt
        if now>=s.endsAt then return R.finish(s,now,'timeout') end
        return 'wait'
    elseif s.phase=='waiting' and not s.biteUsed then
        s.biteUsed=true
        -- Do not offer an expired bite after an update stall.
        if now>=s.biteAt+2 then
            s.deadline=s.endsAt;return 'missed'
        end
        s.phase='bite';s.deadline=s.biteAt+2;return 'bite'
    elseif s.phase=='bite' then
        s.phase='waiting';s.deadline=s.endsAt;return 'missed'
    elseif s.phase=='leaving' then
        s.phase='done';return s.result=='caught' and 'reward' or 'failed'
    end
end

function R.press(s,now)
    if s.phase=='done' or s.phase=='windup' then return nil end
    if now>=s.deadline then return R.tick(s,now) end
    if s.phase=='bite' then return R.finish(s,now,'caught')
    elseif s.phase=='waiting' then return R.finish(s,now,'early') end
end
