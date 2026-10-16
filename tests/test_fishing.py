"""Gameplay contract tests using the actual Lua rules, without a game process."""
from pathlib import Path
import unittest
from lupa import LuaRuntime

ROOT = Path(__file__).resolve().parents[1]


class FishingTests(unittest.TestCase):
    def setUp(self):
        self.lua = LuaRuntime(unpack_returned_tuples=True)
        self.lua.execute((ROOT / 'tools/fishing_game.lua').read_text())

    def test_one_bite_click_rewards_immediately_and_only_once(self):
        self.lua.execute("""
            local R=GMFishingRules
            local s=R.new(0,function() return .5 end,1)
            assert(R.tick(s,1)=='wait' and s.endsAt==61)
            assert(s.biteAt==31.5)
            assert(R.tick(s,31.5)=='bite')
            assert(R.press(s,31.6)=='leave' and s.result=='caught')
            assert(R.tick(s,31.6)=='reward')
            assert(R.tick(s,40)==nil and R.press(s,40)==nil)
        """)

    def test_missed_bite_finishes_at_sixty_seconds_without_reward(self):
        self.lua.execute("""
            local R=GMFishingRules
            for _,random in ipairs({0,1}) do
                local s=R.new(0,function() return random end,1)
                R.tick(s,1)
                assert(s.biteAt>=4 and s.biteAt<=59)
                assert(R.tick(s,s.biteAt)=='bite')
                if s.deadline<61 then
                    assert(R.tick(s,s.deadline)=='missed')
                    assert(R.tick(s,60.99)==nil)
                end
                assert(R.tick(s,61)=='leave' and s.result=='timeout')
                assert(R.tick(s,61)=='failed')
            end
        """)

    def test_early_late_or_stalled_clicks_do_not_catch(self):
        self.lua.execute("""
            local R=GMFishingRules
            local s=R.new(0,function() return 0 end,1)
            R.tick(s,1)
            assert(R.press(s,2)=='leave' and s.result=='early')
            assert(R.tick(s,2)=='failed')
            s=R.new(0,function() return 0 end,1);R.tick(s,1)
            assert(R.tick(s,20)=='missed')
            assert(R.press(s,21)=='leave' and s.result~='caught')
            s=R.new(0,function() return 0 end,1)
            assert(R.tick(s,90)=='leave' and s.result=='timeout')
            assert(R.tick(s,90)=='failed')
        """)

    def test_aim_accepts_water_from_shallows_or_high_banks(self):
        self.lua.execute(''' 
            local R=GMFishingRules
            local w={bounds={-20,-20,20,20},points={{-20,-20,0},{20,-20,0},{20,20,0},{-20,20,0}}}
            local ground=function() return -1 end
            assert(R.aim({w},{x=0,y=0,z=1.4},{x=1,y=0,z=-.2},ground))
            assert(R.aim({w},{x=0,y=0,z=8},{x=1,y=0,z=-1},ground))
            assert(not R.aim({w},{x=0,y=0,z=2},{x=1,y=0,z=1},ground))
            assert(not R.aim({w},{x=0,y=0,z=2},{x=1,y=0,z=0},ground))
            assert(not R.aim({w},{x=0,y=0,z=2},{x=0,y=0,z=0},ground))
            assert(not R.aim({w},{x=0,y=0,z=2},{x=1,y=0,z=-1},function() return 0/0 end))
        ''')

    def test_aim_stops_at_land_before_water(self):
        self.lua.execute('''
            local w={bounds={4,-10,20,10},points={{4,-10,0},{20,-10,0},{20,10,0},{4,10,0}}}
            local t,r=GMFishingRules.aim({w},{x=0,y=0,z=2},{x=1,y=0,z=-.2},
                function(x,y) return x<4 and 2 or -1 end)
            assert(t==nil and r=='land')
        ''')

    def test_runtime_lua_parses(self):
        self.lua.compile((ROOT / 'tools/fishing_runtime.lua').read_text())
        self.lua.compile((ROOT / 'tools/fishing_visuals.lua').read_text())
        self.lua.compile((ROOT / 'tools/fishing_interaction.lua').read_text())

    def test_native_interaction_gates_and_dispatches_cast_catch_and_cancel(self):
        self.lua.execute('''
            _time=0;player={};safe=true;held=true;owned=true;water=true;casts=0;cancels=0;removed=0
            GMFishing={safe=function() return safe end,held=function() return held end,ownsRod=function() return owned end,
                bank=function() if water then return {x=10,y=0,z=0} end end,
                act=function() casts=casts+1 end,cancel=function() cancels=cancels+1 end}
            System={GetEntityByName=function() end,RemoveEntity=function() removed=removed+1 end,
                GetViewCameraPos=function() return {x=0,y=0,z=2} end,
                GetViewCameraDir=function() return {x=1,y=0,z=-.1} end,
                SpawnEntity=function(args)
                    assert(args.class=='InteractionTrigger')
                    return {id=1,SetMaterial=function() end,SetLocalScale=function() end,
                        SetWorldPos=function(self,p) self.pos=p end}
                end}
            inr_scriptTrigger=7;AHT_PRESS=1
            function Action()
                local a={}
                for _,key in ipairs({'hint','action','func','interaction','hintType','enabled'}) do
                    local k=key;a[k]=function(self,v) self['_'..k]=v;return self end
                end
                return a
            end
            function AddInteractorAction(out,fast,a) out[#out+1]=a end
        ''')
        self.lua.execute((ROOT/'tools/fishing_interaction.lua').read_text())
        self.lua.execute('''
            local I,F=GMFishingInteraction,GMFishing
            I:update(F,true);assert(I.entity)
            local a=I.actions(I.entity,player,false)[1]
            assert(a._hint=='@gm_fishing_action_fish' and a._action=='trigger_use')
            a._func(I.entity,player);assert(casts==1)
            F.session={phase='waiting'};I.used(I.entity,player);assert(cancels==1)
            F.session.phase='bite'
            a=I.actions(I.entity,player,false)[1]
            assert(a._hint=='@gm_fishing_action_catch')
            I.used(I.entity,player);assert(casts==2)
            I.used(I.entity,{});assert(casts==2)
            F.session=nil;water=false
            assert(#I.actions(I.entity,player,false)==0)
            I:update(F,true);assert(I.entity==nil and removed==1)
            water=true;held=false;assert(I:hint(F)=='fish')
            owned=false;assert(I:hint(F)==nil);owned=true
            held=true;safe=false;assert(I:hint(F)==nil)
            safe=true;F.cooldown=2;assert(I:hint(F)==nil)
            _time=3;assert(I:hint(F)=='fish')
        ''')

    def test_gravity_flight_lands_on_target_and_habitat_changes_catch(self):
        self.lua.execute('''
            local R=GMFishingRules
            local f=R.flight({x=0,y=0,z=2},{x=12,y=7,z=0})
            local p=R.projectile(f,f.duration)
            assert(math.abs(p.x-12)<.00001 and math.abs(p.y-7)<.00001 and math.abs(p.z)<.00001)
            local a=R.projectile(f,0);assert(a.z==2)
            local m=R.projectile(f,f.duration/2);assert(m.z>1)
            local _,river=R.catch('river',function() return .5 end)
            local _,pond=R.catch('pond',function() return .5 end)
            assert(river=='trout' and pond=='perch')
        ''')

    def test_visible_float_dips_for_bite_and_cleanup_removes_all_geometry(self):
        self.lua.execute('''
            math.atan2=math.atan2 or math.atan
            Script={}
            System={GetViewCameraPos=function() return {x=0,y=0,z=2} end,
                GetViewCameraDir=function() return {x=1,y=0,z=0} end,
                RemoveEntity=function() removed=removed+1 end,
                SpawnEntity=function(args)
                    return {id=args.name,SetMaterial=function() end,SetLocalScale=function(self,s) assert(type(s)=='number');self.scale=s end,
                        SetWorldPos=function(self,p) self.pos=p end,
                        SetWorldAngles=function(self,a) self.angles=a;self.scale=1 end}
                end}
            Particle={SpawnEffect=function(name,p,dir,scale)
                ripples=ripples+1;lastRipple=p
                assert(name=='gm_fishing.ripple' and dir.z==1)
            end}
            player={human={GetItemInHand=function() return 'rod' end}}
            HS_RIGHT=0
            XGenAIModule={GetEntityByWUID=function(id)
                assert(id=='rod')
                return {GetHelperPos=function(self,name,localSpace)
                    assert(name=='gm_fishing_tip')
                    return localSpace and {x=0,y=0,z=1.8395473} or rodTip
                end}
            end}
            rodTip={x=1.8,y=0,z=2};removed=0;ripples=0
        ''')
        self.lua.execute((ROOT / 'tools/fishing_visuals.lua').read_text())
        self.lua.execute('''
            local V=GMFishingVisuals
            local tip=V:tip()
            assert(tip.x==1.8 and tip.z==2)
            local original=XGenAIModule.GetEntityByWUID
            XGenAIModule.GetEntityByWUID=function() return nil end
            assert(V:tip()==nil) -- Never manufacture a camera-based endpoint.
            XGenAIModule.GetEntityByWUID=original
            local duration=V:begin({x=10,y=0,z=0},0)
            assert(#V.entities==21)
            for i=1,120 do V:update(i/30,{phase='waiting'}) end
            -- Model the native rotation resetting scale, then verify every rendered
            -- cylinder endpoint (not merely the simulated point array).
            for i,e in ipairs(V.lines) do
                local a=e.angles;local b=V.points[i+1].pos
                local x=e.pos.x+e.scale*math.sin(a.y)*math.cos(a.z)
                local y=e.pos.y+e.scale*math.sin(a.y)*math.sin(a.z)
                local z=e.pos.z+e.scale*math.cos(a.y)
                assert(math.abs(x-b.x)<.00001 and math.abs(y-b.y)<.00001 and math.abs(z-b.z)<.00001)
            end
            assert(ripples==0) -- Landing and idle water remain quiet.
            local resting=V.body.pos.z
            local length=V.lineLength
            rodTip={x=-2,y=3,z=2}
            V:update(4.01,{phase='waiting'})
            assert(V.body.pos.x==10 and V.body.pos.y==0)
            assert(V.points[1].pos.x==-2 and V.points[1].pos.y==3)
            assert(V.points[17].pos.x==10 and V.points[17].pos.y==0)
            assert(V.lineLength>length)
            length=V.lineLength;rodTip={x=8,y=0,z=2}
            V:update(4.02,{phase='waiting'});assert(V.lineLength==length)
            for i=121,180 do V:update(i/30,{phase='bite'}) end
            assert(V.body.pos.z<resting-.1 and ripples==1)
            V:ripple({x=100,y=200,z=-50},1)
            assert(lastRipple.x==10 and lastRipple.y==0 and lastRipple.z==.015)
            -- Bite takes up the visible slack without disconnecting either end.
            local mid=V.points[9].pos
            assert(math.abs(mid.x-(rodTip.x+V.body.pos.x)/2)<.001)
            assert(math.abs(mid.z-(rodTip.z+V.knot.pos.z)/2)<.03)
            V:remove();assert(removed==21 and #V.entities==0 and V.flight==nil)
        ''')

    def test_cast_registration_freezes_original_clip_and_has_scopes(self):
        import sys
        import xml.etree.ElementTree as ET
        sys.path.insert(0,str(ROOT/'tools'))
        from build_fishing import animation_resources, ADB, CONTROLLER, CAST_CLIP, CAST_HOLD, CAST_RELEASE, CAST_START
        source='<AnimDB><FragmentList>'+''.join(
            '<'+name+'><Fragment><AnimLayer/></Fragment></'+name+'>'
            for name in ('FishingCast','FishingIdle','FishingLeave'))+'</FragmentList></AnimDB>'
        result=animation_resources(source,'<TagDefinition><Tags/></TagDefinition>',
                                   '<ControllerDef><FragmentDefs/></ControllerDef>')
        db=ET.fromstring(result[ADB]);control=ET.fromstring(result[CONTROLLER])
        for name in ('GMFishingCast','GMFishingIdle','GMFishingLeave'):
            layer=db.find('FragmentList/'+name+'/Fragment/AnimLayer')
            clips=layer.findall('Animation')
            self.assertTrue(all(c.get('name')==CAST_CLIP for c in clips))
            self.assertEqual(clips[-1].get('speed'),'0')
            self.assertEqual(float(layer.findall('Blend')[-1].get('StartTime')),CAST_HOLD)
            self.assertEqual(control.find('FragmentDefs/'+name).get('scopes'),
                             'FullBody+UpperBody' if name=='GMFishingCast' else 'UpperBody')
        self.assertLess(CAST_RELEASE,1)
        self.assertAlmostEqual(CAST_RELEASE+CAST_START,14.133334159851074*.3367099)
        self.assertLess(CAST_RELEASE,CAST_HOLD-CAST_START)
        self.assertLess(CAST_HOLD,14.133334159851074*.4991038)

    def test_adapter_cancels_on_movement_and_death_and_grants_one_catch(self):
        self.lua.execute('''
            Script={ReloadScript=function() end,SetTimer=function() end}
            GMFishingVisuals={remove=function() end,update=function() end}
            System={GetEntityByName=function() return {} end,LogAlways=function() end}
            notifications={}
            Game={SendInfoText=function() end,ShowItemsTransfer=function(id,n)
                assert(player.inventory.count==1)
                notifications[#notifications+1]={id=id,n=n}
            end}
            HS_RIGHT=0;NULL_ENTITY={};_time=0
            local item={}
            player={
                SetAnimationSpeed=function() end,StopAnimation=function() end,
                actor={IsDead=function() return false end},
                human={HolsterToInventory=function() end,IsInDialog=function() return false end,IsMounted=function() return false end,
                    GetItemInHand=function() return item end,StopAnim=function() end,PlayAnim=function() end},
                soul={IsInCombatDanger=function() return false end},
                inventory={count=0,FindItem=function() return item end,
                    GetCountOfClass=function(self) return self.count end,
                    CreateItem=function(self,id,n) self.count=self.count+n end},
                GetWorldPos=function() return {x=0,y=0,z=0} end
            }
        ''')
        self.lua.execute((ROOT / 'tools/fishing_runtime.lua').read_text())
        self.lua.execute('''
            local F=GMFishing
            F.bank=function() return {x=10,y=0,z=0} end
            F.origin={x=2,y=0,z=0};F.session=GMFishingRules.new(0);F.session.phase="waiting"
            F:update()
            assert(F.session==nil and player.inventory.count==0)
            F.origin={x=0,y=0,z=0};F.session=GMFishingRules.new(0)
            GMFishingRules.finish(F.session,0,'caught')
            _time=5;F:update();F:update();F:update()
            assert(F.session==nil and player.inventory.count==1)
            assert(#notifications==1 and notifications[1].n==1)
            F.session=GMFishingRules.new(5)
            player.actor.IsDead=function() return true end
            F:update()
            assert(F.session==nil and player.inventory.count==1)
            assert(#notifications==1)
            player.actor.IsDead=function() return false end
            local casts=0
            F.act=function() casts=casts+1 end
            _time=10
            assert(F:input('attack_primary_mouse','press'))
            _time=10.1;F:input('attack_primary_mouse','release')
            assert(casts==0)
            _time=11;F:input('attack_primary_mouse','press')
            _time=11.5;F:input('attack_primary_mouse','release')
            F:input('attack_primary_mouse','release')
            assert(casts==0)
            assert(not F:input('unrelated_action','press'))
            F.session=GMFishingRules.new(_time)
            assert(F:input('chat_init_with_focus','press'))
            assert(F.session==nil)
            F.session=nil
            local messages={}
            F.message=function(self,key) messages[#messages+1]=key end
            F.chargeStart=20;F.aimAt=0;F.aimKey=nil;_time=20
            F:aimFeedback();assert(messages[#messages]=='aim_ready')
            F.bank=function() return nil,'land' end
            _time=20.3;F:aimFeedback();assert(messages[#messages]=='bank_land')
            player.human.GetItemInHand=function() return NULL_ENTITY end
            assert(not F:input('attack_primary_mouse','press'))
        ''')

    def test_windup_releases_from_rod_only_at_throw_and_cancel_never_casts(self):
        self.lua.execute('''
            Script={ReloadScript=function() end,SetTimer=function() end}
            System={LogAlways=function() end}
            _time=0;begins=0
            GMFishingVisuals={tip=function() return {x=1,y=2,z=3} end,
                begin=function() begins=begins+1;return 1 end,
                remove=function() end,update=function() end}
            player={GetWorldPos=function() return {x=0,y=0,z=0} end,
                human={HolsterToInventory=function() end,GetItemInHand=function() end,StopAnim=function() end},inventory={}}
        ''')
        self.lua.execute((ROOT/'tools/fishing_runtime.lua').read_text())
        self.lua.execute('''
            local F=GMFishing
            F.safe=function() return true end;F.held=function() return true end;F.ownsRod=function() return true end
            F.message=function() end;F.animate=function() end
            F.bank=function() return {x=10,y=0,z=0} end
            F:act();assert(F.session.phase=='windup' and begins==0)
            _time=F.castRelease-.01;F:update();assert(begins==0)
            _time=F.castRelease;F:update()
            assert(begins==1 and F.session.phase=='casting')
            F:update();assert(begins==1)
            F:cancel(true)
            _time=20;F:act();assert(F.session.phase=='windup')
            F:cancel();assert(F.session==nil)
            _time=20.5;F:update();assert(begins==1)
        ''')

    def test_cancel_stops_frozen_layer_and_does_not_restart_hold(self):
        self.lua.execute('''
            Script={ReloadScript=function() end,SetTimer=function() end}
            System={LogAlways=function() end}
            Game={SendInfoText=function() end}
            stopped={};played={};restored={};_time=10
            GMFishingVisuals={remove=function() end,update=function() end}
            player={human={HolsterToInventory=function() end,GetItemInHand=function() end,StopAnim=function() end,
                PlayAnim=function(self,fragment) played[#played+1]=fragment end},
                SetAnimationSpeed=function(self,slot,layer,speed)
                    assert(slot==0 and speed==1);restored[#restored+1]=layer
                end,
                StopAnimation=function(self,slot,layer)
                    assert(slot==0);stopped[#stopped+1]=layer
                end}
        ''')
        self.lua.execute((ROOT/'tools/fishing_runtime.lua').read_text())
        self.lua.execute('''
            local F=GMFishing
            F.held=function() return true end;F.safe=function() return true end
            -- Cancel an idle pose even without an active session.
            F.animation='GMFishingIdle';F:cancel();F:update();F:update()
            assert(stopped[1]==6 and restored[1]==6 and #played==0)
            -- Cancel an actual cast; retrieve visuals without restarting pose.
            F.animation='GMFishingCast';F.holdAt=11
            F.session=GMFishingRules.new(_time)
            assert(F:input('attack_secondary_mouse','press'))
            assert(stopped[2]==0 and restored[2]==0 and F.holdAt==nil)
            assert(F.session==nil)
            _time=11;F:update();F:update()
            assert(F.session==nil and F.animation==nil and #played==0)
            -- Emergency cancellation must work even when safety becomes false.
            F.animation='GMFishingIdle';F.safe=function() return false end
            assert(F:input('attack_secondary_mouse','press'))
            assert(stopped[3]==6 and F.animation==nil)
            F.safe=function() return true end
            F.animation='GMFishingIdle';F.session=GMFishingRules.new(_time)
            assert(not F:input('moveforward','press',1))
            assert(F.session==nil and F.animation==nil and stopped[4]==6)
        ''')

    def test_lost_level_load_timer_is_restarted_without_duplicate_updates(self):
        self.lua.execute('''
            timers={};_time=0
            Script={ReloadScript=function() end,SetTimer=function(ms,fn)
                assert(ms==33);timers[#timers+1]=fn
            end}
            System={LogAlways=function() end}
        ''')
        self.lua.execute((ROOT/'tools/fishing_runtime.lua').read_text())
        self.lua.execute('''
            local F=GMFishing;local updates=0
            F.update=function() updates=updates+1 end
            F:ensureUpdates();assert(#timers==1)
            F:ensureUpdates();assert(#timers==1)
            local old=timers[1]
            -- Simulate the engine discarding pending timers on level load.
            _time=30;F:ensureUpdates();assert(#timers==2)
            old();assert(updates==0) -- A late obsolete callback cannot duplicate.
            timers[2]();assert(updates==1 and #timers==3)
            _time=30.033;timers[3]();assert(updates==2 and F.lastUpdate==_time)
            F:ensureUpdates();assert(#timers==4)
        ''')

    def test_inventory_draw_cast_cancel_and_load_cleanup(self):
        self.lua.execute('''
            _time=0;HS_RIGHT=0;NULL_ENTITY={};hand=nil;owned=true;ready=false
            draws=0;holsters=0;starts=0;position={x=0,y=0,z=0}
            Script={ReloadScript=function() end,SetTimer=function() end}
            System={LogAlways=function() end,AddCCommand=function() end}
            Game={SendInfoText=function() end};Player={}
            GMFishingVisuals={clearRestored=function() end,remove=function() end,
                update=function() end,tip=function() if ready then return {x=0,y=0,z=2} end end}
            player={inventory={FindItem=function() if owned then return 'rod' end end},
                human={GetItemInHand=function() return hand end,
                    DrawFromInventory=function(self,item,slot,animated)
                        assert(item=='rod' and slot==0 and not animated)
                        draws=draws+1;hand='rod'
                    end,
                    HolsterToInventory=function(self,slot,animated)
                        assert(hand=='rod' and slot==0 and not animated)
                        holsters=holsters+1;hand=nil
                    end,
                    IsWeaponDrawn=function() return hand=='sword' end,
                    HolsterWeapon=function() assert(hand=='sword');hand=nil end,
                    StopAnim=function() end,PlayAnim=function() starts=starts+1 end},
                SetAnimationSpeed=function() end,StopAnimation=function() end,
                GetWorldPos=function() return position end}
        ''')
        self.lua.execute((ROOT/'tools/fishing_runtime.lua').read_text())
        self.lua.execute('''
            local F=GMFishing
            F.safe=function() return true end
            F.bank=function() return {x=10,y=0,z=0} end
            F:act();assert(draws==1 and F.pendingDraw and not F.session)
            _time=.05;F:update();assert(draws==1 and not F.session)
            ready=true;_time=.1;F:update()
            assert(F.pendingDraw==nil and F.session.phase=='windup' and starts==1)
            F:cancel();assert(hand==nil and holsters==1 and F.session==nil)
            -- Restored/native draw of the rod is put away while idle.
            hand='rod';F:update();assert(hand==nil and holsters==2)
            hand='rod';F:init();assert(hand==nil and holsters==3 and starts==1)
            -- An unrelated held object survives cleanup and cannot be replaced.
            hand='quest_prop';F:init();assert(hand=='quest_prop')
            _time=1;F:act();assert(hand=='quest_prop' and draws==1)
            -- A normal weapon is holstered before the fishing draw.
            hand='sword';_time=2;ready=false;F:act()
            assert(draws==2 and hand=='rod' and F.pendingDraw)
            F:input('moveforward','press',1)
            assert(hand==nil and F.pendingDraw==nil and F.session==nil)
            ready=true;_time=2.1;F:update();assert(starts==1)
            -- Failed readiness times out without casting, retrying or duplicating.
            ready=false;_time=3;F:act();assert(draws==3)
            _time=5;F:update();assert(hand==nil and not F.pendingDraw and starts==1)
        ''')


if __name__ == '__main__':
    unittest.main()
