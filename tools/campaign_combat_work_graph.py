"""Wire native work phases to the combat and dialogue completion events."""
import xml.etree.ElementTree as E
from campaign_quest_graph import edge, constant


def wire(nodes, stem, plan, assets, actor, quest, fight, cancel_events):
    phases = {}
    waiting = E.SubElement(nodes, 'State', Name=stem + '_work_waiting_dialogue', TypeT='bool')
    constant(waiting, 'DefaultValue', 'false')
    for event in [*cancel_events, stem + '.requested']:
        edge(waiting, event, 'SetFalse')
    phases['waiting_dialogue'] = waiting
    def predicate(g, name):
        value = quest + '.' + g['objective'] + '_' + g['function'].removeprefix('IsObjective')
        if g['negate']:
            n = E.SubElement(nodes, 'Function', Name=name, MethodName='math::boolean::Not', DeclaringType='math::boolean')
            edge(n, value, 'Value'); value = name + '.bool'
        return value
    for phase in ('prepare', 'privacy', 'routine'):
        name = stem + '_work_' + phase
        state = E.SubElement(nodes, 'State', Name=name, TypeT='bool'); constant(state, 'DefaultValue', 'false')
        for event in cancel_events:
            edge(state, event, 'SetFalse')
        enable = E.SubElement(nodes, 'EnableBehavior', Name=name + '_enable', Signature=stem + '_work', EventSet='resultNotification')
        constant(enable, 'Behavior', phase); constant(enable, 'ForceKick', 'true')
        E.SubElement(enable, 'Asset', Name='NPC', Alias=actor)
        for port, alias in [('SmartEntity', assets['host']), ('homeArea', assets['area']), ('workPlace', assets['place'])]:
            E.SubElement(enable, 'Asset', Name=port, Alias=alias)
        if assets['tool']:
            E.SubElement(enable, 'Asset', Name='toolSlot', Alias=assets['tool'])
        edge(enable, name + '.State', 'IsActive')
        if plan.get('preparation') and assets['tool']:
            edge(enable, predicate(plan['preparation']['guard'], name + '_cleanup_guard'), 'cleanupTool')
        else:
            constant(enable, 'cleanupTool', 'false')
        edge(enable, predicate(plan['outcomes']['won']['aftermath']['privacy']['guard'], name + '_privacy_guard'), 'removePrivacy')
        # Native callbacks belong to this invocation, unlike a global signal.
        # Ignore completion after quest cancellation or a superseding request.
        done = E.SubElement(nodes, 'If', Name=name + '_done')
        edge(done, enable.get('Name') + '.Success', 'Exec')
        edge(done, name + '.State', 'Condition')
        seq = E.SubElement(nodes, 'TriggerSequence', Name=name + '_finish')
        edge(seq, name + '_done.True', 'Exec')
        edge(state, name + '_finish.A', 'SetFalse')
        edge(state, enable.get('Name') + '.Fail', 'SetFalse')
        phases[phase] = dict(state=state, finished=name + '_finish.B')
    if plan.get('preparation'):
        edge(phases['prepare']['state'], stem + '.prepare', 'SetTrue')
        edge(fight, phases['prepare']['finished'], 'prepared')
    # A new request replaces the previous post-fight routine.
    for phase in ('privacy', 'routine'):
        edge(phases[phase]['state'], stem + '.requested', 'SetFalse')
    return phases


def after_privacy(nodes, stem, aftermath, quest, event, phases):
    edge(phases['privacy']['state'], event, 'SetTrue')
    g = aftermath['dialogue']['guard']
    value = quest + '.' + g['objective'] + '_' + g['function'].removeprefix('IsObjective')
    branch = E.SubElement(nodes, 'If', Name=stem + '_work_dialogue_guard')
    edge(branch, phases['privacy']['finished'], 'Exec'); edge(branch, value, 'Condition')
    shown, skipped = ('False', 'True') if g['negate'] else ('True', 'False')
    edge(phases['routine']['state'], branch.get('Name') + '.' + skipped, 'SetTrue')
    edge(phases['waiting_dialogue'], branch.get('Name') + '.' + shown, 'SetTrue')
    return branch.get('Name') + '.' + shown


def after_dialogue(nodes, stem, instance, phases):
    waiter = E.SubElement(nodes, 'SceneFinishedWaiter', Name=stem + '_work_dialogue_release')
    edge(waiter, instance.get('Name') + '.AfterPlay', 'Enqueue')
    guard = E.SubElement(nodes, 'If', Name=stem + '_work_dialogue_still_pending')
    edge(guard, waiter.get('Name') + '.OnFinished', 'Exec')
    edge(guard, phases['waiting_dialogue'].get('Name') + '.State', 'Condition')
    seq = E.SubElement(nodes, 'TriggerSequence', Name=stem + '_work_dialogue_completed')
    edge(seq, guard.get('Name') + '.True', 'Exec')
    edge(phases['waiting_dialogue'], seq.get('Name') + '.A', 'SetFalse')
    edge(phases['routine']['state'], seq.get('Name') + '.B', 'SetTrue')
