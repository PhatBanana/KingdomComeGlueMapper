"""Behaviour nodes whose outcome the engine or a lock table decides (quest_lab.engine_nodes).

Each test pairs the modelled behaviour with a mutation: the same tree with one
attribute, outcome or assumption changed must behave differently.
"""
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from quest_lab import Unsupported
from quest_lab.behavior import Behavior
from quest_lab.controller_walk import ASSUMED
from quest_lab.expressions import assignments, evaluate
from quest_lab.graph import Graph
from quest_lab.source import Source

PROJECT = b'''<Database><Skald><Project Name="Test"><Nodes>
  <SetGameContext Name="on"><Constant Name="Context" Value="on"/><Constant Name="IsActive" Value="true"/></SetGameContext>
  <SetGameContext Name="off"><Constant Name="Context" Value="off"/><Constant Name="IsActive" Value="false"/></SetGameContext>
  </Nodes></Project></Skald></Database>'''
MOVE = '<Move destinationSpecification="$spot" speed="Walk"/>'
BUMP = '<Expression expressions="$count = $count + 1"/>'


def lab(body, assumptions=None, trees=(), start=True, **kwargs):
    assumed = dict(ASSUMED) if assumptions is None else assumptions
    blob = ('<BehaviorTrees><BehaviorTree name="main"><Root><Behavior>' + body + '</Behavior></Root></BehaviorTree>'
            + ''.join('<BehaviorTree name="%s"><Root><Behavior>%s</Behavior></Root></BehaviorTree>' % t for t in trees)
            + '</BehaviorTrees>').encode()
    variables = dict(dict(count=0, go=False, spot='spot', this=dict(id='npc', name='npc')), **kwargs.pop('variables', {}))
    b = Behavior('test', blob, Graph(Source.blobs({'graph.xml': PROJECT}), 'Test', budget=20000, assumptions=assumed),
                 variables=variables, **kwargs)
    return (b, b.start('main', 'main')) if start else (b, None)


def status(b, task='main'):
    return b.tasks[task]['status']


def pending(b):
    return [(boundary['operation'], boundary['kind']) for _, boundary in b.boundaries()]


class GateTests(unittest.TestCase):
    def test_context_barrier_waits_for_its_context_and_negation_inverts_it(self):
        gate = '<GameContextBarrier context="%s" Negation="%s" RunLogic="KeepRunning">' + BUMP + '</GameContextBarrier>'
        for context, negation, runs in (('on', 'false', True), ('off', 'false', False), ('on', 'true', False), ('off', 'true', True)):
            b, _ = lab(gate % (context, negation))
            self.assertEqual(b.unsupported, [])
            self.assertEqual((status(b), b.variables['count']), ('success', 1) if runs else ('gate', 0), (context, negation))

    def test_halt_stops_and_restarts_the_child_and_keep_running_does_not(self):
        gate = '<IfGate atomic="false" condition="$go" RunLogic="%s"><Sequence>' + BUMP + MOVE + '</Sequence></IfGate>'
        outcomes = {}
        for logic in ('Halt', 'KeepRunning'):
            b, _ = lab(gate % logic)
            self.assertEqual(status(b), 'gate')
            b.set_variables({'go': True}); b.pump()
            self.assertEqual(pending(b), [('Move', 'action')])
            b.set_variables({'go': False}); b.pump()
            closed = status(b)
            b.set_variables({'go': True}); b.pump()
            b.resolve('main', 'success')
            outcomes[logic] = (closed, b.variables['count'], status(b))
        # Halt: the move is dropped while closed and the child runs again from the start.
        self.assertEqual(outcomes, {'Halt': ('gate', 2, 'success'), 'KeepRunning': ('external', 1, 'success')})

    def test_gate_returns_its_child_result(self):
        for child, result in (('<Success/>', 'success'), ('<Fail/>', 'fail')):
            b, _ = lab('<IfGate atomic="false" condition="true" RunLogic="Halt">' + child + '</IfGate>')
            self.assertEqual(status(b), result)

    def test_engine_gates_open_and_close_only_when_the_scenario_says(self):
        gates = {'DistanceGate': 'Origin="" ReferencePt="$spot" Low="1.0" High="2.0" Negation="false" OpenInMiddle="false"',
                 'AreaPresenceGate': 'aiObjects="$spot" area="$spot" amount="AtLeastOne" presence="Present"',
                 'DialogGate': 'Who="$spot" Negation="true" EndDialogInRoot="false" Condition="InAny"',
                 'ActorStateBarrier': 'Who="$spot" ToState="combat" NegateTo="false"',
                 'DetailBehaviorBarrier': '', 'ProfileLoadedGate': 'LayerName="\'layer\'" NegateTo="false"'}
        for tag, fields in gates.items():
            seen = {}
            for logic in ('Halt', 'KeepRunning'):
                b, _ = lab('<%s %s RunLogic="%s"><Sequence>%s%s</Sequence></%s>' % (tag, fields, logic, BUMP, MOVE, tag))
                self.assertEqual(b.unsupported, [], tag)
                self.assertEqual((pending(b), b.variables['count']), ([(tag, 'gate')], 0), tag)
                with self.assertRaises(ValueError): b.resolve('main', 'success')
                b.resolve('main', 'open')
                self.assertEqual(pending(b), [('Move', 'action')])
                (task, path, operation, run_logic), = b.open_gates()
                self.assertEqual((operation, run_logic), (tag, logic))
                b.close_gate(task, path)
                seen[logic] = pending(b)
            self.assertEqual(seen, {'Halt': [(tag, 'gate')], 'KeepRunning': [('Move', 'action')]}, tag)

    def test_fader_barrier_runs_its_child_after_the_fade_and_has_no_run_logic(self):
        b, _ = lab('<FaderBarrier Fader="\'jail\'">' + BUMP + '</FaderBarrier>')
        self.assertEqual((b.unsupported, pending(b)), ([], [('FaderBarrier', 'gate')]))
        b.resolve('main', 'open')
        self.assertEqual((status(b), b.variables['count']), ('success', 1))
        broken, _ = lab('<FaderBarrier Fader="\'jail\'" RunLogic="Halt" Speed="2">' + BUMP + '</FaderBarrier>', start=False)
        self.assertTrue(any('Speed' in u['reason'] for u in broken.unsupported))

    def test_an_assumption_the_scenario_did_not_declare_is_unsupported_by_name(self):
        gate = '<IfGate atomic="false" condition="true" RunLogic="Halt"><Success/></IfGate>'
        with self.assertRaisesRegex(Unsupported, 'behavior.gate.run_logic'):
            lab(gate, assumptions={})
        b, _ = lab(gate, assumptions={'behavior.gate.run_logic': 'halt_restarts'})
        self.assertEqual(status(b), 'success')
        self.assertTrue(b.graph.world.report()['assumptions']['behavior.gate.run_logic']['used'])
        with self.assertRaises(ValueError):
            lab(gate, assumptions={'behavior.gate.run_logic': 'something_else'})

    def test_atomic_gates_and_queue_timeouts_are_findings_not_guesses(self):
        for body, word in (('<IfGate atomic="true" condition="true" RunLogic="Halt"><Success/></IfGate>', 'atomic'),
                           ('<IfGate atomic="false" condition="true" RunLogic="Sometimes"><Success/></IfGate>', 'RunLogic'),
                           ('<IfGate atomic="false" condition="true" RunLogic="Halt"/>', 'exactly 1 child'),
                           ('<ExternalLock atomic="false" TimerType="GameTime" OutsideTimerValue="\'10s\'" LockManagerType="Local" '
                            'SemaphoreName="\'a\'" RunLogic="Halt"><Success/></ExternalLock>', 'queue timeout')):
            b, _ = lab(body, start=False)
            self.assertTrue(any(word in u['reason'] for u in b.unsupported), word)
            with self.assertRaises(Unsupported): b.start('main')


LOCK = ('<ExternalLock atomic="false" OutsideQueuePosVariable="" InsidePosVariable="" TimerType="GameTime" '
        'OutsideTimerValue="\'-1\'" LockManagerType="%s" SemaphoreName="\'door\'" RunLogic="KeepRunning">' + BUMP + '</ExternalLock>')
SET = '<SetExternalLock LockManagerType="%s" Locked="%s" LockName="\'door\'"/>'


class LockTests(unittest.TestCase):
    def test_external_lock_follows_the_declared_polarity_and_unset_state(self):
        seen = {}
        for open_when in ('locked', 'unlocked'):
            for unset in ('locked', 'unlocked'):
                b, _ = lab(LOCK % 'Local', assumptions=dict(ASSUMED, **{'behavior.external_lock.open_when': open_when,
                                                                         'behavior.external_lock.unset': unset}))
                seen[(open_when, unset)] = status(b)
        self.assertEqual(seen, {('locked', 'locked'): 'success', ('locked', 'unlocked'): 'gate',
                                ('unlocked', 'locked'): 'gate', ('unlocked', 'unlocked'): 'success'})

    def test_set_external_lock_opens_a_waiting_gate_in_the_same_scope_only(self):
        for scope, opens in (('Local', True), ('Global', False)):
            b, _ = lab('<Parallel successMode="All" failureMode="Any">' + LOCK % 'Local'
                       + '<Sequence>' + MOVE + SET % (scope, 'false') + '</Sequence></Parallel>')
            self.assertEqual(b.variables['count'], 0)
            task = next(n for n, _ in b.boundaries())
            b.resolve(task, 'success')
            self.assertEqual((status(b), b.variables['count']), ('success', 1) if opens else ('parallel', 0), scope)
            self.assertEqual([e['effect'] for e in b.effects], ['set_lock'])
        b, _ = lab(SET % ('Local', 'true') + LOCK % 'Local')            # written locked: stays shut under 'unlocked'
        self.assertEqual(status(b), 'gate')

    def test_intellect_lock_belongs_to_one_npc_task(self):
        b, _ = lab(LOCK % 'Intellect', trees=[('other', SET % ('Intellect', 'false'))])
        b.start('other', 'other')
        self.assertEqual(status(b), 'gate')
        b.locks['Intellect|main|door'] = False; b.pump()
        self.assertEqual(status(b), 'success')

    def test_lock_name_reads_a_string_variable(self):
        named = LOCK.replace("'door'", "'$name'") % 'Local'
        b, _ = lab(SET.replace("'door'", "'$name'") % ('Local', 'false') + named, variables={'name': 'gate7'})
        self.assertEqual((status(b), b.locks), ('success', {'Local|gate7': False}))
        with self.assertRaises(Unsupported): lab(named)

    SYNC = ('<Synchronize SemaphoreCount="%d" InsideTimerValue="\'-1\'" InvalidateOnExpire="false" atomic="false" '
            'OutsideQueuePosVariable="" InsidePosVariable="" TimerType="GameTime" OutsideTimerValue="\'-1\'" '
            'LockManagerType="Local" SemaphoreName="\'party\'" RunLogic="KeepRunning">' + BUMP + '</Synchronize>')

    def test_synchronize_opens_for_everyone_when_the_count_is_waiting(self):
        for count, opened in ((2, True), (3, False)):
            b, _ = lab(self.SYNC % count, trees=[('second', self.SYNC % count)])
            self.assertEqual(status(b), 'gate')
            b.start('second', 'second')
            self.assertEqual((status(b), status(b, 'second'), b.variables['count']),
                             ('success', 'success', 2) if opened else ('gate', 'gate', 0))

    def test_instant_semaphore_fails_when_full_and_is_released_by_its_holder(self):
        hold = ('<InstantSemaphore SemaphoreCount="%d" LockManagerType="Local" SemaphoreName="\'one\'">' + MOVE + '</InstantSemaphore>')
        for count, second in ((1, 'fail'), (2, 'external')):
            b, _ = lab(hold % count, trees=[('second', hold % count)])
            b.start('second', 'second')
            self.assertEqual(status(b, 'second'), second)
            b.resolve('main', 'success')
            self.assertEqual(b.semaphores, {} if count == 1 else {'Local|one': ['second|second/0/0']})
            b.start('second', 'third')
            self.assertEqual(status(b, 'third'), 'external')


class StructureTests(unittest.TestCase):
    BOX = ('<FuseBox StatusPropagation="%s" OneCleanup="true" saveVersion="2"><Child>%s</Child>'
           '<OnSuccess><Expression expressions="$ended = \'success\'"/></OnSuccess>'
           '<OnFail><Sequence><Expression expressions="$ended = \'fail\'"/>%s</Sequence></OnFail></FuseBox>')

    def test_fusebox_cleans_up_by_result_and_propagates_as_declared(self):
        seen = {}
        for mode in ('Child', 'Success', 'CleanUp'):
            for child in ('<Success/>', '<Fail/>'):
                b, _ = lab(self.BOX % (mode, child, '<Success/>'), variables={'ended': ''})
                self.assertEqual(b.unsupported, [])
                seen[(mode, child)] = (b.variables['ended'], status(b))
        self.assertEqual(seen, {('Child', '<Success/>'): ('success', 'success'), ('Child', '<Fail/>'): ('fail', 'fail'),
                                ('Success', '<Success/>'): ('success', 'success'), ('Success', '<Fail/>'): ('fail', 'success'),
                                ('CleanUp', '<Success/>'): ('success', 'success'), ('CleanUp', '<Fail/>'): ('fail', 'success')})

    def test_interrupted_fusebox_runs_on_fail_and_a_waiting_cleanup_is_refused(self):
        tree = '<Parallel successMode="Any" failureMode="Any">%s<IfGate atomic="false" condition="$go" RunLogic="Halt"><Success/></IfGate></Parallel>'
        b, _ = lab(tree % (self.BOX % ('Child', MOVE, '<Success/>')), variables={'ended': ''})
        self.assertEqual(b.variables['ended'], '')
        b.set_variables({'go': True}); b.pump()
        self.assertEqual((status(b), b.variables['ended']), ('success', 'fail'))
        b, _ = lab(tree % (self.BOX % ('Child', MOVE, MOVE)), variables={'ended': ''})
        with self.assertRaisesRegex(Unsupported, 'cleanup that waits'):
            b.set_variables({'go': True}); b.pump()
        b, _ = lab(tree % (self.BOX % ('Child', MOVE, '<Success/>')), variables={'ended': ''},
                   assumptions={k: v for k, v in ASSUMED.items() if k != 'behavior.fusebox.interrupted'})
        with self.assertRaisesRegex(Unsupported, 'behavior.fusebox.interrupted'):
            b.set_variables({'go': True}); b.pump()

    def test_for_visits_the_array_in_step_order_and_stops_on_break(self):
        loop = ('<For startIndex="%s" endIndex="%s" step="%s" array="$items" iterator="$i" value="$item" break="%s">'
                '<Expression expressions="$seen = $seen * 10 + $item, $stop = $item == 2"/></For>')
        cases = {('0', '-1', '1', ''): 123, ('-1', '-1', '-1', ''): 321, ('1', '-1', '1', ''): 23,
                 ('0', '1', '1', ''): 12, ('0', '-1', '1', '$stop'): 12}
        for fields, expected in cases.items():
            b, _ = lab(loop % fields, variables=dict(items=[1, 2, 3], seen=0, stop=False, i=0, item=0))
            self.assertEqual((b.unsupported, status(b), b.variables['seen']), ([], 'success', expected), fields)
        b, _ = lab(loop.replace('<Expression', '<Sequence><Fail/></Sequence><Expression') % ('0', '-1', '1', ''),
                   variables=dict(items=[1, 2, 3], seen=0, stop=False, i=0, item=0), start=False)
        self.assertTrue(b.unsupported)                       # two children: a finding, never the first child only
        with self.assertRaises(Unsupported): b.start('main')

    def test_for_body_failure_fails_only_under_its_assumption(self):
        loop = '<For startIndex="0" endIndex="-1" step="1" array="$items" iterator="" value="" break=""><Fail/></For>'
        b, _ = lab(loop, variables=dict(items=[1]))
        self.assertEqual(status(b), 'fail')
        with self.assertRaisesRegex(Unsupported, 'behavior.loop.body_failure'):
            lab(loop, variables=dict(items=[1]), assumptions={k: v for k, v in ASSUMED.items() if k != 'behavior.loop.body_failure'})

    def test_loop_until_stops_at_the_wanted_result_or_fails_when_exhausted(self):
        body = '<Sequence>' + BUMP + '<IfCondition condition="$count >= 3" failOnCondition="true"><Success/></IfCondition></Sequence>'
        seen = {}
        for until, attempts in (('Success', 5), ('Success', 2), ('Success', 0), ('Fail', 5)):
            b, _ = lab('<LoopUntil until="%s" attemptCount="%d">%s</LoopUntil>' % (until, attempts, body))
            seen[(until, attempts)] = (status(b), b.variables['count'])
        self.assertEqual(seen, {('Success', 5): ('success', 3), ('Success', 2): ('fail', 2), ('Success', 0): ('success', 3),
                                ('Fail', 5): ('success', 1)})

    def test_atomic_section_returns_its_child_result_and_is_not_interrupted(self):
        for child, result in (('<Success/>', 'success'), ('<Fail/>', 'fail')):
            self.assertEqual(status(lab('<AtomicDecorator>' + child + '</AtomicDecorator>')[0]), result)
        b, _ = lab('<IfGate atomic="false" condition="$go" RunLogic="Halt"><AtomicDecorator>' + MOVE + '</AtomicDecorator></IfGate>',
                   variables={'go': True})
        with self.assertRaisesRegex(Unsupported, 'atomic section'):
            b.set_variables({'go': False}); b.pump()

    def test_endless_loop_with_an_instant_body_waits_for_the_next_engine_tick(self):
        b, _ = lab('<Loop count="-1">' + BUMP + '</Loop>')
        self.assertEqual((status(b), b.variables['count']), ('tick', 1))
        b.pump()
        self.assertEqual(b.variables['count'], 1)
        b.tick(); b.tick()
        self.assertEqual((status(b), b.variables['count']), ('tick', 3))
        waits, _ = lab('<Loop count="-1"><Sequence>' + BUMP + MOVE + '</Sequence></Loop>')
        waits.resolve('main', 'success')
        self.assertEqual((status(waits), waits.variables['count']), ('external', 2))    # a body that waited loops on


class BoundaryTests(unittest.TestCase):
    def test_engine_actions_take_the_outcome_the_scenario_supplies(self):
        actions = {'Move': 'destinationSpecification="$spot" speed="Walk" stopWithinDistance="1.0"',
                   'ExactMove': 'destinationSpecification="$spot" directionType="AlignWithEntity" speed="Run"',
                   'Turn': 'target="$spot" destinationType="FromVariable" align="false"',
                   'CallBehavior': 'Target="$spot" BehaviorName="\'use\'" stopAfterFirstFound="true" nodeLabel="7"',
                   'StopMovement': 'waitUntilStopped="true"', 'DrawAction': 'WeaponSet="Primary" fullBody="false" tags=""',
                   'TeleportAction': 'Position="$spot"'}
        for tag, fields in actions.items():
            for outcome in ('success', 'fail'):
                b, _ = lab('<Sequence><%s %s/>%s</Sequence>' % (tag, fields, BUMP))
                self.assertEqual((b.unsupported, pending(b)), ([], [(tag, 'action')]), tag)
                with self.assertRaises(ValueError): b.resolve('main', 'open')
                b.resolve('main', outcome)
                self.assertEqual((status(b), b.variables['count']), (outcome, int(outcome == 'success')), tag)
        unknown, _ = lab('<Move destinationSpecification="$spot" throughWalls="true"/>', start=False)
        self.assertTrue(any('throughWalls' in u['reason'] for u in unknown.unsupported))

    def test_a_native_function_call_is_one_engine_action_under_its_assumption(self):
        calls = {'Function_speech_polylogInitiator': (
                     ['alias="$alias"', 'animationApproach="$enum:animationApproach.dontPlayDialogAnimations"',
                      'context="$__null"', 'customParameters="$parameters"', 'metarole=""', 'participants="$who"',
                      'participantsMetaroles=""', 'preset="$enum:dialogPreset.ignored"'], 'participants', 'recipient'),
                 'Function_moveInFormation_inFormation': (
                     ['destination="$spot"', 'followEnabled="false"', 'followFormationParams="$formation"',
                      'pathOffset="0.000000"', 'successDistance="0.000000"'], 'destination', 'changeNPCState')}
        for tag, (parameters, required, undeclared) in calls.items():
            fields = ' '.join(parameters)
            for outcome in ('success', 'fail'):
                b, _ = lab('<Sequence><%s %s/>%s</Sequence>' % (tag, fields, BUMP))
                self.assertEqual((b.unsupported, pending(b)), ([], [(tag, 'action')]), tag)
                self.assertEqual(b.variables['count'], 0)  # nothing after the call runs before the engine answers
                b.resolve('main', outcome)
                self.assertEqual((status(b), b.variables['count']), (outcome, int(outcome == 'success')), tag)
                self.assertTrue(b.graph.world.report()['assumptions']['behavior.native_function']['used'])
            # Mutations: a parameter the retail definition does not declare, a parameter left out, no assumption.
            extra, _ = lab('<%s %s %s="true"/>' % (tag, fields, undeclared), start=False)
            self.assertTrue(any(undeclared in u['reason'] for u in extra.unsupported), tag)
            missing, _ = lab('<%s %s/>' % (tag, ' '.join(p for p in parameters if not p.startswith(required + '='))), start=False)
            self.assertTrue(any('every parameter written: ' + required in u['reason'] for u in missing.unsupported), tag)
            with self.assertRaisesRegex(Unsupported, 'behavior.native_function'):
                lab('<%s %s/>' % (tag, fields), assumptions={k: v for k, v in ASSUMED.items() if k != 'behavior.native_function'})
            with self.assertRaises(ValueError):
                lab('<%s %s/>' % (tag, fields), assumptions=dict(ASSUMED, **{'behavior.native_function': 'succeeds'}))
        # A dialogue that fails is tried again by the loop the source put around it; one that succeeds ends it.
        loop = '<LoopUntil until="Success" attemptCount="0"><Sequence>%s<Function_speech_polylogInitiator %s/></Sequence></LoopUntil>' % (
            BUMP, ' '.join(calls['Function_speech_polylogInitiator'][0]))
        b, _ = lab(loop)
        b.resolve('main', 'fail')
        self.assertEqual((status(b), b.variables['count'], pending(b)), ('external', 2, [('Function_speech_polylogInitiator', 'action')]))
        b.resolve('main', 'success')
        self.assertEqual((status(b), b.variables['count']), ('success', 2))
        # The fight stand-in is not modelled: a tree that has it is not walked as if it were.
        other, _ = lab('<Function_combat_fightRepeated_template target="$spot"/>', start=False)
        self.assertTrue(other.unsupported)

    def test_a_scenario_contract_can_still_stand_in_for_an_engine_action(self):
        b, _ = lab(MOVE, contracts={'Move': dict(reason='explicit fixture')})
        self.assertEqual((status(b), b.boundaries()), ('external', []))
        b.resolve('main', 'success')
        self.assertEqual(status(b), 'success')
        with self.assertRaises(ValueError): lab('<Success/>', contracts={'IfGate': dict(reason='no')})

    SEARCH = ('<GraphSearch Origin="$this.id" depth="1" failOnEmpty="%s">'
              '<LinkDataFilter tag="\'place\'" condition="$__link_place == \'chair\'" prune="true" negprune="false" Parent="" Child="$seat" Data=""/>'
              '<EvaLLyzer Expresion="$who = $__link_actor" Quantifiers="Exists" saveVersion="2"/>'
              '<Nodalyzer Quantifiers="Exists" Parent="" Child="$node" saveVersion="2"/></GraphSearch>')

    def test_graph_search_result_comes_from_the_scenario(self):
        b, _ = lab('<Sequence>' + self.SEARCH % 'true' + BUMP + '</Sequence>')
        (_, boundary), = b.boundaries()
        self.assertEqual((b.unsupported, boundary['writes'], boundary['outcomes']), ([], ['seat', 'who', 'node'], ['match', 'empty']))
        with self.assertRaises(ValueError): b.resolve('main', 'match', {'seat': 'chair-1'})        # not every output
        b.resolve('main', 'match', {'seat': 'chair-1', 'who': 'mother', 'node': 'n'})
        self.assertEqual((status(b), b.variables['seat'], b.variables['who'], b.variables['count']), ('success', 'chair-1', 'mother', 1))
        for fail_on_empty, result in (('true', 'fail'), ('false', 'success')):
            b, _ = lab('<Sequence>' + self.SEARCH % fail_on_empty + BUMP + '</Sequence>')
            b.resolve('main', 'empty')
            self.assertEqual(status(b), result)
        odd, _ = lab('<GraphSearch Origin="" depth="1" failOnEmpty="true"><DistanceFilter max="3"/></GraphSearch>', start=False)
        self.assertTrue(any('DistanceFilter' in u['reason'] for u in odd.unsupported))

    def test_lua_gate_takes_the_branch_the_scenario_supplies(self):
        gate = '<LuaGate code="return entity.inventory:GetMoney() > 5" saveVersion="2"><Then>' + BUMP + '</Then><Else><Fail/></Else></LuaGate>'
        for outcome, result in (('true', ('success', 1)), ('false', ('fail', 0))):
            b, _ = lab(gate)
            self.assertEqual(pending(b), [('LuaGate', 'lua')])
            b.resolve('main', outcome)
            self.assertEqual((status(b), b.variables['count']), result)

    def test_execute_lua_is_a_declared_cluster_effect(self):
        code = "Utils.SetWorldTimePaused(false, 'q') data.paused = false"
        script = '<ExecuteLua code="%s"/>' % code
        b, _ = lab(script, lua={code: dict(cluster='TIME', assign={'$paused': False})}, variables={'paused': True})
        self.assertEqual((b.unsupported, status(b), b.variables['paused']), ([], 'success', False))
        self.assertEqual([(e['effect'], e['cluster'], e['changes']) for e in b.effects], [('lua', 'TIME', {'paused': False})])
        undeclared, _ = lab(script, start=False)
        self.assertEqual([u['reason'] for u in undeclared.unsupported], ['Lua script has no declared cluster effect'])
        with self.assertRaises(Unsupported): undeclared.start('main')
        with self.assertRaises(ValueError): lab(script, lua={code: dict(assign={})})

    SEND = ('<SendMessageToNPC target="$this.id" type="\'dialog:monologRequest\'" values="alias(%s),lookAtId($spot)" '
            'timeType="GameTime" timeoutType="OnProcessed" timeout="\'-1\'" answer=""/>')

    def test_send_message_waits_until_the_receiver_processed_it(self):
        for outcome, result in (('processed', 'success'), ('failed', 'fail')):
            b, _ = lab(self.SEND % "'q_bark'")
            self.assertEqual(pending(b), [('SendMessageToNPC', 'message')])
            self.assertEqual([(m['receiver'], m['message_type'], m['content']) for m in b.graph.messages],
                             [('npc', 'dialog:monologRequest', {'alias': 'q_bark', 'lookAtId': 'spot'})])
            b.resolve('main', outcome)
            self.assertEqual((status(b), b.graph.messages), (result, []))
        timed, _ = lab((self.SEND % "'q_bark'").replace("timeout=\"'-1'\"", "timeout=\"'5s'\""), start=False)
        self.assertTrue(timed.unsupported)

    def test_bare_word_in_a_message_field_is_a_string_only_under_its_assumption(self):
        b, _ = lab(self.SEND % 'q_bark')
        self.assertEqual(b.graph.messages[0]['content']['alias'], 'q_bark')
        self.assertTrue(any(r['kind'] == 'behavior_bare_word' for r in b.graph.trace))
        with self.assertRaisesRegex(Unsupported, 'behavior.message.bare_word'):
            lab(self.SEND % 'q_bark', assumptions={k: v for k, v in ASSUMED.items() if k != 'behavior.message.bare_word'})

    def test_multi_send_queues_one_message_per_target(self):
        b, _ = lab('<InstantMultiSendMessageToNPC targets="$npcs" successMode="Any" failureMode="Any" type="\'cue\'" values="go(true)"/>',
                   variables={'npcs': ['a', 'b', 'c']})
        self.assertEqual((status(b), [m['receiver'] for m in b.graph.messages]), ('success', ['a', 'b', 'c']))

    def test_area_listener_runs_its_child_per_tracked_event_and_keeps_listening(self):
        listener = '<AreaPresenceListener aiObjects="$spot" area="$spot" trackIn="true" trackOut="%s" reportInitialState="true">' + BUMP + '</AreaPresenceListener>'
        for track_out, expected in (('true', 3), ('false', 2)):
            b, _ = lab(listener % track_out)
            for event in ('in', 'out', 'in'):
                self.assertEqual(pending(b), [('AreaPresenceListener', 'listener')])
                b.resolve('main', event)
            self.assertEqual((status(b), b.variables['count']), ('external', expected))


class EffectTests(unittest.TestCase):
    def test_buffs_links_teleports_and_game_over_are_a_ledger(self):
        b, _ = lab('<Sequence><AddBuff SoulWUID="" BuffGUID="\'b1\'"/><AddBuff SoulWUID="$spot" BuffGUID="\'b2\'"/>'
                   '<RemoveBuffs SoulWUID="$this.id" BuffGUID="\'b1\'" BuffTagId="-1"/>'
                   '<GetTime TimeType="GameTime" OutVar="$stamp" Delta="1m"/>'
                   '<AddLink From="$this.id" To="$spot" Tag="\'calm\'" Data="$stamp" LinkOpHandleMode="Error"/>'
                   '<GetSpatialInfo In="$spot" Out="$where" What="Transform"/><SetSpatialInfo In="$this.id" Val="$where" What="Transform"/>'
                   '<GameOver Reason="DiedInJail"/></Sequence>', variables={'stamp': 0, 'where': None})
        self.assertEqual((b.unsupported, status(b)), ([], 'success'))
        self.assertEqual([e['effect'] for e in b.effects],
                         ['add_buff', 'add_buff', 'remove_buffs', 'add_link', 'set_spatial', 'game_over'])
        self.assertEqual((b.buffs, b.links, b.variables['stamp']), ({'spot': ['b2']}, [['npc', 'spot', 'calm', 60000000]], 60000000))
        self.assertEqual(b.effects[-2]['value'], dict(spatial='Transform', of='spot'))
        self.assertEqual(b.effects[-1]['reason'], 'DiedInJail')
        with self.assertRaises(Unsupported): lab('<RemoveBuffs SoulWUID="" BuffGUID="\'b\'" BuffTagId="4"/>')

    def test_state_survives_a_snapshot_and_a_changed_tree_is_refused(self):
        b, _ = lab('<Sequence><AddBuff SoulWUID="" BuffGUID="\'b1\'"/>' + SET % ('Local', 'true')
                   + '<DistanceGate Origin="" ReferencePt="$spot" Low="1" High="2" Negation="false" OpenInMiddle="false" RunLogic="Halt">'
                   + MOVE + '</DistanceGate>' + BUMP + '</Sequence>')
        saved, graph = b.snapshot(), b.graph.snapshot()
        b.resolve('main', 'open'); b.resolve('main', 'success')
        self.assertEqual((status(b), b.variables['count']), ('success', 1))
        b.graph.restore(graph); b.restore(saved)
        self.assertEqual((pending(b), b.locks, b.buffs, len(b.effects), b.variables['count']),
                         ([('DistanceGate', 'gate')], {'Local|door': True}, {'npc': ['b1']}, 2, 0))
        b.resolve('main', 'open'); b.resolve('main', 'fail')
        self.assertEqual(status(b), 'fail')
        other, _ = lab('<Success/>')
        with self.assertRaises(ValueError): other.restore(saved)

    def test_state_key_ignores_the_clock_and_the_effect_ledger_but_not_the_position(self):
        tree = '<Loop count="-1"><Sequence><GameOver Reason="x"/><Wait duration="\'10s\'" timeType="GameTime" doFail="false" variation=""/></Sequence></Loop>'
        b, _ = lab(tree)
        first = b.state_key()
        b.graph.advance_to(b.next_deadline()); b.pump()
        self.assertEqual((b.state_key(), len(b.effects)), (first, 2))
        b.graph.advance_to(b.graph.now + 1000000)
        self.assertNotEqual(b.state_key(), first)


class ExpressionTests(unittest.TestCase):
    def test_conditional_negation_and_compound_assignment(self):
        values = dict(name='janek', n=5, flag=False, t=dict(x=1))
        self.assertEqual(evaluate("$name == 'janek' ? 'a' : 'b'", values), 'a')
        self.assertEqual(evaluate("$name == 'x' ? 'a' : $n > 3 ? 'b' : 'c'", values), 'b')
        self.assertEqual(evaluate("'a ? b : c'", values), 'a ? b : c')
        self.assertTrue(evaluate('~$flag', values))
        assignments("$n -= 2, $t.x += 1.5, $who = $name == 'janek' ? 'j' : 'k',", values)
        self.assertEqual((values['n'], values['t']['x'], values['who']), (3, 2.5, 'j'))
        with self.assertRaises(Unsupported): evaluate('$n ? 1', values)
        with self.assertRaises(Unsupported): evaluate('$n ? 1 : 2', values)             # the test must be a boolean

    def test_engine_record_is_carried_and_an_unset_member_needs_its_assumption(self):
        types = b'''<Root><Types version="1"><Type Name="next"><Member Name="name" Type="_string"/>
            <Member Name="tries" Type="_int" InitialValue="2"/></Type></Types></Root>'''
        tree = ('<BehaviorTree name="main"><Variables><Variable name="move" type="additionalMoveParams" '
                'values="destChangedThreshold(\'2s\')" form="single"/><Variable name="t" type="next" values="" form="single"/></Variables>'
                '<Root><Behavior><Expression expressions="$t.name = \'Wait\'"/></Behavior></Root></BehaviorTree>').encode()
        for assumed, works in ((ASSUMED, True), ({k: v for k, v in ASSUMED.items() if k != 'behavior.record.unset_member'}, False)):
            graph = Graph(Source.blobs({'graph.xml': PROJECT, 'types.xml': types}), 'Test', assumptions=assumed)
            b = Behavior('test', tree, graph)
            if not works:
                with self.assertRaises(Unsupported): b.start('main', 'main')
                continue
            b.start('main', 'main')
            local = b.tasks['main']['locals']
            self.assertEqual(local['t'], dict(name='Wait', tries=2))
            self.assertEqual(local['move'], dict(engine_record='additionalMoveParams', initializer="destChangedThreshold('2s')"))

    def start(self, variables, expressions, assumed=ASSUMED, types=b'<Root/>'):
        tree = ('<BehaviorTree name="main"><Variables>%s</Variables><Root><Behavior><Expression expressions="%s"/>'
                '</Behavior></Root></BehaviorTree>' % (variables, expressions)).encode()
        b = Behavior('test', tree, Graph(Source.blobs({'graph.xml': PROJECT, 'types.xml': types}), 'Test', assumptions=assumed))
        b.start('main', 'main')
        return b, b.tasks['main']['locals']

    def without(self, name):
        return {k: v for k, v in ASSUMED.items() if k != name}

    def test_a_member_of_an_engine_record_is_kept_only_once_a_tree_assigns_it(self):
        declared = ('<Variable name="f" type="followFormationParams" values="" form="single"/>'
                    '<Variable name="p" type="dialog:parameters:initiator" values="" form="single"/>'
                    '<Variable name="on" type="_bool" values="true" form="single"/>')
        b, local = self.start(declared, "$f.formation.type = 'followNPC'&#10;$p.enableGreeting = !$on&#10;$p.movePlayer = $on")
        self.assertEqual((status(b), b.unsupported), ('success', []))
        self.assertEqual(local['f'], dict(engine_record='followFormationParams', initializer='',
                                          formation=dict(engine_record='followFormationParams.formation', type='followNPC')))
        self.assertEqual({k: v for k, v in local['p'].items() if k not in ('engine_record', 'initializer')},
                         dict(enableGreeting=False, movePlayer=True))
        self.assertTrue(b.graph.world.report()['assumptions']['behavior.engine_record.member']['used'])
        # Mutations: no assumption; a member nothing assigned is still unreadable; a record the lab knows stays closed.
        with self.assertRaisesRegex(Unsupported, 'Unbound assignment'):
            self.start(declared, "$f.formation.type = 'followNPC'", self.without('behavior.engine_record.member'))
        with self.assertRaises(Unsupported): self.start(declared, '$on = $p.chat')
        with self.assertRaises(Unsupported): self.start(declared, '$on = $f.formation.leader == $on')
        types = b'<Root><Types version="1"><Type Name="next"><Member Name="name" Type="_string"/></Type></Types></Root>'
        with self.assertRaisesRegex(Unsupported, 'Unbound assignment member: other'):
            self.start('<Variable name="t" type="next" values="" form="single"/>', "$t.other = 'x'", types=types)
        _, quiet = self.start('<Variable name="on" type="_bool" values="true" form="single"/>', '$on = false')
        self.assertEqual(quiet, dict(on=False))

    def test_assigning_just_past_the_end_of_an_array_appends(self):
        declared = '<Variable name="who" type="_wuid" values="" form="array"/>'
        b, local = self.start(declared, "$who[0] = 'a'&#10;$who[1] = 'b'&#10;$who[2] = 'c'&#10;$who[0] = 'z'")
        self.assertEqual((local['who'], b.graph.world.report()['assumptions']['behavior.array.assign_at_end']['used']),
                         (['z', 'b', 'c'], True))
        with self.assertRaisesRegex(Unsupported, 'Invalid assignment array index'): self.start(declared, "$who[1] = 'b'")
        with self.assertRaisesRegex(Unsupported, 'Invalid assignment array index'): self.start(declared, "$who[-1] = 'b'")
        with self.assertRaisesRegex(Unsupported, 'Invalid assignment array index'):
            self.start(declared, "$who[0] = 'a'", self.without('behavior.array.assign_at_end'))

    def test_an_entity_reference_member_is_unset_until_assigned(self):
        types = (b'<Root><Types version="1"><Type Name="talk"><Member Name="alias" Type="string"/>'
                 b'<Member Name="lookAtId" Type="wuid"/><Member Name="greet" Type="bool" InitialValue="true"/></Type></Types></Root>')
        declared = '<Variable name="t" type="talk" values="" form="single"/>'
        _, local = self.start(declared, "$t.alias = 'hello'&#10;$t.lookAtId = 'npc'", types=types)
        self.assertEqual(local['t'], dict(alias='hello', lookAtId='npc', greet=True))
        # Mutations: without the unset-member assumption the record does not exist; a default is not invented.
        with self.assertRaises(Unsupported):
            self.start(declared, "$t.alias = 'hello'", self.without('behavior.record.unset_member'), types)
        with self.assertRaises(Unsupported):
            self.start(declared, "$t.alias = 'hello'", types=types.replace(b'Type="wuid"', b'Type="wuid" InitialValue="x"'))

    def test_an_unlimited_loop_until_is_the_same_state_after_a_failed_attempt(self):
        loop = '<LoopUntil until="Success" attemptCount="%d">' + MOVE + '</LoopUntil>'
        keys = {}
        for limit in (0, 3):
            b, _ = lab(loop % limit)
            first = b.state_key()
            b.resolve('main', 'fail')
            keys[limit] = (first == b.state_key(), pending(b))
        self.assertEqual(keys, {0: (True, [('Move', 'action')]), 3: (False, [('Move', 'action')])})
        b, _ = lab(loop % 2)
        b.resolve('main', 'fail'); b.resolve('main', 'fail')
        self.assertEqual(status(b), 'fail')


if __name__ == '__main__': unittest.main()
