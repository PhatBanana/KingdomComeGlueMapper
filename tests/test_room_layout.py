import copy
from pathlib import Path
import sys
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from room_layout import resolve, check_clearances, geometry, preview_lua, overlaps, footprint, boarded_surface
from forge_loft_layout import LAYOUT, placements
try:
    from lupa import LuaRuntime
except ImportError:
    LuaRuntime=None


class RoomLayoutTests(unittest.TestCase):
    def test_nested_group_rotates_offset_and_item_independently(self):
        layout=dict(origin=(100,200,10),yaw=90,groups={
            'bed':dict(offset=(2,0,0),yaw=90),
            'chest':dict(parent='bed',offset=(1,0,.5))},items=[
                dict(name='box',group='chest',offset=(1,0,0),yaw=-90)])
        p=resolve(layout)[0]
        for a,b in zip(p['position'],(98,202,10.5)):self.assertAlmostEqual(a,b)
        self.assertAlmostEqual(p['yaw_radians'],1.5707963267948966)

    def test_moving_group_moves_only_its_contents(self):
        original=placements();draft=copy.deepcopy(LAYOUT)
        draft['groups']['henry']['offset']=(0,0,0)
        moved=resolve(draft)
        for old,new in zip(original,moved):
            if old['group']=='henry':self.assertNotEqual(old['position'],new['position'])
            else:self.assertEqual(old,new)
        self.assertEqual(original,placements())

    def test_bad_groups_names_and_nonfinite_values_rejected(self):
        bad=[dict(groups={'a':dict(parent='b'),'b':dict(parent='a')},items=[]),
             dict(groups={},items=[dict(name='one',group='missing')]),
             dict(groups={},items=[dict(name='one'),dict(name='one')]),
             dict(groups={},items=[dict(name='one',yaw=float('nan'))])]
        for value in bad:
            with self.subTest(value=value),self.assertRaises(ValueError):resolve(dict(origin=(0,0,0),**value))

    def test_rotated_mesh_not_just_origin_checked_against_ladder(self):
        layout=dict(origin=(0,0,0),items=[dict(name='bed',offset=(2,0,0),yaw=90,footprint=(-.5,-2,.5,2))],
                    clearances=[dict(name='landing',footprint=(-.5,-.5,.5,.5))])
        with self.assertRaisesRegex(ValueError,'bed obstructs landing'):check_clearances(layout)
        layout['items'][0]['yaw']=0
        self.assertEqual(check_clearances(layout)['measured'],1)

    def test_touching_is_not_overlap(self):
        a=[(0,0),(1,0),(1,1),(0,1)];b=[(1,0),(2,0),(2,1),(1,1)]
        self.assertFalse(overlaps(a,b));self.assertTrue(overlaps(a,a))

    def test_unmeasured_meshes_not_claimed_validated(self):
        result=check_clearances(dict(origin=(0,0,0),items=[dict(name='unknown')]))
        self.assertEqual(result['unmeasured'],['unknown']);self.assertFalse(result['navigation_verified'])

    def test_forge_has_three_distinct_owners_and_matching_bed_families(self):
        values=placements();beds=[p for p in values if p['kind']=='bed']
        self.assertEqual({p['owner'] for p in beds},{'player','mother','father'})
        self.assertEqual({p['helper_family'] for p in beds},{'Bed_1Place_High'})
        self.assertTrue(all('/beds/high/' in p['model'] for p in beds))
        self.assertEqual(len({p['position'] for p in beds}),3)
        self.assertGreater(check_clearances(LAYOUT)['measured'],5)

    def test_scaled_floor_may_cross_passage_but_not_ladder_opening(self):
        layout=dict(origin=(0,0,0),items=[dict(name='floor',footprint=(-1,-1,1,1),
            scale=(2,1,.2),walkable_surface=True)],clearances=[dict(name='passage',
            offset=(1.5,0,0),footprint=(-.2,-.2,.2,.2),allow_floor=True)])
        check_clearances(layout)
        layout['clearances'][0]['allow_floor']=False
        with self.assertRaisesRegex(ValueError,'floor obstructs passage'):check_clearances(layout)
        layout['items'][0]['scale']=(0,1,1)
        with self.assertRaises(ValueError):resolve(layout)

    def test_furniture_follows_walls_and_storage_does_not_overlap_beds(self):
        p={e['name']:e for e in placements()}
        self.assertEqual(p['mother_bed']['model'],p['father_bed']['model'])
        self.assertEqual(p['mother_bed']['yaw_radians'],p['father_bed']['yaw_radians'])
        self.assertEqual(LAYOUT['groups']['mother']['offset'][1],LAYOUT['groups']['father']['offset'][1])
        for a,b in [('laundry','table'),('personal_chest','player_bed'),
                    ('family_chest','father_bed'),('table','mother_bed')]:
            with self.subTest(a=a,b=b):self.assertFalse(overlaps(footprint(p[a]),footprint(p[b])))

    def test_board_variation_is_repeatable_and_stays_inside_room(self):
        models=[dict(model='a.cgf',bbox=(-.2,-1,0,.2,1,.1)),
                dict(model='b.cgf',bbox=(-.15,-1.1,0,.15,1.1,.08))]
        args=('boards',models,(0,0,6,7))
        boards=boarded_surface(*args,seed=42)
        self.assertEqual(boards,boarded_surface(*args,seed=42))
        self.assertNotEqual(boards,boarded_surface(*args,seed=43))
        resolved=resolve(dict(origin=(0,0,0),items=boards))
        self.assertGreater(len({b['scale'][:2] for b in boards}),10)
        self.assertEqual({b['yaw'] for b in boards},{0,180})
        for b in resolved:
            for x,y in footprint(b):
                self.assertTrue(0<=x<=6 and 0<=y<=7)

    def test_geometry_is_static_and_preview_namespace_is_required(self):
        p=placements()[0];e=geometry(p)
        self.assertEqual(e.get('EntityClass'),'BasicEntity')
        self.assertEqual(e.find('Properties').get('object_Model'),p['model'])
        self.assertEqual(e.find('Properties/Physics').get('bRigidBody'),'0')
        self.assertEqual(e.find('Properties/Physics').get('Mass'),'-1')
        self.assertIsNone(e.get('Geometry'))
        floor=geometry(dict(p,visual_only=True))
        self.assertEqual(floor.get('EntityClass'),'GeomEntity')
        self.assertEqual(floor.find('Properties/Physics').get('bPhysicalize'),'0')
        with self.assertRaises(ValueError):preview_lua(LAYOUT,'gm_forge_loft_')
        with self.assertRaises(ValueError):geometry(dict(name='bad',model='x.lua'))

    @unittest.skipUnless(LuaRuntime,'Lua runtime not installed')
    def test_preview_repeat_cleanup_and_foreign_entity_protection(self):
        lua=LuaRuntime(unpack_returned_tuples=True)
        lua.execute('''entities={} nextId=0 removed=0
System={
 GetEntityByName=function(name) return entities[name] end,
 RemoveEntity=function(id) for n,e in pairs(entities) do if e.id==id then entities[n]=nil;removed=removed+1 end end end,
 SpawnEntity=function(p)
  nextId=nextId+1
  local e={id=nextId}
  function e:LoadObject(slot,path) self.model=path end
  function e:SetWorldPos(pos) self.pos=pos end
  function e:SetWorldAngles(a) self.angles=a end
  function e:SetLocalScale(s) assert(type(s)=='number'); self.scale=s end
  function e:GetLocalBBox() return {x=-1,y=-1,z=0},{x=1,y=1,z=1} end
  entities[p.name]=e;return e
 end
}''')
        layout=dict(origin=(0,0,0),items=[dict(name='box',model='objects/test.cgf')])
        script=preview_lua(layout,'gm_preview_test_')
        lua.execute(script);lua.execute(script)
        self.assertEqual(lua.globals().nextId,1)
        layout['items'][0]['offset']=(1,2,3)
        lua.execute(preview_lua(layout,'gm_preview_test_'))
        self.assertEqual(lua.globals().entities['gm_preview_test_box'].pos.x,1)
        lua.execute('entities.gm_preview_test_foreign={id=99}')
        layout['items'].append(dict(name='foreign',model='objects/test.cgf'))
        with self.assertRaisesRegex(Exception,'Unowned preview name'):
            lua.execute(preview_lua(layout,'gm_preview_test_'))
        self.assertEqual(lua.globals().removed,0)
        lua.execute(preview_lua(dict(layout,items=[]),'gm_preview_test_'))
        self.assertEqual(lua.globals().removed,1)
        self.assertEqual(lua.globals().entities['gm_preview_test_foreign'].id,99)

    @unittest.skipUnless(LuaRuntime,'Lua runtime not installed')
    def test_preview_paths_are_literal_lua_data(self):
        from room_layout import lua_string
        value='quote"\\ newline\n Žluťoučký'
        got=LuaRuntime().execute('return '+lua_string(value))
        self.assertEqual(got,value)


if __name__=='__main__':unittest.main()
