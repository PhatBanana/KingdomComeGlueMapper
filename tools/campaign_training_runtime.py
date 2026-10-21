"""Acknowledged lifecycle around the native combat tutorial controller.

World/AI adapters supply scoped arrival, equipment and stop callbacks. No actor,
item, location or quest is selected here. Cleanup must acknowledge before the
host is told to advance its source completion path.
"""
import xml.etree.ElementTree as E

from campaign_native_training import emit as tutorial
from campaign_quest_graph import edge, constant, all_of, any_of, xml


def emit(name, domain, contract):
    blob, report = tutorial(name, domain, contract)
    root = E.fromstring(blob)
    host = root.find('./Skald/Module')
    ports, nodes = host.find('Ports'), host.find('Nodes')
    output = nodes.find('Output')
    controller = nodes.find('CombatTutorialNode')
    for port in list(ports):
        if port.get('Name') in ('isactive', 'continue', 'finished'):
            ports.remove(port)
    for e in list(output):
        if e.get('To') == 'finished': output.remove(e)
    for e in list(controller):
        if e.tag == 'Edge' and e.get('To') in ('IsActive', 'CustomStepEvent'): controller.remove(e)

    def port(n, typ='trigger', direction='In'):
        E.SubElement(ports, 'Port', Name=n, Direction=direction, Type=typ)
    for n in ('request', 'cancel', 'arrived', 'arrival_failed', 'prepared', 'preparation_failed',
              'readiness_changed', 'dialogue_finished', 'instruction_ack', 'workers_stopped',
              'cleanup_done', 'cleanup_failed', 'retry_cleanup', 'authorization_changed'):
        port(n)
    for n in ('tutor_ready', 'dialogue_busy', 'lesson_authorized'): port(n, 'bool')
    port('ack_phase', 'int')
    for n in ('arrive', 'prepare', 'stop_workers', 'cleanup', 'started', 'exercises_finished', 'finished', 'canceled', 'fault'):
        port(n, direction='Out')
    for n in ('busy', 'training_active'): port(n, 'bool', 'Out')

    def state(n):
        s = E.SubElement(nodes, 'State', Name=n, TypeT='bool')
        constant(s, 'DefaultValue', 'false')
        return s
    states = {n:state(n) for n in ('arriving', 'at_destination', 'preparing', 'waiting', 'running', 'stopping',
                                  'cleaning', 'completion_pending', 'ack_used')}
    def invert(n, value):
        s = E.SubElement(nodes, 'Function', Name=n, MethodName='math::boolean::Not', DeclaringType='math::boolean')
        edge(s, value, 'Value')
        return n + '.bool'
    def gate(n, event, condition):
        g = E.SubElement(nodes, 'If', Name=n)
        edge(g, event, 'Exec'); edge(g, condition, 'Condition')
        return n + '.True'
    def order(n, event):
        s = E.SubElement(nodes, 'TriggerSequence', Name=n)
        edge(s, event, 'Exec')
        return n
    def set_state(n, event, value): edge(states[n], event, 'SetTrue' if value else 'SetFalse')
    def send(event, out): edge(output, event, out)

    busy = any_of(nodes, 'session_busy', [n+'.State' for n in ('arriving','at_destination','preparing','waiting','running','stopping','cleaning')])
    send(busy, 'busy'); send('running.State', 'training_active')
    accepted = order('accept_order', gate('accept_request', 'request', invert('idle', busy)))
    set_state('completion_pending', accepted+'.A', False)
    set_state('arriving', accepted+'.B', True)
    send(accepted+'.C', 'arrive')
    arrived = order('arrived_order', gate('accept_arrival', 'arrived', 'arriving.State'))
    set_state('arriving', arrived+'.A', False)
    set_state('at_destination', arrived+'.B', True)
    ready_to_prepare = E.SubElement(nodes, 'If', Name='authorized_preparation')
    for event in (arrived+'.C', 'authorization_changed'): edge(ready_to_prepare, event, 'Exec')
    edge(ready_to_prepare, all_of(nodes, 'may_prepare', ['at_destination.State', 'lesson_authorized']), 'Condition')
    preparation = order('preparation_order', 'authorized_preparation.True')
    set_state('at_destination', preparation+'.A', False)
    set_state('preparing', preparation+'.B', True)
    send(preparation+'.C', 'prepare')
    prepared = order('prepared_order', gate('accept_preparation', 'prepared', 'preparing.State'))
    set_state('preparing', prepared+'.A', False)
    set_state('waiting', prepared+'.B', True)
    can_start = all_of(nodes, 'can_start', ['waiting.State', 'tutor_ready', invert('not_talking', 'dialogue_busy')])
    start = E.SubElement(nodes, 'If', Name='begin')
    for event in (prepared+'.C', 'readiness_changed', 'dialogue_finished'): edge(start, event, 'Exec')
    edge(start, can_start, 'Condition')
    begun = order('begin_order', 'begin.True')
    set_state('waiting', begun+'.A', False)
    set_state('ack_used', begun+'.A', False)
    set_state('running', begun+'.B', True)
    send(begun+'.C', 'started')
    edge(controller, 'running.State', 'IsActive')

    # Match the phase acknowledged by the instruction, and consume it once.
    # The host must dispatch only the native lesson's explicit instruction barriers.
    compare = E.SubElement(nodes, 'IfFunction', Name='instruction_phase', TypeT='int',
                           MethodName='Control::Compare', DeclaringType='Control')
    constant(compare, 'Op', 'Equals')
    edge(compare, 'instruction_ack', 'Exec')
    edge(compare, 'ack_phase', 'ValueA'); edge(compare, 'training.Phase', 'ValueB')
    allowed = all_of(nodes, 'instruction_allowed', ['running.State','not_talking.bool', invert('ack_unused','ack_used.State')])
    ack = order('ack_order', gate('accept_instruction', 'instruction_phase.True', allowed))
    set_state('ack_used', ack+'.A', True)
    edge(controller, ack+'.B', 'CustomStepEvent')
    set_state('ack_used', 'training.OnPhaseStart', False)

    # Stop workers before issuing cleanup: cancellation must not race a late
    # item creation. Host callbacks must belong to the stopped invocation.
    success = gate('accept_success', 'training.OnTutorialEnd', 'running.State')
    successful = order('success_order', success)
    set_state('completion_pending', successful+'.A', True)
    send(successful+'.A', 'exercises_finished')
    stop = order('stop_order', successful+'.B')
    cancellable = any_of(nodes, 'cancellable', [n+'.State' for n in ('arriving','at_destination','preparing','waiting','running')])
    canceled = gate('accept_cancel', 'cancel', cancellable)
    edge(nodes.find("TriggerSequence[@Name='stop_order']"), canceled, 'Exec')
    set_state('completion_pending', 'cancel', False)
    for event, phase in [('arrival_failed','arriving'),('preparation_failed','preparing')]:
        failure = gate('accept_'+event, event, phase+'.State')
        edge(nodes.find("TriggerSequence[@Name='stop_order']"), failure, 'Exec')
        send(failure, 'fault')
    lost = gate('lost_readiness', 'readiness_changed', all_of(nodes,'ready_lost',
                ['running.State', invert('tutor_not_ready', 'tutor_ready')]))
    edge(nodes.find("TriggerSequence[@Name='stop_order']"), lost, 'Exec'); send(lost,'fault')
    for phase in ('arriving','at_destination','preparing','waiting','running'): set_state(phase, stop+'.A', False)
    set_state('stopping', stop+'.B', True)
    send(stop+'.C', 'stop_workers')
    stopped = order('stopped_order', gate('accept_stopped', 'workers_stopped', 'stopping.State'))
    set_state('stopping', stopped+'.A', False)
    set_state('cleaning', stopped+'.B', True)
    send(stopped+'.C', 'cleanup')
    send(gate('retry_cleanup_guard', 'retry_cleanup', 'cleaning.State'), 'cleanup')
    send(gate('cleanup_failed_guard', 'cleanup_failed', 'cleaning.State'), 'fault')
    cleaned = gate('accept_cleaned', 'cleanup_done', 'cleaning.State')
    result = E.SubElement(nodes, 'If', Name='cleanup_result')
    edge(result, cleaned, 'Exec'); edge(result, 'completion_pending.State', 'Condition')
    for branch, event in [('True','finished'),('False','canceled')]:
        done = order(event+'_order', 'cleanup_result.'+branch)
        for phase in ('cleaning','completion_pending','ack_used'): set_state(phase, done+'.A', False)
        send(done+'.B', event)
    report.update(required_host_bindings=['tutor','request','cancel','arrived','prepared','tutor_ready',
        'readiness_changed','dialogue_busy','dialogue_finished','instruction_ack','ack_phase',
        'workers_stopped','cleanup_done','lesson_authorized','authorization_changed'], runtime_validated=False,
        completion_event='finished after OnTutorialEnd and cleanup_done',
        callback_contract='Invocation-scoped; workers_stopped means no further item creation or callbacks from that invocation.')
    return xml(root), report
