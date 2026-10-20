"""Wire resolved quest objectives and a native arrival worker to training.

Objective bindings are explicit converter outputs. This module never infers
an objective from an NPC name, dialogue text or source phase number.
"""
import xml.etree.ElementTree as E
from campaign_quest_graph import edge, constant, identifier, all_of


def bind(nodes, lifecycle, quest, quest_definition, arrival_worker, objectives, cancel_events, reconcile_events=()):
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
    for role in ('arrival', 'completion'): require('complete_'+objectives[role], 'In', 'trigger')
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
    edge(request, all_of(nodes, name+'_new_request',
        [q+'.'+objectives['arrival']+'_Started', not_sent.get('Name')+'.bool',
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
    return dict(objectives=objectives, runtime_validated=False,
                requires_resolved_arrival_worker=True, requires_invocation_scoped_callbacks=True)


def _idle(nodes, name, lifecycle):
    check = E.SubElement(nodes, 'Function', Name=name+'_idle',
        MethodName='math::boolean::Not', DeclaringType='math::boolean')
    edge(check, lifecycle+'.busy', 'Value')
    return check.get('Name')+'.bool'
