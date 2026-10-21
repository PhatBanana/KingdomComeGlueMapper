import copy
import unittest
import xml.etree.ElementTree as E

from campaign_schedule_routes import plan, assemble
from campaign_entity_links import append_links
from test_campaign_schedule_requests import fixture, message, VALUES


def inputs():
    model, doc, trees = fixture()
    trees['onUpdate']['root']['children'][0]['children'][0]['children'].append(
        message("add(false),handle('work_handle')"))
    scoped = {(doc, 'onUpdate', 'actors[worker]'): '00000001-0000-0000'}
    p = plan(model, scoped)
    objects = E.fromstring('<Objects><Entity EntityId="1" EntityGuid="00000001-0000-0000" EntityClass="NPC" Pos="1,2,3"/>'
        '<Entity EntityId="2" EntityGuid="00000002-0000-0000" EntityClass="SmartObjectHolder" Pos="4,5,6">'
        '<Properties guidSmartObjectType="controller-template"/></Entity></Objects>')
    schedule = E.fromstring('<database><Schedulers><C_SmartHub EntityGuid="1"><Links>'
        '<S_ActivityLink TargetGuid="1"><Parameters BehaviorName="daily_job"/></S_ActivityLink>'
        '</Links></C_SmartHub></Schedulers></database>')
    template = E.fromstring('<SmartEntityTemplate DatabaseId="controller-template" BrainId="keep-brain">'
        '<BehaviorTemplates><SmartBehaviorTemplate Name="public_job" InitialState="Enabled" MaxInstances="-1">'
        '<TreeLocation FileName="imported/q_test/quests/q_test.xml" TreeName="implementation"/>'
        '<Inboxes><InboxTemplate InboxId="keep-inbox" Priority="2"/></Inboxes>'
        '</SmartBehaviorTemplate></BehaviorTemplates></SmartEntityTemplate>')
    activity = E.fromstring('<S_ActivityLink TargetGuid="0" PositioningDelegate="0"><Parameters '
        'BehaviorName="native_wait" TimeOfDayStart="0" TimeOfDayEnd="1440"/></S_ActivityLink>')
    report = dict(namespace='Imported', trees=[dict(owner='q_test', document=doc, tree='implementation', native_emitted=True)])
    files = {'AI/imported/q_test/quests/q_test.xml': b'<BehaviorTrees><BehaviorTree name="implementation"><Root><Success/></Root></BehaviorTree></BehaviorTrees>'}
    policies = {('1','work_handle'): dict(priority=55, urgency='Slow', evidence='fixture native policy contract')}
    return [p, objects, schedule, '00000002-0000-0000', template, activity, report, files, policies, 'Imported']


class ScheduleRoutesTests(unittest.TestCase):
    def test_source_add_remove_retain_guards_and_share_one_handle(self):
        args = inputs()
        self.assertEqual(len(args[0]['leases']), 1)
        lease = args[0]['leases'][0]
        self.assertEqual([s['add'] for s in lease['sites']], [True, False])
        self.assertEqual(lease['sites'][0]['path'], 'Root/0/0/0')
        self.assertEqual([a['op'] for a in lease['sites'][0]['ancestors']], ['Root','Behavior','Sequence'])

    def test_assembly_preserves_baseline_and_controller_scope(self):
        args = inputs(); before = copy.deepcopy(args)
        world, schedule, template, links, report = assemble(*args)
        self.assertEqual([E.tostring(args[i]) for i in (1,2,4,5)], [E.tostring(before[i]) for i in (1,2,4,5)])
        self.assertEqual(args[0], before[0])
        self.assertEqual(len(world), 3)
        activities = schedule.findall("Schedulers/C_SmartHub[@EntityGuid='1']/Links/S_ActivityLink")
        self.assertEqual(activities[0].find('Parameters').get('BehaviorName'), 'daily_job')
        # immediate(true) is not silently turned into Instant.
        self.assertEqual(activities[1].find('Parameters').get('Urgency'), 'Slow')
        self.assertEqual(activities[1].get('TargetGuid'), '2')
        bs = list(template.find('BehaviorTemplates'))
        self.assertEqual(bs[0].get('InitialState'), 'Enabled')
        self.assertEqual(bs[1].get('InitialState'), 'Disabled')
        self.assertEqual(E.tostring(bs[0].find('TreeLocation')), E.tostring(bs[1].find('TreeLocation')))
        self.assertEqual(bs[1].find('Inboxes/InboxTemplate').get('InboxId'), 'keep-inbox')
        self.assertEqual(template.get('BrainId'), 'keep-brain')
        self.assertNotIn('PreventsMonsterLod', bs[1].attrib)
        self.assertEqual(len(E.fromstring(append_links(None,links)).findall('WaitingLinks/WaitingLink')),2)
        self.assertFalse(report['publication_ready']); self.assertFalse(report['runtime_validated'])

    def test_same_callback_on_two_handles_has_separate_availability(self):
        args=inputs(); lease=copy.deepcopy(args[0]['leases'][0]); lease['handle']='another_handle'
        args[0]['leases'].append(lease)
        args[8][('1','another_handle')]=dict(args[8][('1','work_handle')])
        _,_,template,_,report=assemble(*args)
        self.assertEqual(len({r['behavior'] for r in report['routes']}),2)
        self.assertEqual(len(template.find('BehaviorTemplates')),3)

    def test_scoped_actor_binding_is_required(self):
        m, doc, _=fixture()
        with self.assertRaisesRegex(ValueError,'scoped world binding'): plan(m,{})
        with self.assertRaisesRegex(ValueError,'not imported'): plan(m,{},[(doc,'unknown')])

    def test_other_imported_quests_are_not_treated_as_this_controller(self):
        m,doc,_=fixture()
        m['behavior_documents']['libs/ai/quests/q_other.xml']=copy.deepcopy(m['behavior_documents'][doc])
        p=plan(m,{(doc,'onUpdate','actors[worker]'):'00000001-0000-0000'})
        self.assertEqual(len(p['leases']),1)

    def test_actor_this_is_not_mistaken_for_controller_in_callback(self):
        m,doc,trees=fixture()
        trees['implementation']['root']['children']=[message()]
        bindings={(doc,t,'actors[worker]'):'00000001-0000-0000' for t in ('onUpdate','implementation')}
        with self.assertRaisesRegex(ValueError,'actor, not the owning controller'):plan(m,bindings)

    def test_remove_without_add_or_conflicting_replacement_is_blocked(self):
        m,doc,trees=fixture(); seq=trees['onUpdate']['root']['children'][0]['children'][0]
        binding={(doc,'onUpdate','actors[worker]'):'00000001-0000-0000'}
        seq['children']=[message("add(false),handle('work_handle')")]
        with self.assertRaisesRegex(ValueError,'no resolved addition'): plan(m,binding)
        seq['children']=[message(),message(VALUES.replace('priority(55)','priority(56)'))]
        with self.assertRaisesRegex(ValueError,'replacement conversion'):plan(m,binding)

    def test_unconverted_or_wrong_callback_never_gets_a_route(self):
        for kind in ('blocked','missing_file','wrong_tree','wrong_registration'):
            args=inputs()
            if kind=='blocked':args[6]['trees'][0]['native_emitted']=False
            elif kind=='missing_file':args[7].clear()
            elif kind=='wrong_tree':args[7][next(iter(args[7]))]=b'<BehaviorTrees/>'
            else:args[4].find('.//TreeLocation').set('TreeName','different')
            before=[E.tostring(args[i]) for i in (1,2,4)]
            with self.subTest(kind=kind), self.assertRaises(ValueError):assemble(*args)
            self.assertEqual(before,[E.tostring(args[i]) for i in (1,2,4)])

    def test_missing_policy_or_late_failure_is_atomic(self):
        args=inputs(); lease=copy.deepcopy(args[0]['leases'][0]);lease['handle']='second'
        args[0]['leases'].append(lease) # first route succeeds internally, second lacks policy
        before=[E.tostring(args[i]) for i in (1,2,4)]
        with self.assertRaisesRegex(ValueError,'evidenced mapping'):assemble(*args)
        self.assertEqual(before,[E.tostring(args[i]) for i in (1,2,4)])

    def test_controller_identity_mismatch_and_ambiguous_entities_fail(self):
        args=inputs();args[4].set('DatabaseId','wrong')
        with self.assertRaisesRegex(ValueError,'identity mismatch'):assemble(*args)
        args=inputs();args[1].append(copy.deepcopy(args[1][0]))
        with self.assertRaisesRegex(ValueError,'Ambiguous exported'):assemble(*args)


if __name__=='__main__':unittest.main()
