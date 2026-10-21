import copy
import re
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
import xml.etree.ElementTree as E

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))

from campaign_ai_registration import NativeAIRegistry
from campaign_behavior import convert_behaviors
from campaign_schedule_lifecycle import ScheduleAdapter, validate_generated
from campaign_schedule_routes import assemble, compile_program
from test_campaign_behavior import catalog
from test_campaign_schedule_requests import fixture
from test_campaign_schedule_routes import inputs


class Consumer:
    """Run emitted control flow with explicit engine acquire/release events.

    This tests the generated program, not a second Python implementation of
    its state machine. Native scheduler/unwind timing still needs a playtest.
    """
    def __init__(self, adapter):
        self.adapter = adapter
        self.vars = {'this': SimpleNamespace(id=2), '__behaviors': {}, '__null': 0}
        self.availability = {}
        for r in adapter.routes:
            self.vars['__behaviors'][r['name']] = SimpleNamespace(count=0)
            self.availability[r['name']] = 'Disabled'
            for name, variable in adapter.variables(r).items():
                self.vars[variable] = 0 if name == 'generation' else False

    def expression(self, text):
        text = re.sub(r'\$([A-Za-z_]\w*)', r"values['\1']", text)
        text = text.replace('&', ' and ').replace('|', ' or ').replace('!', ' not ')
        text = re.sub(r'\btrue\b', 'True', text); text = re.sub(r'\bfalse\b', 'False', text)
        return eval(text, {'__builtins__': {}}, {'values': self.vars})

    def run(self, element):
        tag = element.tag
        if tag in ('Sequence', 'Then', 'Else', 'DefaultBranch', 'ProcessMessage'):
            return all(self.run(child) for child in element)
        if tag == 'Success': return True
        if tag == 'Fail': return False
        if tag == 'Expression':
            for statement in element.get('expressions').split(','):
                left, right = statement.split('=', 1)
                self.vars[left.strip().removeprefix('$')] = self.expression(right)
            return True
        if tag == 'SmartObjSetBehaviorState':
            self.availability[element.get('behaviors').strip("'")] = element.get('state')
            return True
        if tag == 'IfCondition':
            return self.run(element[0]) if self.expression(element.get('condition')) else True
        if tag == 'IfElseCondition':
            return self.run(element[0 if self.expression(element.get('condition')) else 1])
        if tag == 'Switch':
            for child in element:
                if child.tag == 'DefaultBranch' or self.expression(child.get('condition')):
                    return self.run(child)
            return True
        raise AssertionError('Unhandled generated operation: ' + tag)

    def event(self, kind, generation=0, route=0, sender=None):
        if sender is None: sender = 2 if kind < 2 else int(self.adapter.routes[route]['lease']['actor'])
        self.vars.update(message=SimpleNamespace(kind=kind, generation=generation, route=route,
            actor=int(self.adapter.routes[route]['lease']['actor'])), sender=SimpleNamespace(id=sender))
        self.run(self.adapter.consumer().find('.//ProcessMessage'))
        return self.vars['answer']

    def acquire(self, route=0):
        self.vars['__behaviors'][self.adapter.routes[route]['name']].count += 1
        return self.event(2, route=route)

    def release(self, route=0):
        self.vars['__behaviors'][self.adapter.routes[route]['name']].count -= 1
        self.run(self.adapter.released(self.adapter.routes[route]))

    def status(self, route=0):
        return self.availability[self.adapter.routes[route]['name']]


def registry():
    rows = {
        'brain': [dict(brain_id='keep-brain', brain_name='existing')],
        'brain2subbrain': [dict(brain_id='keep-brain', subbrain_id='existing-smart', priority='5')],
        'brain2mailbox': [dict(brain_id='keep-brain', mailbox_id='existing-inbox', priority='2')],
        'brain_variable': [dict(brain_id='keep-brain', brain_variable_name='original_phase',
            ai_variable_form_id='0', ai_variable_sync_id='0', type='int', init_value='0', is_persistent='true')],
        'subbrain': [dict(subbrain_id='existing-smart', subbrain_name='source', subbrain_type='4', always_active='true', timeout='0')],
        'subbrain_smart_object': [dict(subbrain_id='existing-smart', file_name='imported/q_test/quests/q_test.xml',
            on_update_tree='onUpdate', on_release_tree='original_release')],
        'subbrain_behaviour_tree': [dict(subbrain_id='other', file_name='default.xml', tree_name='default')],
        'mailbox': [dict(mailbox_id='existing-inbox', mailbox_name='existing', message_limit='-1', on_accept='2')],
        'mailbox_filter': [dict(mailbox_filter_id='old-filter', mailbox_id='existing-inbox', type='_string')],
        'mailbox_action_type': [dict(mailbox_action_type_id='2', mailbox_action_type_name='consume')],
        'subbrain_type': [dict(subbrain_type_id='1', subbrain_type_name='BehaviorTree')],
        'ai_variable_form': [dict(ai_variable_form_id='0', ai_variable_form_name='single')],
        'ai_variable_sync': [dict(ai_variable_sync_id='0', ai_variable_sync_name='no_sync')],
    }
    return NativeAIRegistry({name:dict(rows=value, container=name+'s', attributes={}, row_tag=name)
                             for name,value in rows.items()}, 'Imported')


def setup(once=True):
    args = inputs(); args[0]['leases'][0]['policy']['once'] = once
    return args, ScheduleAdapter(args[0], args[3], args[-1])


class ScheduleLifecycleTests(unittest.TestCase):
    def test_handles_are_independent_even_when_callback_and_actor_are_shared(self):
        args, _ = setup()
        other = copy.deepcopy(args[0]['leases'][0])
        other.update(handle='other', sites=[])
        args[0]['leases'].append(other)
        adapter = ScheduleAdapter(args[0], args[3], args[-1]); sim = Consumer(adapter)
        sim.event(1, route=0); sim.event(1, route=1)
        first = sim.acquire(0); sim.event(0, route=0)
        sim.event(3, first, route=0); sim.release(0)
        self.assertEqual(sim.status(0), 'Disabled')
        self.assertEqual(sim.status(1), 'Enabled')

    def test_restored_pending_replacement_waits_for_release(self):
        _, adapter = setup(); before = Consumer(adapter)
        before.event(1); old = before.acquire(); before.event(1)
        restored = Consumer(adapter)
        restored.vars = copy.deepcopy(before.vars)
        restored.availability = copy.deepcopy(before.availability)
        restored.event(3, old)
        self.assertEqual(restored.status(), 'Disabled')
        restored.release()
        self.assertGreater(restored.acquire(), old)

    def test_activate_claim_complete_then_wait_for_actual_release(self):
        _, adapter = setup(); sim = Consumer(adapter)
        sim.event(1); token = sim.acquire()
        self.assertEqual(token, 1); self.assertEqual(sim.status(), 'Enabled')
        sim.event(3, token)
        self.assertEqual(sim.status(), 'NoRequests')
        v = adapter.variables(adapter.routes[0])
        self.assertTrue(sim.vars[v['draining']])
        sim.release()
        self.assertFalse(sim.vars[v['draining']]); self.assertFalse(sim.vars[v['wanted']])

    def test_replacement_waits_and_old_completion_cannot_retire_new_job(self):
        _, adapter = setup(); sim = Consumer(adapter)
        sim.event(1); old = sim.acquire(); sim.event(1)
        self.assertEqual(sim.status(), 'Disabled')
        sim.release(); new = sim.acquire()
        self.assertGreater(new, old)
        sim.event(3, old)
        self.assertEqual(sim.status(), 'Enabled')
        sim.event(3, new); self.assertEqual(sim.status(), 'NoRequests')

    def test_remove_during_replacement_wins(self):
        _, adapter = setup(); sim = Consumer(adapter)
        sim.event(1); token = sim.acquire(); sim.event(1); sim.event(0)
        sim.event(3, token); sim.release()
        self.assertEqual(sim.status(), 'Disabled')

    def test_add_during_once_cleanup_survives_old_completion(self):
        _, adapter = setup(); sim = Consumer(adapter)
        sim.event(1); token = sim.acquire(); sim.event(3, token)
        sim.event(1); sim.event(3, token)
        self.assertEqual(sim.status(), 'Disabled')
        sim.release(); self.assertEqual(sim.status(), 'Enabled')

    def test_remove_before_acquisition_does_not_wait_for_nonexistent_worker(self):
        _, adapter = setup(); sim = Consumer(adapter)
        sim.event(1); sim.event(0)
        v = adapter.variables(adapter.routes[0])
        self.assertFalse(sim.vars[v['draining']]); self.assertEqual(sim.status(), 'Disabled')
        self.assertEqual(sim.event(2), 0)

    def test_interruption_is_not_once_completion(self):
        _, adapter = setup(); sim = Consumer(adapter)
        sim.event(1); sim.acquire(); sim.release()
        self.assertEqual(sim.status(), 'Enabled')
        self.assertTrue(sim.vars[adapter.variables(adapter.routes[0])['wanted']])

    def test_recurring_worker_remains_scheduled_after_result(self):
        _, adapter = setup(once=False); sim = Consumer(adapter)
        sim.event(1); token = sim.acquire(); sim.event(3, token); sim.release()
        self.assertEqual(sim.status(), 'Enabled')

    def test_repeated_adds_coalesce_during_release_without_skipping_replacement(self):
        _, adapter = setup(); sim = Consumer(adapter)
        sim.event(1); old = sim.acquire()
        for _ in range(4): sim.event(1)
        self.assertEqual(sim.status(), 'Disabled')
        sim.release(); self.assertGreater(sim.acquire(), old)

    def test_late_result_from_native_preemption_cannot_finish_resumed_worker(self):
        _, adapter = setup(); sim = Consumer(adapter)
        sim.event(1); old = sim.acquire(); sim.release()
        current = sim.acquire(); self.assertGreater(current, old)
        sim.event(3, old); self.assertEqual(sim.status(), 'Enabled')
        sim.event(3, current); self.assertEqual(sim.status(), 'NoRequests')

    def test_unrelated_sender_cannot_complete_or_enable_actor(self):
        _, adapter = setup(); sim = Consumer(adapter)
        sim.event(1, sender=999); self.assertEqual(sim.status(), 'Disabled')
        sim.event(1); token = sim.acquire(); sim.event(3, token, sender=999)
        self.assertEqual(sim.status(), 'Enabled')

    def test_success_and_failure_both_report_after_whole_source_root(self):
        _, adapter = setup(); worker = adapter.wrapper(adapter.routes[0], 'source.xml', 'work')
        seq = worker.find('Root/Behavior/Sequence')
        self.assertEqual(seq[0].tag, 'SendMessageToNPC')
        self.assertEqual(seq[0].get('timeoutType'), 'OnProcessed')
        result = seq.find('.//Selector')
        self.assertEqual([c.tag for c in result[0]], ['IncludeTree','SendMessageToNPC'])
        self.assertEqual([c.tag for c in result[1]], ['SendMessageToNPC','Fail'])
        self.assertNotIn('OnFail', [n.tag for n in worker.iter()])  # no cancellation-as-completion hook

    def test_compiler_lowers_guarded_request_only_with_bound_adapter(self):
        m, doc, _ = fixture(); args, adapter = setup()
        # The assembly fixture adds a removal, but the original add path is the same.
        files, _, report = convert_behaviors([m], 'Imported', catalog(), schedule_adapter=adapter)
        record = next(r for r in report['trees'] if r['tree']=='onUpdate')
        self.assertTrue(record['native_emitted'], record['unresolved'])
        sender = E.fromstring(files['AI/imported/q_test/quests/q_test.xml']).find('.//Sequence/InstantSendMessageToNPC')
        self.assertEqual(sender.get('target'), '$this.id')
        self.assertEqual(sender.get('type'), repr(adapter.message_type))
        self.assertEqual(report['schedule_consumer_required'], adapter.stem)

    def test_install_registers_real_consumer_and_release_hook_preserving_brain(self):
        args, adapter = setup()
        path = 'AI/imported/q_test/quests/q_test.xml'
        args[7][path] = b'<BehaviorTrees><BehaviorTree name="implementation"><Root><Success/></Root></BehaviorTree><BehaviorTree name="original_release"><Root><Success/></Root></BehaviorTree></BehaviorTrees>'
        before = copy.deepcopy(args)
        _,_,template,_,report = assemble(*args, lifecycle=adapter, native=registry())
        self.assertEqual(args[7], before[7]); self.assertEqual(E.tostring(args[4]), E.tostring(before[4]))
        files = report['files']; self.assertTrue(report['lifecycle']['request_consumer_installed'])
        self.assertNotEqual(template.get('BrainId'), 'keep-brain')
        alias = template.findall('BehaviorTemplates/SmartBehaviorTemplate')[1]
        self.assertEqual(alias.get('MaxInstances'), '1')
        self.assertEqual(alias.find('TreeLocation').get('FileName'), adapter.file)
        self.assertIsNotNone(E.fromstring(files[path]).find(".//IncludeTree[@Name=\"'original_release'\"]"))
        self.assertTrue(any('original_phase' in b.decode() for p,b in files.items() if 'brain_variable__' in p))
        self.assertTrue(any('existing-inbox' in b.decode() for p,b in files.items() if 'brain2mailbox__' in p))
        self.assertFalse(report['runtime_validated'])

    def test_missing_release_registration_aborts_atomically(self):
        args, adapter = setup(); before = copy.deepcopy(args)
        native = registry(); native.tables['subbrain_smart_object']['rows'] = []
        with self.assertRaisesRegex(ValueError, 'release callback'): assemble(*args, lifecycle=adapter, native=native)
        self.assertEqual(args[7], before[7]); self.assertEqual(E.tostring(args[1]), E.tostring(before[1]))

    def test_path_backed_converted_brain_and_document_are_read(self):
        args, adapter = setup(); native = registry()
        document = b'<BehaviorTrees><BehaviorTree name="implementation"><Root><Success/></Root></BehaviorTree><BehaviorTree name="original_release"><Root><Success/></Root></BehaviorTree></BehaviorTrees>'
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder); source = root / 'controller.xml'; source.write_bytes(document)
            args[7]['AI/imported/q_test/quests/q_test.xml'] = source
            table_path, table_blob = next(iter(native.emit('brain_variable', 'converted', [dict(
                native.tables['brain_variable']['rows'][0], brain_variable_name='imported_state')]).items()))
            table = root / 'variable.xml'; table.write_bytes(table_blob); args[7][table_path] = table
            result = assemble(*args, lifecycle=adapter, native=native)
            self.assertTrue(any(b'imported_state' in value for path,value in result[-1]['files'].items()
                if 'brain_variable__' in path and isinstance(value, bytes)))
            self.assertEqual(source.read_bytes(), document)

    def test_complete_program_requires_controller_entry_and_emits_consumer_together(self):
        args, _ = setup(); m, doc, trees = fixture(); native = registry()
        native.tables['subbrain_smart_object']['rows'][0]['on_release_tree'] = ''
        m['controller_registration']['entry_points'].append(dict(
            kind='on_update_tree', file='quests/q_test.xml', tree='onUpdate'))
        abi = catalog()
        abi['nodes']['SmartObjSetBehaviorState'] = dict(attributes=['behaviors','state'])
        binding = {(doc, 'onUpdate', 'actors[worker]'): '00000001-0000-0000'}
        def build():
            return compile_program(m, binding, *args[1:6], args[8], args[9], abi, native, {})
        result = build(); report = result[-1]
        self.assertTrue(report['lifecycle']['request_consumer_installed'])
        self.assertEqual(report['compiler']['blocked_trees'], 0)
        self.assertTrue(any('_consume' in blob.decode() for p,blob in report['files'].items() if p.startswith('AI/')))
        before = [E.tostring(args[i]) for i in (1,2,4)]
        trees['onUpdate']['root']['children'][0]['children'][0]['children'].append(
            dict(op='UnconvertedControllerOperation', attributes={}, children=[]))
        with self.assertRaisesRegex(ValueError, 'entry programs remain unconverted'): build()
        self.assertEqual(before, [E.tostring(args[i]) for i in (1,2,4)])

    def test_generated_consumer_requires_target_node_abi(self):
        _, adapter = setup(); root = E.Element('BehaviorTrees'); root.append(adapter.consumer())
        files = {'AI/' + adapter.file: E.tostring(root)}
        with self.assertRaisesRegex(ValueError, 'native ABI: SmartObjSetBehaviorState'):
            validate_generated(adapter, files, dict(nodes={
                n.tag: dict(attributes=list(n.attrib)) for n in root.iter() if n.tag != 'SmartObjSetBehaviorState'}))

    def test_complete_generic_program_packages_factions_with_scheduler(self):
        from campaign_temporary_factions import FactionBridge
        from campaign_compile import wire_bridge
        from campaign_quest_graph import emit_project
        from quest_import import ast
        from test_campaign_temporary_factions import GROUPS, TREE, NATIVE, SOUL
        from test_campaign_quest_graph import model as quest_model

        args, _ = setup(); model, doc, trees = fixture(); native = registry()
        native.tables['subbrain_smart_object']['rows'][0]['on_release_tree'] = ''
        model['controller_registration']['entry_points'].append(dict(
            kind='on_update_tree', file='quests/q_test.xml', tree='onUpdate'))
        # The callback owns its original cleanup. Faction conversion must not
        # move this to startup or confuse the worker with its smart-object host.
        trees['implementation']['root'] = ast(E.fromstring('''<Root><Behavior>
          <FuseBox StatusPropagation="Child" OneCleanup="true"><Child><Sequence>
            <SetTemporarySuperfaction soul="this.id" superfaction="Civilians"/>
            <Success/>
          </Sequence></Child><OnSuccess>
            <ClearTemporarySuperfaction soul="this.id"/>
          </OnSuccess></FuseBox></Behavior></Root>'''))
        factions = FactionBridge('Imported',
            {('q_test', doc, 'implementation', 'this.id'): SOUL}, GROUPS, TREE, NATIVE)
        abi = catalog()
        abi['nodes']['SmartObjSetBehaviorState'] = dict(attributes=['behaviors','state'])
        binding = {(doc, 'onUpdate', 'actors[worker]'): '00000001-0000-0000'}
        before = [E.tostring(args[i]) for i in (1, 2, 4)]
        result = compile_program(model, binding, *args[1:6], args[8], args[9], abi,
                                 native, {}, faction_adapter=factions)
        report = result[-1]; compiled = report['compiler']; files = report['files']
        self.assertEqual(compiled['blocked_trees'], 0)
        self.assertTrue(report['lifecycle']['request_consumer_installed'])
        self.assertEqual({a['actor'] for a in compiled['temporary_factions']['actions'].values()}, {SOUL})
        self.assertEqual({a['kind'] for a in compiled['temporary_factions']['actions'].values()}, {'set','clear'})
        effect_path = 'Quests/Imported_temporary_factions.xml'
        self.assertIn(effect_path, files)
        self.assertIn(effect_path, report['bridge_files'])
        self.assertIn('Libs/Tables/ai/AIConceptSignalDatabase__imported_temporary_factions.xml', files)
        worker = E.fromstring(files['AI/imported/q_test/quests/q_test.xml']).find(
            "BehaviorTree[@name='implementation']/Root/Behavior/FuseBox")
        self.assertTrue(worker.find('OnSuccess')[0].tag.startswith('SendAIConceptSignal_'))
        self.assertIsNone(worker.find('OnFail'))
        project, _ = emit_project([quest_model()], 'world')
        wire_bridge(project, 'world', {p: files[p] for p in report['bridge_files']}, compiled)
        self.assertIsNotNone(E.fromstring(project['world.xml']).find(
            "./Skald/Project/Nodes/Imported_temporary_factions[@Name='source_temporary_factions']"))
        self.assertEqual(before, [E.tostring(args[i]) for i in (1, 2, 4)])
        self.assertFalse(report['publication_ready'])
        self.assertFalse(compiled['temporary_factions']['runtime_validated'])

    def test_deferred_requests_are_not_silently_made_immediate(self):
        args = inputs(); args[0]['leases'][0]['policy']['immediate'] = False
        with self.assertRaisesRegex(ValueError, 'next-activity boundary'):
            ScheduleAdapter(args[0], args[3], args[-1])


if __name__ == '__main__': unittest.main()
