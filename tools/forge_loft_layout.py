"""Forge loft: family bedding, bedside storage and a compact household corner."""
from room_layout import resolve, check_clearances, boarded_surface

FURNITURE='objects/manmade/common_furniture/'
HOUSEHOLD='objects/manmade/task_specific_props/household/cooking_eating/'
BED_BOUNDS=(-.636391,-.991432,.5364,1.12897)
LAYOUT={
 'origin':(735,3420,67.315),
 'yaw':1,
 'groups':{
  'henry':{'offset':(-2.0,-.1,0),'yaw':0},
  'mother':{'offset':(-.15,2.8,0),'yaw':90},
  'father':{'offset':(2.20,2.8,0),'yaw':90},
  'household':{'offset':(-2.15,2.7,0),'yaw':0},
 },
 'items':[],
 'clearances':[
  {'name':'ladder_landing','offset':(2.6,-3.4,0),'footprint':(-.6,-.7,.6,.5)},
  {'name':'central_passage','offset':(.4,-1.1,0),'footprint':(-.45,-1.3,.45,1.4),'allow_floor':True},
  {'name':'parents_access','offset':(.6,1.5,0),'footprint':(-2.25,-.32,2.25,.32),'allow_floor':True},
 ]
}
def add(name,model,group='room',offset=(0,0,0),yaw=0,**kwargs):
 LAYOUT['items'].append(dict(name=name,model=model,group=group,offset=offset,yaw=yaw,kind='prop',**kwargs))

for role,group in (('player','henry'),('mother','mother'),('father','father')):
 LAYOUT['items'].append(dict(name=role+'_bed',model=FURNITURE+'beds/high/bed_rustic_d.cgf',
  group=group,offset=(0,0,0),kind='bed',owner=role,helper_family='Bed_1Place_High',footprint=BED_BOUNDS,
  subobject='WH_MergeNode007'))
 # Complete native bedding mesh; no separately overlaid cloth across the frame.

for name,owner,group,offset,yaw,shared in (
 ('personal_chest','player','room',(-2.1,-1.95,0),90,True),
 ('family_chest','mother','room',(3.15,-.55,0),270,False)):
 LAYOUT['items'].append(dict(name=name,model='gluebuild/player_chests/1/chest02.cga',group=group,
  offset=offset,yaw=yaw,kind='chest',owner=owner,shared=shared,footprint=(-.700619,-.014058,.700551,.488125)))
add('table',FURNITURE+'tables/table_shabby_d_80_rough.cgf','household',footprint=(-.415629,-.422243,.415626,.424109))
add('jug',HOUSEHOLD+'jugs/jug_b.cgf','household',(-.18,.23,.75041),-14)
add('cup_a',HOUSEHOLD+'cups/cup_a.cgf','household',(.20,.22,.75041),23)
add('cup_b',HOUSEHOLD+'cups/cup_b.cgf','household',(.24,.04,.75041),-31)
add('stool','objects/manmade/task_specific_props/clothing_industry/shoemaking/stool_cobbler.cgf',
 'household',(.20,-1.2,0),0,footprint=(-.243,.002,.243,.602))
add('laundry',FURNITURE+'baskets/basket_laundry.cgf','household',(-.60,-.80,0),-8,
 footprint=(-.318,-.277,.305,.307))
add('linen','objects/manmade/task_specific_props/clothing_industry/tailoring/cloth_folded_a.cgf',
 'household',(-.10,-.20,.76551),0)
add('small_sack',FURNITURE+'sacks/sack_b.cgf',offset=(3.0,.6,.04894),yaw=-17)
# The wall hanger's local mesh is horizontal: its pitch is handled separately
# after the native visual orientation has been checked, not guessed here.

# Fitted boards are visual only: existing floor collision and ladder landing stay.
# The rectangular patch starts north of the landing; nothing spans the opening.
board='objects/manmade/task_specific_props/construction/plank_rough_'
models=[dict(model=board+v+'.cgf',bbox=b) for v,b in (
 ('a',(-.201429,-1.06165,-.0129252,.210651,1.06165,.070535)),
 ('b',(-.170235,-1.05337,-.00591759,.219543,1.0527,.102914)),
 ('c',(-.18689,-1.10217,-.0194599,.18689,1.10209,.0836069)),
 ('d',(-.147815,-1.05005,.00145576,.147814,1.05005,.0880157)),
 ('e',(-.139458,-1.05398,-.00654946,.139459,1.05398,.0649907)))]
LAYOUT['items'].extend(boarded_surface('floor',models,(-2.75,-2.85,3.5,3.65),seed=32407))

def placements():
 result=resolve(LAYOUT)
 check_clearances(LAYOUT,result)
 return result
