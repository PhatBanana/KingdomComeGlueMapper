import sys
from pathlib import Path
import unittest
import xml.etree.ElementTree as E

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from campaign_intro_activity import plan, emit


SOURCE = b'''<BehaviorTrees>
<BehaviorTree name="onUpdate"><Root><InstantSendMessageToNPC target="t_actors[teacher]" type="daycycle:change"
 values="add(true),name('intro'),immediate(true),once(true),priority(63)"/></Root></BehaviorTree>
<BehaviorTree name="intro"><Root><OnInit><LinkDataFilter tag="QuestPlace" condition="$QuestPlace == 'seat'" Child="spot"/></OnInit>
<Behavior><Parallel successMode="Any" failureMode="Any">
<DistanceGate Origin="" ReferencePt="__player" Low="3" High="6" Negation="false" OpenInMiddle="false" RunLogic="KeepRunning">
<DialogGate Who="this.id" Condition="InDialog" Negation="true" EndDialogInRoot="false" WaitForTwins="false" RunLogic="KeepRunning">
<Sequence><InstantSendMessageToNPC target="this.id" type="dialog:monologRequest" values="alias('test_bark'),lookAtId($__player),priority(2)"/>
<Wait duration="-1" doFail="false" timeType="GameTime"/></Sequence></DialogGate></DistanceGate>
<CallBehavior Target="spot" BehaviorName="use"/></Parallel></Behavior></Root></BehaviorTree></BehaviorTrees>'''


class IntroTests(unittest.TestCase):
    def test_receipt_upgrade_does_not_write_through_staging_hardlink(self):
        import json, os, tempfile
        from setup_quest_introductions import write_report, RECORD
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);baseline=root/'baseline.json';baseline.write_bytes(b'original')
            stage=root/'stage';stage.mkdir();os.link(baseline,stage/RECORD)
            write_report(stage,{'source_plan':{'completion_events':['Success']}})
            self.assertEqual(baseline.read_bytes(),b'original')
            self.assertEqual(json.loads((stage/RECORD).read_text())['source_plan']['completion_events'],['Success'])

    def test_recoverable_failure_does_not_retire_success_only_source_request(self):
        from setup_quest_introductions import bind_completion
        root=E.fromstring(SOURCE)
        request=root.find('.//InstantSendMessageToNPC')
        request.set('values',request.get('values')+",handle('request')")
        body=root.find("BehaviorTree[@name='intro']/Root/Behavior")
        parallel=body[0];body.remove(parallel)
        fuse=E.SubElement(body,'FuseBox');E.SubElement(fuse,'Child').append(parallel)
        E.SubElement(E.SubElement(fuse,'OnSuccess'),'InstantSendMessageToNPC',
            type='daycycle:change',values="add(false),handle('request')")
        policy=plan(E.tostring(root),'intro')
        self.assertEqual(policy['completion_events'],['Success'])
        entry=E.fromstring('<Entry><State Name="test_ended"><Constant Name="DefaultValue" Value="false"/>'
            '<Edge From="test_enable.Success" To="SetTrue"/><Edge From="test_enable.Fail" To="SetTrue"/></State></Entry>')
        with self.assertRaises(ValueError):bind_completion(entry,'test',policy,validate=True)
        self.assertTrue(bind_completion(entry,'test',policy))
        self.assertEqual([n.get('From') for n in entry.findall('.//Edge')],['test_enable.Success'])
        self.assertFalse(bind_completion(entry,'test',policy))
        bind_completion(entry,'test',policy,validate=True)
        fuse.find('OnSuccess/InstantSendMessageToNPC').set('values',"add(false),handle('other')")
        with self.assertRaises(ValueError):plan(E.tostring(root),'intro')

    def test_called_seat_requires_its_own_scheduler_destination(self):
        from setup_quest_introductions import repair_destinations
        report = {'placement':{'quest':'example','source_place_guid':'0000000000000002'},
                  'source_plan':{'tree':'arrival'}}
        mission = E.fromstring('<Objects><Entity Name="gm_schedule_gm_intro_example_arrival_seat" '
            'EntityClass="SmartObjectHolder" EntityGuid="00000002-0000-0000"/></Objects>')
        scheduler = E.fromstring('<database><Schedulers><C_SmartHub EntityGuid="1">'
            '<Links><S_ActivityLink TargetGuid="1"><Parameters BehaviorName="unrelated"/>'
            '</S_ActivityLink></Links></C_SmartHub></Schedulers></database>')
        unrelated = E.tostring(scheduler.find('Schedulers')[0])
        with self.assertRaisesRegex(ValueError, 'Missing smart-object scheduler destination'):
            repair_destinations(mission,scheduler,report)
        self.assertTrue(repair_destinations(mission,scheduler,report,create=True))
        self.assertFalse(repair_destinations(mission,scheduler,report,create=True))
        repair_destinations(mission,scheduler,report)
        self.assertEqual(unrelated,E.tostring(scheduler.find('Schedulers')[0]))
        self.assertEqual(len(scheduler.find('Schedulers')),2)

    def test_destination_repair_rejects_conflicting_or_duplicate_rows(self):
        from campaign_behavior_schedule import destination
        seat=E.fromstring('<Entity EntityClass="SmartObjectHolder" EntityGuid="00000002-0000-0000"/>')
        for rows in ('<Other EntityGuid="2"/>', '<C_SmartHub EntityGuid="2"/><C_SmartHub EntityGuid="2"/>'):
            scheduler=E.fromstring('<database><Schedulers>'+rows+'</Schedulers></database>')
            before=E.tostring(scheduler)
            with self.assertRaisesRegex(ValueError,'Incompatible'):
                destination(scheduler,seat,create=True)
            self.assertEqual(before,E.tostring(scheduler))

    def test_source_identity_and_policy(self):
        p = plan(SOURCE, 'intro')
        self.assertEqual((p['actor_role'],p['place_role'],p['priority'],p['speed']),('teacher','seat',63,'Slow'))
        self.assertEqual((p['low'],p['high'],p['alias'],p['bark_priority']),(3,6,'test_bark',2))

    def test_indefinite_bark_keeps_source_lod_lifetime(self):
        # Success of this parallel branch retires the once-only request. A
        # source prohibition on skipping its wait must survive conversion.
        for value in ('false', 'true'):
            blob = SOURCE.replace(b'timeType="GameTime"',
                                  ('timeType="GameTime" skipInLOD="'+value+'"').encode())
            p = plan(blob, 'intro')
            wait = E.fromstring(emit('example_intro', p)['AI/example_intro.xml']).find('.//Wait')
            self.assertEqual(wait.get('skipInLOD'), value)
            self.assertEqual(wait.get('duration'), "'-1'")
        native = E.fromstring(emit('example_intro', plan(SOURCE, 'intro'))['AI/example_intro.xml'])
        self.assertNotIn('skipInLOD', native.find('.//Wait').attrib)

    def test_unsupported_wait_lifetime_is_not_silently_flattened(self):
        for extra in ('skipInLOD="sometimes"', 'unknownPolicy="false"', 'variation="10s"'):
            with self.subTest(extra=extra), self.assertRaisesRegex(ValueError, 'bark lifetime'):
                plan(SOURCE.replace(b'timeType="GameTime"', ('timeType="GameTime" '+extra).encode()), 'intro')

    def test_native_stance_owns_movement_and_no_animation_loop(self):
        files = emit('example_intro',plan(SOURCE,'intro'))
        root = E.fromstring(files['AI/example_intro.xml'])
        self.assertEqual(root.find('.//CallBehavior').get('Target'),'$workPlace')
        self.assertEqual(root.find('.//EntityContextElement').get('context'),'activity_disableSchedulerLooping')
        self.assertIsNone(root.find('.//Loop'))
        self.assertIsNone(root.find('.//SetSpatialInfo'))
        self.assertEqual(root.find('.//DistanceGate').get('High'),'6')
        self.assertEqual(root.find('.//DialogGate').get('Who'),'$this.id')
        self.assertIn('priority(2)',root.find('.//InstantSendMessageToNPC').get('values'))
        self.assertEqual(root.find('.//Wait').get('duration'),"'-1'")
        self.assertEqual({n.get('EventName') for n in root.iter('Callback_empty')},{"'Success'","'Fail'"})

    def test_editor_forest_is_not_a_second_runtime(self):
        root=E.fromstring(SOURCE)
        import copy
        tree=root.find("BehaviorTree[@name='intro']")
        E.SubElement(tree,'ForestContainer').append(copy.deepcopy(tree.find('Root')))
        self.assertEqual(plan(E.tostring(root),'intro')['place_role'],'seat')

    def test_rejects_changed_semantics(self):
        for old,new in [(b'once(true)',b'once(false)'),(b'BehaviorName="use"',b'BehaviorName="sleep"'),
                        (b'duration="-1"',b'duration="0"'),(b'High="6" Negation="false"',b'High="6" Negation="true"'),
                        (b'Low="3"',b'Low="nan"'),(b'High="6"',b'High="2"')]:
            with self.subTest(old=old),self.assertRaises(ValueError):
                plan(SOURCE.replace(old,new),'intro')

    def test_old_recipe_inserts_intro_in_source_order(self):
        from setup_gameplay import STAGE_IDS
        from setup_package_upgrade import migrate_step_ids
        for missing in ({'quest-introductions'}, {'quest-introductions','gm_guard_interaction'}, set()):
            report={'steps':[{'id':s} for s in STAGE_IDS if s not in missing]}
            migrate_step_ids(report)
            self.assertEqual([s['id'] for s in report['steps']],list(STAGE_IDS))
            migrate_step_ids(report)
            self.assertEqual([s['id'] for s in report['steps']],list(STAGE_IDS))


if __name__ == '__main__': unittest.main()
