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
        self.assertEqual(report['rejected'], dict(actor_not_in_level=1, addition_fields=1, lease_policy=1,
                                                  next_activity_boundary=1, removal_fields=1, runtime_actor=1,
                                                  synchronous_request=1))
        self.assertEqual((report['requests'], report['accepted_requests'], report['accepted_shape_in_a_rejected_tree']), (9, 1, 1))

    def test_a_lease_shared_by_two_trees_needs_one_policy(self):
        same = dict(cutscene_a=send(), cutscene_b=send(), cutscene_c=send("add(false),handle('h_wait')"))
        trees, _, report = schedule.select(prepared(same)[0][0], REFERENCES)
        self.assertEqual((len(trees), report['rejected']), (3, {}))
        differing = dict(same, cutscene_b=send(ADD.replace('priority(60)', 'priority(70)')))
        trees, _, report = schedule.select(prepared(differing)[0][0], REFERENCES)
        self.assertEqual((trees, report['rejected']), (set(), dict(lease_policy=3)))
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


if __name__ == '__main__': unittest.main()
