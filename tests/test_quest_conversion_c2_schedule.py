"""Converter C2: binding daycycle requests to the lease adapter."""
from pathlib import Path
import sys
import unittest
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
import campaign_controller_contracts as contracts
import campaign_controller_schedule as schedule

DOCUMENT = 'libs/ai/quests/q_example.xml'
ACTOR, OTHER, CONTROLLER = '00000001-0002-0003', '00000004-0005-0006', '00000007-0008-0009'
ADD = "add(true),immediate(true),once(true),handle('h_wait'),sourceId($this.id),name('work'),priority(60)"


def node(op, children=(), **attributes):
    return dict(op=op, attributes=attributes, children=list(children), text='')


def send(values=ADD, target="t_actors['worker']", op='InstantSendMessageToNPC'):
    return node(op, target=target, type='daycycle:change', values=values)


def model(trees, automaton=True):
    entry = node('Root', [node('IncludeTree', File='"final/questUtils.xml"', Name='"cutsceneAutomaton"')] if automaton else [])
    documents = dict(entry=entry, work=node('Root', [node('Success')]), **trees)
    points = [dict(file='quests/q_example.xml', tree='entry', kind='on_update_tree')]
    points += [dict(file='quests/q_example.xml', tree=name, kind='behavior_callback', name=name) for name in documents if name != 'entry']
    return dict(quest='q_example', controller_registration=dict(entry_points=points),
                behavior_documents={DOCUMENT: dict(trees={name: dict(variables=[], root=root if root['op'] == 'Root' else node('Root', [root]))
                                                           for name, root in documents.items()})})


def prepared(trees, **kwargs):
    return contracts.prepare([model(trees, **kwargs)])


REFERENCES = {"t_actors['worker']": ACTOR, "t_actors['other']": OTHER}


class ScheduleTests(unittest.TestCase):
    def test_a_scene_tree_run_by_the_controller_names_the_controller_as_source(self):
        models, report = prepared(dict(cutscene_a=send(), elsewhere=send()))
        trees = models[0]['behavior_documents'][DOCUMENT]['trees']
        self.assertIn('sourceId($__object.id)', trees['cutscene_a']['root']['children'][0]['attributes']['values'])
        self.assertIn('sourceId($this.id)', trees['elsewhere']['root']['children'][0]['attributes']['values'])
        self.assertEqual([r['tree'] for r in report['controller_scope']], ['cutscene_a'])
        models, report = prepared(dict(cutscene_a=send()), automaton=False)
        self.assertEqual(report['controller_scope'], [])

    def test_only_trees_whose_every_request_fits_are_selected(self):
        cases = dict(
            cutscene_ok=send(),
            cutscene_later=send(ADD.replace('immediate(true)', 'immediate(false)').replace('h_wait', 'h_later')),
            cutscene_window=send(ADD.replace('h_wait', 'h_window') + ",startTime('8')"),
            cutscene_unbound=send(ADD.replace('h_wait', 'h_unbound'), target="t_actors['stranger']"),
            cutscene_runtime=send(ADD.replace('h_wait', 'h_runtime'), target='this.id'),
            cutscene_sync=send(ADD.replace('h_wait', 'h_sync'), op='SendMessageToNPC'),
            cutscene_removal=send("add(false),handle('h_gone')"),
            cutscene_mixed=node('Sequence', [send(ADD.replace('h_wait', 'h_mixed')), send("add(false),handle('h_x'),name('work')")]))
        models, _ = prepared(cases)
        trees, bindings, report = schedule.select(models[0], REFERENCES)
        self.assertEqual(trees, {(DOCUMENT, 'cutscene_ok')})
        self.assertEqual(bindings, {(DOCUMENT, 'cutscene_ok', "t_actors['worker']"): ACTOR})
        self.assertEqual(report['rejected'], dict(actor_not_in_level=1, addition_fields=1, removal_without_addition=1,
                                                  next_activity_boundary=1, removal_fields=1, runtime_actor=1,
                                                  synchronous_request=1))
        self.assertEqual(report['sites']['cutscene_removal'], {'Root/0': 'removal_without_addition'})
        self.assertEqual(report['sites']['cutscene_mixed'], {'Root/0/0': 'tree', 'Root/0/1': 'removal_fields'})
        self.assertEqual((report['requests'], report['accepted_requests'], report['accepted_shape_in_a_rejected_tree']), (9, 1, 1))

    def test_a_lease_shared_by_two_trees_needs_one_policy(self):
        same = dict(cutscene_a=send(), cutscene_b=send(), cutscene_c=send("add(false),handle('h_wait')"))
        trees, _, report = schedule.select(prepared(same)[0][0], REFERENCES)
        self.assertEqual((len(trees), report['rejected']), (3, {}))
        differing = dict(same, cutscene_b=send(ADD.replace('priority(60)', 'priority(70)')))
        trees, _, report = schedule.select(prepared(differing)[0][0], REFERENCES)
        self.assertEqual((trees, report['rejected']), (set(), dict(lease_policy=3)))
        self.assertEqual(report['sites'], dict(cutscene_a={'Root/0': 'lease_policy'}, cutscene_b={'Root/0': 'lease_policy'},
                                               cutscene_c={'Root/0': 'lease_policy'}))
        # The controller under its two names is one policy to KCD1 and two to the lease adapter.
        scopes = dict(cutscene_b=send(), cutscene_c=node('Sequence', [send("add(false),handle('h_wait')"),
                                                                                    send(ADD.replace('h_wait', 'h_c').replace('$this.id', '$__object.id'))]))
        models_ = prepared(scopes, automaton=False)[0]
        models_[0]['behavior_documents'][DOCUMENT]['trees']['entry']['root']['children'] = [send()]
        models_[0]['behavior_documents'][DOCUMENT]['trees']['cutscene_b']['root']['children'][0]['attributes']['values'] = \
            ADD.replace('$this.id', '$__object.id')
        trees, _, report = schedule.select(models_[0], REFERENCES)
        self.assertEqual((trees, report['rejected']), (set(), dict(lease_from_two_scopes=3)))
        self.assertEqual(report['sites']['cutscene_c'], {'Root/0/0': 'lease_from_two_scopes', 'Root/0/1': 'tree'})
        # A removal whose addition sits in a tree that waits for another reason waits with it.
        waiting = dict(cutscene_a=node('Sequence', [send(), send(ADD.replace('h_wait', 'h_r'), target='this.id')]),
                       cutscene_c=send("add(false),handle('h_wait')"))
        trees, _, report = schedule.select(prepared(waiting)[0][0], REFERENCES)
        self.assertEqual((trees, report['rejected'], report['sites']['cutscene_c']),
                         (set(), dict(runtime_actor=1, lease_in_a_waiting_tree=1), {'Root/0': 'lease_in_a_waiting_tree'}))
        other_actor = dict(same, cutscene_b=send(ADD.replace('priority(60)', 'priority(70)'), target="t_actors['other']"))
        self.assertEqual(len(schedule.select(prepared(other_actor)[0][0], REFERENCES)[0]), 3)

    def test_the_adapter_lowers_an_accepted_request_and_refuses_the_rest(self):
        import campaign_behavior
        models, _ = prepared(dict(cutscene_ok=send(), cutscene_later=send(ADD.replace('immediate(true)', 'immediate(false)').replace('h_wait', 'h_later'))))
        lease, report = schedule.adapter(models[0], dict(level='test', controller=CONTROLLER, references=REFERENCES), 'C2')
        self.assertEqual([(l['handle'], l['behavior'], l['priority'], l['once'], l['sites']) for l in report['leases']],
                         [('h_wait', 'work', 60, True, 1)])
        contracts.register()
        catalog = dict(nodes={op: dict(attributes=list(fields), children=[]) for op, fields in campaign_behavior.CONTRACTS.items()},
                       variable_types=[], enum_types=[])
        compiler = campaign_behavior.BehaviorCompiler([], 'C2', catalog, schedule_adapter=lease)
        compiler.object_scopes[('q_example', DOCUMENT, 'cutscene_ok')] = 'q_example'
        def lower(tree):
            record = dict(unresolved=[], buff_dependencies=[], item_dependencies=[], includes=[])
            source = models[0]['behavior_documents'][DOCUMENT]['trees'][tree]['root']['children'][0]
            return compiler.lower_node(source, 'q_example', DOCUMENT, tree, 'Root/0', record), [u['reason'] for u in record['unresolved']]
        emitted, reasons = lower('cutscene_ok')
        self.assertEqual((reasons, emitted.tag, emitted.get('target'), emitted.get('type')),
                         ([], 'InstantSendMessageToNPC', '$__object.id', repr(lease.message_type)))
        self.assertEqual(emitted.get('values'), "route(0),kind(1),generation(0),actor($t_actors['worker'])")
        self.assertEqual(lower('cutscene_later'), (None, ['Schedule request differs from its resolved source site']))
        self.assertEqual(schedule.adapter(prepared(dict(cutscene_later=send(ADD.replace('immediate(true)', 'immediate(false)'))))[0][0],
                                          dict(level='test', controller=CONTROLLER, references=REFERENCES), 'C2')[0], None)


class NormaliseTests(unittest.TestCase):
    """Each rule restates KCD1's own consumer (Libs/AI/final/sb_daycycles.xml, inbox daycycleChange)."""
    BASE = "add(true),handle('h'),name('work'),priority(60),sourceId($this.id)"

    def run_one(self, values):
        subject = model(dict(a=send(values)))
        report = schedule.normalise(subject)
        return subject['behavior_documents'][DOCUMENT]['trees']['a']['root']['children'][0]['attributes']['values'], report

    def test_a_removal_keeps_only_its_handle(self):
        values, report = self.run_one("add(false),handle('h'),name('work'),immediateDaycycleHaltSpeed($enum:daycycleHaltSpeed.fast)")
        self.assertEqual(values, "add(false),handle('h')")
        self.assertEqual(report['rewritten'][0]['rules'], ['removal:name', 'removal:immediateDaycycleHaltSpeed'])
        self.assertEqual(self.run_one("add(false),handle('h')")[1]['rewritten'], [])
        # A field the consumer's removal branch is not known to ignore stays, and the request stays blocked.
        self.assertIn('once(true)', self.run_one("add(false),handle('h'),once(true)")[0])

    def test_a_critical_priority_replaces_the_priority(self):
        for label, priority in (('cutscene_dialogFadingIn', 95), ('cutscene_init', 100)):
            values, _ = self.run_one(self.BASE + ',immediate(true),criticalPriority($enum:daycyclePatchCriticalPriority.%s)' % label)
            self.assertEqual(values, "add(true),handle('h'),name('work'),priority(%d),sourceId($this.id),immediate(true)" % priority)
        values, report = self.run_one(self.BASE + ',immediate(true),criticalPriority($enum:daycyclePatchCriticalPriority.other)')
        self.assertIn('criticalPriority', values)
        self.assertEqual(report['rewritten'], [])

    def test_a_request_without_immediate_is_not_immediate(self):
        values, report = self.run_one(self.BASE)
        self.assertEqual((values, report['rewritten'][0]['rules']), (self.BASE + ',immediate(false)', ['immediate:default']))

    def test_an_immediate_request_has_no_window(self):
        values, report = self.run_one(self.BASE + ',immediate(true),startTime(-1),endTime(0.5)')
        self.assertEqual((values, report['windows']), (self.BASE + ',immediate(true)', {}))

    def test_a_window_is_minutes_of_the_day_on_a_request_that_waits(self):
        values, report = self.run_one("add(true), startTime(10),endTime(20.5),handle('h'),name('work'),priority(60),sourceId($this.id)")
        self.assertEqual(values, self.BASE + ',immediate(false)')
        self.assertEqual(report['windows'], {('a', 'Root/0'): (600, 1230)})
        self.assertEqual(self.run_one(self.BASE + ',startTime(8)')[1]['windows'], {('a', 'Root/0'): (480, 1440)})
        self.assertEqual(self.run_one(self.BASE + ',endTime(20)')[1]['windows'], {('a', 'Root/0'): (0, 1200)})
        for whole in ('startTime(0),endTime(24)', 'startTime(-1),endTime(24)', 'endTime(24)'):
            values, report = self.run_one(self.BASE + ',' + whole)
            self.assertEqual((values, report['windows']), (self.BASE + ',immediate(false)', {}))

    def test_a_request_that_waits_is_an_immediate_lease_by_decision_and_says_so(self):
        # Decision 11a. Off unless asked for; its window survives; an immediate request is not touched.
        subject = model(dict(a=send(self.BASE + ',startTime(10),endTime(20)'), b=send(self.BASE + ',immediate(true)'),
                             c=send(self.BASE + ',immediate(false)'), d=send(self.BASE + ',startTime(22),endTime(6)'),
                             e=send("add(false),handle('h')")))
        report = schedule.normalise(subject, boundary=True)
        trees = subject['behavior_documents'][DOCUMENT]['trees']
        site = lambda name: trees[name]['root']['children'][0]
        self.assertEqual([site(name)['attributes']['values'] for name in 'abc'], [self.BASE + ',immediate(true)'] * 3)
        self.assertEqual(([site(name).get('stand_in') for name in 'abcde'], report['boundaries'], report['windows']),
                         (['immediate lease, urgency Slow', None, 'immediate lease, urgency Slow', None, None],
                          [dict(tree='a', path='Root/0'), dict(tree='c', path='Root/0')], {('a', 'Root/0'): (600, 1200)}))
        self.assertEqual((report['rules']['boundary'], [r['rules'] for r in report['rewritten'] if r['tree'] == 'a']),
                         (2, [['immediate:default', 'window:kept', 'boundary:slow']]))
        # A window with no level form keeps the whole request as written.
        self.assertIn('immediate(false)', site('d')['attributes']['values'])
        self.assertIn('decision 11a', schedule.BOUNDARY)
        self.assertEqual(schedule.normalise(model(dict(a=send(self.BASE))))['boundaries'], [])

    def test_a_window_without_a_level_form_is_left_as_written(self):
        for window in ('startTime(-1),endTime(2)', 'startTime(22),endTime(6)', 'startTime($hour),endTime(24)',
                       'startTime(10.001),endTime(20)', 'startTime(10),endTime(25)'):
            values, report = self.run_one(self.BASE + ',' + window)
            self.assertIn(window, values.replace(', ', ','))
            self.assertEqual((report['windows'], len(report['left'])), ({}, 1))

    def test_a_window_is_part_of_the_lease_policy(self):
        trees = dict(cutscene_a=send(ADD + ',startTime(10),endTime(20)'), cutscene_b=send(ADD))
        subject = prepared(trees)[0][0]
        for tree in ('cutscene_a', 'cutscene_b'):   # as if the boundary adapter existed
            node_ = subject['behavior_documents'][DOCUMENT]['trees'][tree]['root']['children'][0]
            node_['attributes']['values'] = node_['attributes']['values'].replace(',startTime(10),endTime(20)', '')
        self.assertEqual(len(schedule.select(subject, REFERENCES)[0]), 2)
        selected, _, report = schedule.select(subject, REFERENCES, {('cutscene_a', 'Root/0'): (600, 1200)})
        self.assertEqual((selected, report['rejected']), (set(), dict(lease_policy=2)))


class WorldSideTests(unittest.TestCase):
    """What the converter hands `campaign_schedule_routes.assemble`, and adds to its result."""
    def scheduler(self, *behaviors, fields='TimeOfDayStart="0" TimeOfDayEnd="1440"'):
        import xml.etree.ElementTree as ET
        links = ''.join('<S_ActivityLink><Parameters BehaviorName="%s" %s /></S_ActivityLink>' % (b, fields) for b in behaviors)
        return ET.fromstring('<Root><Schedulers><C_SmartHub><Links>%s</Links></C_SmartHub></Schedulers></Root>' % links)

    def route(self, behavior, *sites):
        return dict(behavior=behavior, lease=dict(handle='h_' + behavior, sites=[
            dict(tree=tree, path=path, add=add) for tree, path, add in sites]))

    def test_a_lease_keeps_its_source_priority_and_the_default_halt_speed(self):
        prepared_ = dict(leases=[dict(actor='1', handle='h', policy=dict(priority=95))])
        policies = schedule.native_policies(prepared_)
        self.assertEqual((set(policies), policies[('1', 'h')]['priority'], policies[('1', 'h')]['urgency']),
                         ({('1', 'h')}, 95, 'Slow'))
        self.assertTrue(policies[('1', 'h')]['evidence'].strip())
        self.assertEqual(set(policies[('1', 'h')]), {'priority', 'urgency', 'evidence'})
        self.assertNotIn('decision 11a', policies[('1', 'h')]['evidence'])
        prepared_['leases'][0]['sites'] = [dict(tree='t', path='Root/0'), dict(tree='t', path='Root/1')]
        self.assertIn('decision 11a', schedule.native_policies(prepared_, [dict(tree='t', path='Root/1')])[('1', 'h')]['evidence'])
        self.assertNotIn('decision 11a', schedule.native_policies(prepared_, [dict(tree='u', path='Root/1')])[('1', 'h')]['evidence'])

    def test_the_preflight_lists_everything_the_converted_world_lacks(self):
        import xml.etree.ElementTree as ET
        plan = dict(owner='q_example', leases=[
            dict(actor='1', handle='h', policy=dict(behavior='work', callback=dict(document=DOCUMENT, tree='work'))),
            dict(actor='2', handle='g', policy=dict(behavior='rest', callback=dict(document=DOCUMENT, tree='rest')))])
        conversion = dict(trees=[dict(owner='q_example', document=DOCUMENT, tree='work', native_emitted=True),
                                 dict(owner='q_example', document=DOCUMENT, tree='rest', native_emitted=False),
                                 dict(owner='q_other', document=DOCUMENT, tree='rest', native_emitted=True)])
        def world(*entities):
            return ET.fromstring('<Objects>%s</Objects>' % ''.join('<Entity EntityGuid="%s" EntityClass="%s" />' % e for e in entities))
        template = ET.fromstring('<SmartEntityTemplate><BehaviorTemplates><SmartBehaviorTemplate Name="work" />'
                                 '</BehaviorTemplates></SmartEntityTemplate>')
        guid = lambda number: '%08x-0000-0000' % number
        empty = schedule.preflight(plan, guid(9), world(), None, conversion)
        self.assertEqual((empty['controller_in_world'], empty['controller_is_holder'], empty['template'], empty['ready']),
                         (False, False, False, False))
        from campaign_entity_links import guid_value
        plan['leases'][0]['actor'], plan['leases'][1]['actor'] = str(guid_value(guid(1))), str(guid_value(guid(2)))
        part = schedule.preflight(plan, guid(9), world((guid(9), 'NPC'), (guid(1), 'NPC')), template, conversion)
        self.assertEqual((part['controller_in_world'], part['controller_is_holder'], part['template'], part['ready']),
                         (True, False, True, False))
        self.assertEqual([(l['actor_in_world'], l['callback_emitted'], l['callback_registered']) for l in part['leases']],
                         [(True, True, True), (False, False, False)])
        one = dict(plan, leases=plan['leases'][:1])
        self.assertTrue(schedule.preflight(one, guid(9), world((guid(9), 'SmartObjectHolder'), (guid(1), 'NPC')), template, conversion)['ready'])
        self.assertFalse(schedule.preflight(one, guid(9), world((guid(9), 'SmartObjectHolder'), (guid(1), 'NPC')), None, conversion)['ready'])
        holder = world((guid(9), 'SmartObjectHolder'), (guid(1), 'NPC'))
        self.assertFalse(schedule.preflight(plan, guid(9), holder, template, conversion)['ready'])
        self.assertFalse(schedule.preflight(dict(plan, leases=[]), guid(9), holder, None, conversion)['ready'])
        self.assertTrue(schedule.preflight(dict(plan, leases=[]), guid(9), holder, template, conversion)['ready'])
        class Lease: plan, controller = one, guid(9)
        with self.assertRaisesRegex(ValueError, 'controller_in_world, controller_is_holder, template, 1 of 1 leases incomplete'):
            schedule.install(Lease, world(), None, None, None, conversion, {}, 'C2', None, {})

    def test_a_window_is_written_on_the_leases_own_link_only(self):
        table = self.scheduler('lease_a', 'lease_b')
        routes = [self.route('lease_a', ('t', 'Root/0', True), ('t', 'Root/1', False)), self.route('lease_b', ('u', 'Root/0', True))]
        self.assertEqual(schedule.apply_windows(table, routes, {('t', 'Root/0'): (600, 1200), ('t', 'Root/1'): (1, 2)}), 1)
        self.assertEqual([(p.get('BehaviorName'), p.get('TimeOfDayStart'), p.get('TimeOfDayEnd')) for p in table.iter('Parameters')],
                         [('lease_a', '600', '1200'), ('lease_b', '0', '1440')])

    def test_an_ambiguous_window_or_link_is_refused(self):
        windows = {('t', 'Root/0'): (600, 1200), ('t', 'Root/1'): (0, 1200)}
        with self.assertRaises(ValueError):
            schedule.apply_windows(self.scheduler('lease_a'), [self.route('lease_a', ('t', 'Root/0', True), ('t', 'Root/1', True))], windows)
        one = [self.route('lease_a', ('t', 'Root/0', True))]
        for table in (self.scheduler(), self.scheduler('lease_a', 'lease_a'), self.scheduler('lease_a', fields='')):
            with self.assertRaises(ValueError):
                schedule.apply_windows(table, one, windows)


if __name__ == '__main__': unittest.main()
