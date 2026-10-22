"""Room-relative furnishing layouts shared by package builders and Lua previews.

All distances are metres; authored angles are degrees. Footprints are optional
measured model bounds, not navigation data. Native interaction/ownership
contracts remain the responsibility of the consuming converter.
"""
import json
import math
import re
import random
import xml.etree.ElementTree as E


def numbers(values, count, label):
    if len(values) != count or not all(isinstance(v, (int, float)) and math.isfinite(v) for v in values):
        raise ValueError('Invalid '+label)
    return tuple(values)


def transform(position, offset, yaw):
    x, y, z = numbers(offset, 3, 'offset')
    c, s = math.cos(yaw), math.sin(yaw)
    return position[0]+c*x-s*y, position[1]+s*x+c*y, position[2]+z


def boarded_surface(name, models, rectangle, *, columns=18, seed=0, top=0, thickness=.2):
    """Fit measured board variants to a rectangle with repeatable staggered joints.

    Models contain model + bbox (min xyz, max xyz). Width follows each selected
    board's proportions; three unequal lengths and end-for-end rotation break
    repetition. This authors visual geometry, not collision or navigation.
    """
    x0,y0,x1,y1=numbers(rectangle,4,'floor rectangle')
    if x1<=x0 or y1<=y0 or columns<1 or not models or thickness<=0:
        raise ValueError('Invalid boarded surface')
    rng=random.Random(seed)
    chosen=[models[rng.randrange(len(models))] for _ in range(columns)]
    boxes=[numbers(m['bbox'],6,'board bounds') for m in chosen]
    if any(b[3]<=b[0] or b[4]<=b[1] or b[5]<=b[2] for b in boxes):
        raise ValueError('Empty board bounds')
    widths=[(b[3]-b[0])*rng.uniform(.94,1.06) for b in boxes]
    factor=(x1-x0)/sum(widths);x=x0;result=[]
    for col,(model,b,width) in enumerate(zip(chosen,boxes,widths)):
        width*=factor
        # Different joints in every strip, without tiny offcuts at the edges.
        cuts=[y0,y0+(y1-y0)*rng.uniform(.22,.40),y0+(y1-y0)*rng.uniform(.59,.78),y1]
        for row,(start,end) in enumerate(zip(cuts,cuts[1:])):
            flip=rng.choice((False,True));sign=-1 if flip else 1
            sx=(width-.003)/(b[3]-b[0]);sy=(end-start-.003)/(b[4]-b[1])
            result.append(dict(name=f'{name}_{col:02d}_{row:02d}',model=model['model'],kind='prop',
                group='room',offset=(x+width/2-sign*(b[0]+b[3])/2*sx,
                    (start+end)/2-sign*(b[1]+b[4])/2*sy,top-b[5]*thickness),
                yaw=180 if flip else 0,scale=(sx,sy,thickness),visual_only=True,
                walkable_surface=True,footprint=(b[0],b[1],b[3],b[4])))
        x+=width
    return result


def resolve(layout):
    """Resolve named parent groups into stable world placements; never randomize."""
    origin = numbers(layout['origin'], 3, 'room origin')
    yaw = math.radians(numbers((layout.get('yaw', 0),), 1, 'room yaw')[0])
    groups = layout.get('groups', {})
    if 'room' in groups:
        raise ValueError('room is a reserved group name')
    frames = {'room': (origin, yaw)}
    visiting = set()

    def frame(name):
        if name in frames:
            return frames[name]
        if name in visiting or name not in groups:
            raise ValueError('Cyclic or missing layout group: '+name)
        visiting.add(name)
        group = groups[name]
        p, a = frame(group.get('parent', 'room'))
        angle = math.radians(numbers((group.get('yaw', 0),), 1, 'group yaw')[0])
        frames[name] = transform(p, group.get('offset', (0, 0, 0)), a), a+angle
        visiting.remove(name)
        return frames[name]

    for name in groups:
        frame(name)
    result, names = [], set()
    for item in layout['items']:
        name = item['name']
        if not re.fullmatch(r'[a-z][a-z0-9_]*', name) or name in names:
            raise ValueError('Invalid or duplicate layout name: '+name)
        names.add(name)
        scale=numbers(item.get('scale',(1,1,1)),3,'item scale')
        if min(scale)<=0:raise ValueError('Non-positive item scale: '+name)
        p, a = frame(item.get('group', 'room'))
        a += math.radians(numbers((item.get('yaw', 0),), 1, 'item yaw')[0])
        # Offset follows the group's axes, not the item's final rotation.
        p = transform(p, item.get('offset', (0, 0, 0)), frame(item.get('group', 'room'))[1])
        result.append(dict(item, position=p, yaw_radians=a, scale=scale,
                           rotation=(math.cos(a/2), 0, 0, math.sin(a/2))))
    return result


def footprint(item):
    """World XY corners of supplied local min-x/min-y/max-x/max-y bounds."""
    x0, y0, x1, y1 = numbers(item['footprint'], 4, 'footprint')
    if x0 >= x1 or y0 >= y1:
        raise ValueError('Empty footprint: '+item['name'])
    scale=item.get('scale',(1,1,1))
    return [transform(item['position'], (x*scale[0], y*scale[1], 0), item['yaw_radians'])[:2]
            for x, y in ((x0,y0),(x1,y0),(x1,y1),(x0,y1))]


def overlaps(a, b):
    """Separating-axis test for convex footprint polygons; touching is allowed."""
    for polygon in (a, b):
        for p, q in zip(polygon, polygon[1:]+polygon[:1]):
            axis = (p[1]-q[1], q[0]-p[0])
            pa = [x*axis[0]+y*axis[1] for x,y in a]
            pb = [x*axis[0]+y*axis[1] for x,y in b]
            if max(pa) <= min(pb)+1e-9 or max(pb) <= min(pa)+1e-9:
                return False
    return True


def check_clearances(layout, placements=None):
    """Reject measured footprints intruding into authored room-relative keepouts.

    Returns unmeasured names explicitly: passing this check does not claim that
    unmeasured meshes, sloping roofs, collisions or AI paths have been validated.
    """
    placements = resolve(layout) if placements is None else placements
    zones = resolve(dict(layout, items=layout.get('clearances', [])))
    for item in placements:
        if 'footprint' not in item:
            continue
        for zone in zones:
            if item.get('walkable_surface') and zone.get('allow_floor',False):continue
            if overlaps(footprint(item), footprint(zone)):
                raise ValueError(item['name']+' obstructs '+zone['name'])
    return dict(measured=sum('footprint' in p for p in placements),
                unmeasured=[p['name'] for p in placements if 'footprint' not in p],
                navigation_verified=False)


def geometry(item):
    """Create the static visual template; converter supplies identity/transform."""
    model = item.get('model', '')
    if not model.lower().endswith(('.cgf', '.cga')):
        raise ValueError('Missing geometry for '+item['name'])
    # BasicEntity loads object_Model before physicalization in SetupModel.
    # Authored solid furniture must not rely on GeomEntity's external slot load.
    visual_only = item.get('visual_only', False)
    node = E.Element('Entity', EntityClass='GeomEntity' if visual_only else 'BasicEntity',
                     CastShadowMinSpec='1', ViewDistRatio='100')
    props = E.SubElement(node, 'Properties', bSaved_by_game='0', bInteractiveCollisionClass='0')
    if visual_only:
        node.set('Geometry', model)
    else:
        props.set('object_Model', model)
    E.SubElement(props, 'Physics', bPhysicalize='0' if item.get('visual_only') else '1', bRigidBody='0',
                 bPushableByPlayers='0', Density='-1', Mass='-1')
    return node


def lua_string(value):
    # Lua 5.1 has no JSON \u escape. Escape UTF-8 bytes using fixed-width decimal.
    return '"'+''.join(chr(b) if 32 <= b < 127 and b not in (34, 92)
                       else '\\%03d' % b for b in value.encode('utf-8'))+'"'


def preview_lua(layout, prefix, *, cleanup=False):
    """Bounded repeatable visual preview; deletes only entities it created.

    A registry also removes obsolete previews when a layout is revised. Never
    registers beds/chests or mutates production entities with matching names.
    """
    if not re.fullmatch(r'gm_preview_[a-z][a-z0-9_]*_', prefix):
        raise ValueError('Use an explicit gm_preview_<room>_ namespace')
    placements = resolve(layout)
    check_clearances(layout, placements)
    items = []
    if not cleanup:
        for p in placements:
            if not p.get('model'):
                continue
            geometry(p)
            pos = ','.join(k+'='+format(v,'.12g') for k,v in zip('xyz',p['position']))
            scale = ','.join(k+'='+format(v,'.12g') for k,v in zip('xyz',p['scale']))
            items.append('{name='+lua_string(prefix+p['name'])+',model='+lua_string(p['model'])+
                         ',pos={'+pos+'},scale={'+scale+'},yaw='+format(p['yaw_radians'],'.12g')+'}')
    return '''local items={%s}
_G.GMRoomPreviews=_G.GMRoomPreviews or {}
local key=%s
local owned=_G.GMRoomPreviews[key] or {}
local wanted={}
-- Check all name collisions before changing the scene.
for _,p in ipairs(items) do
  wanted[p.name]=true
  local e=System.GetEntityByName(p.name)
  if e and owned[p.name]~=e.id then error('Unowned preview name: '..p.name) end
end
for name,id in pairs(owned) do
  if not wanted[name] then
    local e=System.GetEntityByName(name)
    if e and e.id==id then System.RemoveEntity(id) end
    owned[name]=nil
  end
end
_G.GMRoomPreviews[key]=owned
local report={}
for _,p in ipairs(items) do
  local e=System.GetEntityByName(p.name)
  local nonuniform=p.scale.x~=p.scale.y or p.scale.x~=p.scale.z
  -- Lua SetLocalScale accepts a scalar; SetWorldAngles also resets anisotropic
  -- scale. Spawn with the complete transform for nonuniform visual meshes.
  if e and nonuniform then System.RemoveEntity(e.id); e=nil end
  if not e then
    e=System.SpawnEntity({class='GeomEntity',name=p.name,position=p.pos,
      orientation={x=-math.sin(p.yaw),y=math.cos(p.yaw),z=0},scale=p.scale})
  end
  if not e then error('Unable to preview '..p.name) end
  owned[p.name]=e.id
  e:LoadObject(0,p.model)
  if not nonuniform then
    e:SetWorldPos(p.pos)
    e:SetWorldAngles({x=0,y=0,z=p.yaw})
    e:SetLocalScale(p.scale.x)
  end
  local lo,hi=e:GetLocalBBox()
  report[#report+1]={name=p.name,min=lo,max=hi}
end
return {visual_only=true,objects=report}
''' % (','.join(items), lua_string(prefix))


if __name__ == '__main__':
    import argparse
    from pathlib import Path
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('layout',type=Path)
    parser.add_argument('--preview',type=Path)
    parser.add_argument('--prefix',default='gm_preview_room_')
    parser.add_argument('--cleanup',action='store_true')
    args=parser.parse_args()
    layout=json.loads(args.layout.read_text(encoding='utf-8'))
    report=dict(placements=resolve(layout),clearances=check_clearances(layout))
    if args.preview:
        args.preview.write_text(preview_lua(layout,args.prefix,cleanup=args.cleanup),encoding='utf-8')
    print(json.dumps(report,indent=2))
