"""Wire resolved quest objectives and a native arrival worker to training.

Objective bindings are explicit converter outputs. This module never infers
an objective from an NPC name, dialogue text or source phase number.
"""
import xml.etree.ElementTree as E
from campaign_quest_graph import edge, constant, identifier, all_of, any_of


def bind(nodes, lifecycle, quest, quest_definition, arrival_worker, objectives, cancel_events, reconcile_events=(),
         *, arrival_completion='worker'):
    if arrival_completion not in ('worker', 'source_objective'):
        raise ValueError('Unknown arrival completion contract')
    if set(objectives) != {'arrival', 'authorization', 'completion'}:
        raise ValueError('Training requires arrival, authorization and completion objective bindings')
    ports = E.fromstring(quest_definition).find('./Skald/Quest/Ports')
    if ports is None: raise ValueError('Missing compiled source quest ports')
    def require(name, direction, typ):
        if ports.find("Port[@Name='" + name + "'][@Direction='" + direction + "'][@Type='" + typ + "']") is None:
            raise ValueError('Missing source quest port: ' + name)
    for objective in objectives.values(): identifier(objective)
    require(objectives['arrival']+'_Started', 'Out', 'bool')
    require(objectives['authorization']+'_Started', 'Out', 'bool')
    require('complete_'+objectives['completion'], 'In', 'trigger')
    if arrival_completion == 'source_objective':
        require(objectives['arrival']+'_Completed', 'Out', 'bool')
        require(objectives['completion']+'_Completed', 'Out', 'bool')
    else:
        require('complete_'+objectives['arrival'], 'In', 'trigger')
    require('source_state_changed', 'Out', 'trigger')
    if arrival_worker.tag != 'EnableBehavior' or arrival_worker.get('EventSet') != 'resultNotification':
        raise ValueError('Arrival worker requires native resultNotification events')
    if (any(e.get('To') == 'IsActive' for e in arrival_worker.findall('Edge'))
            or arrival_worker.find("Constant[@Name='IsActive']") is not None):
        raise ValueError('Arrival worker already scheduled')
    if any(e.get('To') in ('request','lesson_authorized','authorization_changed','arrived','arrival_failed')
           for e in lifecycle.findall('Edge')):
        raise ValueError('Training schedule already bound')
    name = identifier(lifecycle.get('Name')) + '_arrival'
    q = quest.get('Name')
    sent = E.SubElement(nodes, 'State', Name=name+'_request_sent', TypeT='bool')
    constant(sent, 'DefaultValue', 'false')
    # Cancellation/failure can leave the source arrival objective Started.
    # Release the request latch only after the lifecycle acknowledges cleanup;
    # a later source notification/reconcile may then retry that same objective.
    edge(sent, lifecycle.get('Name')+'.canceled', 'SetFalse')
    not_sent = E.SubElement(nodes, 'Function', Name=name+'_not_sent',
        MethodName='math::boolean::Not', DeclaringType='math::boolean')
    edge(not_sent, sent.get('Name')+'.State', 'Value')
    request = E.SubElement(nodes, 'If', Name=name+'_requested')
    reset = E.SubElement(nodes, 'If', Name=name+'_reset_request')
    edge(reset, q+'.'+objectives['arrival']+'_Started', 'Condition')
    edge(sent, reset.get('Name')+'.False', 'SetFalse')
    for event in (q+'.source_state_changed', *reconcile_events):
        edge(request, event, 'Exec'); edge(lifecycle, event, 'authorization_changed')
        edge(reset, event, 'Exec')
    pending_arrival = q+'.'+objectives['arrival']+'_Started'
    if arrival_completion == 'source_objective':
        # A migrated save may already be at the ring. Authorization can arrive
        # after the old departure worker has completed the source objective.
        pending_arrival = any_of(nodes,name+'_arrival_available',
            [pending_arrival,q+'.'+objectives['arrival']+'_Completed'])
        unfinished=E.SubElement(nodes,'Function',Name=name+'_unfinished',
            MethodName='math::boolean::Not',DeclaringType='math::boolean')
        edge(unfinished,q+'.'+objectives['completion']+'_Completed','Value')
        pending_arrival=all_of(nodes,name+'_unfinished_arrival',
            [pending_arrival,unfinished.get('Name')+'.bool'])
    edge(request, all_of(nodes, name+'_new_request',
        [pending_arrival, not_sent.get('Name')+'.bool',
         _idle(nodes, name, lifecycle.get('Name'))]), 'Condition')
    requested = E.SubElement(nodes, 'TriggerSequence', Name=name+'_request_order')
    edge(requested, request.get('Name')+'.True', 'Exec')
    edge(sent, requested.get('Name')+'.A', 'SetTrue')
    edge(lifecycle, requested.get('Name')+'.B', 'request')
    edge(lifecycle, q+'.'+objectives['authorization']+'_Started', 'lesson_authorized')
    running = E.SubElement(nodes, 'State', Name=name+'_running', TypeT='bool')
    constant(running, 'DefaultValue', 'false')
    edge(running, lifecycle.get('Name')+'.arrive', 'SetTrue')
    for event in (*cancel_events, lifecycle.get('Name')+'.stop_workers'): edge(running, event, 'SetFalse')
    for event in cancel_events: edge(lifecycle, event, 'cancel')
    edge(arrival_worker, running.get('Name')+'.State', 'IsActive')
    if arrival_completion == 'source_objective':
        # A complete source routine may Move, complete its arrival objective,
        # then wait/lean indefinitely. Its success event is not arrival. Keep
        # that authored waiting behavior alive until preparation takes over.
        waiting = E.SubElement(nodes, 'State', Name=name+'_waiting_for_arrival', TypeT='bool')
        constant(waiting, 'DefaultValue', 'false')
        edge(waiting, lifecycle.get('Name')+'.arrive', 'SetTrue')
        for event in (*cancel_events, lifecycle.get('Name')+'.stop_workers'):
            edge(waiting, event, 'SetFalse')
        edge(running, lifecycle.get('Name')+'.prepare', 'SetFalse')
        guard = E.SubElement(nodes, 'If', Name=name+'_source_completed')
        arrived_order = E.SubElement(nodes,'TriggerSequence',Name=name+'_arm_arrival')
        edge(arrived_order,lifecycle.get('Name')+'.arrive','Exec')
        for state in (running,waiting):
            for e in list(state.findall('Edge')):
                if e.get('To')=='SetTrue' and e.get('From')==lifecycle.get('Name')+'.arrive':state.remove(e)
            edge(state,arrived_order.get('Name')+'.A','SetTrue')
        for event in (q+'.source_state_changed', arrived_order.get('Name')+'.B', *reconcile_events):
            edge(guard, event, 'Exec')
        edge(guard, all_of(nodes, name+'_source_arrived',
            [waiting.get('Name')+'.State', running.get('Name')+'.State',
             q+'.'+objectives['arrival']+'_Completed']), 'Condition')
        order = E.SubElement(nodes, 'TriggerSequence', Name=name+'_source_arrived_order')
        edge(order, guard.get('Name')+'.True', 'Exec')
        edge(waiting, order.get('Name')+'.A', 'SetFalse')
        edge(lifecycle, order.get('Name')+'.B', 'arrived')
        # Failure before reaching the objective is an arrival failure. Failure
        # of the waiting pose afterwards must cancel, not deliver arrival again.
        failed = E.SubElement(nodes, 'If', Name=name+'_source_failed_active')
        edge(failed, arrival_worker.get('Name')+'.Fail', 'Exec')
        edge(failed, running.get('Name')+'.State', 'Condition')
        phase = E.SubElement(nodes, 'If', Name=name+'_source_failed_phase')
        edge(phase, failed.get('Name')+'.True', 'Exec')
        edge(phase, waiting.get('Name')+'.State', 'Condition')
        edge(lifecycle, phase.get('Name')+'.True', 'arrival_failed')
        edge(lifecycle, phase.get('Name')+'.False', 'cancel')
        edge(quest, lifecycle.get('Name')+'.finished', 'complete_'+objectives['completion'])
        return dict(objectives=objectives, arrival_completion=arrival_completion, runtime_validated=False,
                    requires_resolved_arrival_worker=True, requires_invocation_scoped_callbacks=True)
    for outcome, port in (('Success','arrived'), ('Fail','arrival_failed')):
        guard = E.SubElement(nodes, 'If', Name=name+'_'+outcome)
        edge(guard, arrival_worker.get('Name')+'.'+outcome, 'Exec')
        edge(guard, running.get('Name')+'.State', 'Condition')
        order = E.SubElement(nodes, 'TriggerSequence', Name=name+'_'+outcome+'_order')
        edge(order, guard.get('Name')+'.True', 'Exec')
        edge(running, order.get('Name')+'.A', 'SetFalse')
        if outcome == 'Success': edge(quest, order.get('Name')+'.B', 'complete_'+objectives['arrival'])
        edge(lifecycle, order.get('Name')+'.C', port)
    edge(quest, lifecycle.get('Name')+'.finished', 'complete_'+objectives['completion'])
    return dict(objectives=objectives, arrival_completion=arrival_completion, runtime_validated=False,
                requires_resolved_arrival_worker=True, requires_invocation_scoped_callbacks=True)


def _idle(nodes, name, lifecycle):
    check = E.SubElement(nodes, 'Function', Name=name+'_idle',
        MethodName='math::boolean::Not', DeclaringType='math::boolean')
    edge(check, lifecycle+'.busy', 'Value')
    return check.get('Name')+'.bool'
