"""Emit native quest-combat lifecycles from a resolved source combat plan.

The actor, thresholds, protection buffs, outcomes and partner roles are inputs
from conversion. No quest or character is selected by this module. Native
contracts are taken from utils/combat and fist_fights_common_library, rather
than the obsolete combat:stimulus:customBehaviorRequest message.
"""
import xml.etree.ElementTree as ET

from campaign_quest_graph import definition, edge, constant, all_of, identifier, xml

SOUL = 'wh::rpgmodule::I_Soul*'


def emit(name, plan):
    identifier(name)
    if plan['weapon'] != 'unarmed':
        raise ValueError('Combat weapon policy requires a native adapter')
    if not 0 <= plan['initial_health'] <= 100 or plan['player_health_divisor'] < 1:
        raise ValueError('Invalid combat health initialization')
    root, host = definition('Module', name)
    ports = ET.SubElement(host, 'Ports')
    definitions = ET.SubElement(host, 'Definitions')
    for helper in ('fightstop', 'fighteffect'):
        ET.SubElement(definitions, 'Definition', File=name + '/' + helper + '.xml')
    nodes = ET.SubElement(host, 'Nodes')
    output = ET.SubElement(nodes, 'Output', Name='Output')

    def port(n, typ='trigger', direction='In'):
        ET.SubElement(ports, 'Port', Name=n, Direction=direction, Type=typ)
    for n in ('request', 'cancel', 'dialogue_finished'):
        port(n)
    for n in ('dialogue_busy', 'party_ready'):
        port(n, 'bool')
    for n in ('actor', 'player'):
        port(n, SOUL)
    # Combat and preparation share the generated local behavior host.
    port('scheduler', 'wh::xgenaimodule::SmartObject*')
    port('home', 'wh::entitymodule::TagPoint*')
    for i, _ in enumerate(plan['partners']):
        port('partner_' + str(i), SOUL)
    for n in ('won', 'lost', 'distance_lost', 'started', 'engaged', 'stopped', 'requested'):
        port(n, direction='Out')
    port('active', 'bool', 'Out')
    if plan.get('preparation'):
        port('prepared')
        port('prepare', direction='Out')

    def node(tag, n, edges=(), constants=(), **attrs):
        x = ET.SubElement(nodes, tag, Name=n, **attrs)
        for a, b in edges: edge(x, a, b)
        for a, b in constants: constant(x, a, b)
        return x
    def state(n):
        return node('State', n, constants=[('DefaultValue', 'false')], TypeT='bool')
    def invert(n, source):
        node('Function', n, [(source, 'Value')], MethodName='math::boolean::Not', DeclaringType='math::boolean')
        return n + '.bool'
    def gate(n, trigger, condition):
        node('If', n, [(trigger, 'Exec'), (condition, 'Condition')])
        return n + '.True'
    def sequence(n, trigger):
        return node('TriggerSequence', n, [(trigger, 'Exec')])
    pending, active, stopping = state('pending'), state('fighting'), state('stopping')
    edge(output, 'fighting.State', 'active')
    idle = all_of(nodes, 'idle', [invert('not_fighting', 'fighting.State'),
        invert('not_stopping', 'stopping.State'), invert('not_pending', 'pending.State')])
    accepted = gate('accept', 'request', idle)
    edge(output, accepted, 'requested')
    # The pending latch is set before checking whether the dialogue has ended.
    sequence('request_order', accepted)
    edge(pending, 'request_order.A', 'SetTrue')
    can_start = all_of(nodes, 'can_start', ['pending.State',
        invert('not_talking', 'dialogue_busy'), 'not_stopping.bool'])
    begin = gate('begin', 'request_order.B', can_start)
    node('If', 'begin_after_dialogue', [('dialogue_finished', 'Exec'), (can_start, 'Condition')])
    if plan.get('preparation'):
        preparing = state('preparing')
        prepared = state('preparation_ready')
        start_prep = sequence('prepare_order', gate('prepare_once', begin, invert('not_preparing', 'preparing.State')))
        retry = node('If', 'prepare_after_dialogue', [('begin_after_dialogue.True', 'Exec'), ('not_preparing.bool', 'Condition')])
        edge(start_prep, 'prepare_after_dialogue.True', 'Exec')
        edge(preparing, 'prepare_order.A', 'SetTrue')
        edge(output, 'prepare_order.B', 'prepare')
        # A delayed acknowledgement after cancellation cannot start a fight.
        ready = gate('prepared_pending', 'prepared', all_of(nodes, 'prepared_allowed', ['pending.State', 'preparing.State']))
        acknowledged = sequence('prepare_ack_order', ready)
        edge(prepared, 'prepare_ack_order.A', 'SetTrue')
        finish_allowed = all_of(nodes, 'prepared_can_initialize', [can_start, 'preparing.State', 'preparation_ready.State'])
        finish = node('If', 'prepared_finish', [('prepare_ack_order.B', 'Exec'),
            ('dialogue_finished', 'Exec'), (finish_allowed, 'Condition')])
        finished = sequence('prepared_order', 'prepared_finish.True')
        edge(preparing, 'prepared_order.A', 'SetFalse')
        edge(prepared, 'prepared_order.A', 'SetFalse')
        edge(preparing, 'cancel', 'SetFalse')
        edge(prepared, 'cancel', 'SetFalse')
        init = sequence('initialize', 'prepared_order.B')
    else:
        init = sequence('initialize', begin)
        edge(init, 'begin_after_dialogue.True', 'Exec')
    edge(pending, 'initialize.A', 'SetFalse')
    edge(pending, 'cancel', 'SetFalse')
    node('MemberFunction', 'reset_health', [('actor', 'Soul'), ('initialize.B', 'Exec')],
         [('State', 'health'), ('Value', plan['initial_health'])],
         MethodName='SetState', DeclaringType='wh::rpgmodule::I_Soul')
    node('MemberFunction', 'player_health', [('player', 'Soul')], [('State', 'health')],
         MethodName='GetState', DeclaringType='wh::rpgmodule::I_Soul')
    node('Function', 'threshold', [('player_health.Value', 'A')], [('B', plan['player_health_divisor'])],
         MethodName='wh::conceptmodule::math::DivideFloat', DeclaringType='wh::conceptmodule::math')
    # Snapshot once. A live HP/2 expression would move the surrender threshold
    # down on every hit and could never be crossed.
    node('State', 'player_threshold', [('threshold.float', 'Value'), ('initialize.C', 'Exec')], TypeT='float')
    sequence('initialize_protection', 'initialize.D')
    edge(active, 'initialize_protection.B', 'SetTrue')
    edge(output, 'initialize_protection.B', 'started')

    node('MakeArray', 'actor_array', [('actor', 'A')], TypeT='wh::rpgmodule::Souls')
    node('MakeArray', 'player_array', [('player', 'A')], TypeT='wh::rpgmodule::Souls')
    together = node('MakeArray', 'participants', [('actor', 'A'), ('player', 'B')], TypeT='wh::rpgmodule::Souls')
    # Native fightnotificationtrigger observes combat history, separately from
    # enabling a behavior. Expose this as evidence of actual engagement.
    node('CombatHistoryTrigger', 'combat_history', [('actor', 'Soul1'),
        ('player', 'Soul2'), ('fighting.State', 'IsActive')], [('MaxTime', '30')])
    edge(output, 'combat_history.OnCombatHistoryBegins', 'engaged')
    for i, _ in enumerate(plan['partners']):
        node('MakeArray', 'partner_array_' + str(i), [('partner_' + str(i), 'A')], TypeT='wh::rpgmodule::Souls')
    protected = all_of(nodes, 'protected', ['not_pending.bool',
        invert('fully_idle', all_of(nodes, 'inactive', ['not_fighting.bool', 'not_stopping.bool']))])
    for i, buff in enumerate(plan['buffs']):
        # Source AddBuff/RemoveBuff lifetimes must stay explicit. Native
        # BuffEffect rejects persistent buffs, including death protection.
        node('Function', 'protection_add_' + str(i), [('actor_array.Array', 'Souls'),
            ('initialize_protection.A', 'Exec')], [('Buff', buff)],
            MethodName='wh::rpgmodule::AddBuff', DeclaringType='wh::rpgmodule')
        node('Function', 'protection_remove_' + str(i), [('actor_array.Array', 'Souls'),
            ('all_stopped_order.A', 'Exec')], [('Buff', buff)],
            MethodName='wh::rpgmodule::RemoveBuff', DeclaringType='wh::rpgmodule')

    def context(n, souls, context_name, enabled):
        node('SetEntityContext', n, [(souls, 'Souls'), (enabled, 'IsActive')], [('Context', context_name)])
    grace = state('reaction_grace')
    edge(grace, 'all_stopped_order.A', 'SetTrue')
    node('Timer', 'grace_timer', [('all_stopped_order.A', 'SetRunning')],
         [('Duration', plan['reaction_grace']), ('TimeType', 'GameTime')])
    edge(grace, 'grace_timer.OnFinished', 'SetFalse')
    from campaign_quest_graph import any_of
    reaction_protection = any_of(nodes, 'arranged_active', [protected, 'reaction_grace.State'])
    context('arranged', 'participants.Array', 'combat_arrangedFight', reaction_protection)
    if plan.get('suppress_assault_reactions'):
        # Native bonzak fistfight protection uses combat_indifference through
        # fightconfiguration_indifference. It prevents the quest's hits from
        # starting a separate crime/self-help response. Keep the source grace
        # interval after stop, and leave ordinary behavior unchanged afterward.
        context('assault_reaction_suppression', 'actor_array.Array', 'combat_indifference',
                reaction_protection)
    participants = [('actor', 'actor_array.Array', 'player', 'fighting.State')]
    party_active = all_of(nodes, 'party_active', ['fighting.State', 'party_ready'])
    for i, _ in enumerate(plan['partners']):
        participants.append(('partner_' + str(i), 'partner_array_' + str(i) + '.Array', 'actor', party_active))
    for actor_name, array, target, enabled in participants:
        node('fighteffect', actor_name + '_fight', [(actor_name, 'attacker'), (target, 'target'),
            ('scheduler', 'qso'), (enabled, 'isactive')],
            [('prioritytarget', 'false'), ('behaviorname', 'fightRepeated_template')])
        context(actor_name + '_unarmed', array, 'combat_forceUnarmed', enabled)
        # The legacy keepRunning combat branch delegates surrender decisions
        # to its own gates. Native morale must not replace them with fleeing.
        context(actor_name + '_keep_fighting', array, 'combat_neverSurrenderOrFlee', enabled)
        context(actor_name + '_join', array, 'combat_alwaysJoinSkirmish', enabled)

    # Arbitration disables all monitors before StopFight. Simultaneous health
    # and surrender notifications cannot select two outcomes.
    outcomes = {}
    for result in ('won', 'lost', 'distance_lost'):
        latch = state('result_' + result)
        node('If', 'take_' + result, [('fighting.State', 'Condition')])
        sequence('finish_' + result, 'take_' + result + '.True')
        edge(active, 'finish_' + result + '.A', 'SetFalse')
        edge(stopping, 'finish_' + result + '.B', 'SetTrue')
        edge(latch, 'finish_' + result + '.C', 'SetTrue')
        edge(latch, 'initialize.A', 'SetFalse')
        outcomes[result] = next(n for n in nodes if n.get('Name') == 'take_' + result)
    node('If', 'cancel_active', [('cancel', 'Exec'), ('fighting.State', 'Condition')])
    sequence('cancel_order', 'cancel_active.True')
    edge(active, 'cancel_order.A', 'SetFalse')
    edge(stopping, 'cancel_order.B', 'SetTrue')
    # Use the shipped helper because StopFight.OnExec acknowledges submission,
    # not completion of the native combat interrupt.
    stop = node('fightstop', 'stop_actor', [('actor_array.Array', 'participants')])
    for result in outcomes: edge(stop, 'finish_' + result + '.D', 'stop')
    edge(stop, 'cancel_order.C', 'stop')
    acknowledged = state('actor_stopped')
    edge(acknowledged, 'stop_actor.onstopped', 'SetTrue')
    edge(acknowledged, 'initialize.A', 'SetFalse')
    acknowledgements = ['actor_stopped.State']
    for result in outcomes:
        done = gate('deliver_' + result, 'all_stopped_order.B', 'result_' + result + '.State')
        edge(output, done, result)
    # Stop supporting fighters too; native StopFight handles a soul array,
    # but its acknowledgement belongs to its first soul, hence separate calls.
    for i, _ in enumerate(plan['partners']):
        n = node('fightstop', 'stop_partner_' + str(i),
                 [('partner_array_' + str(i) + '.Array', 'participants')])
        condition = node('If', 'stop_partner_gate_' + str(i), [('party_ready', 'Condition')])
        for result in outcomes: edge(condition, 'finish_' + result + '.D', 'Exec')
        edge(condition, 'cancel_order.C', 'Exec')
        edge(n, condition.get('Name') + '.True', 'stop')
        acknowledged = state('partner_stopped_' + str(i))
        edge(acknowledged, 'stop_partner_' + str(i) + '.onstopped', 'SetTrue')
        edge(acknowledged, 'initialize.A', 'SetFalse')
        acknowledgements.append(any_of(nodes, 'partner_ack_' + str(i),
            [acknowledged.get('Name') + '.State', 'no_party.bool']))
    all_stopped = all_of(nodes, 'all_stopped', ['stopping.State'] + acknowledgements)
    node('Watch', 'stop_watch', [(all_stopped, 'WatchedState'), ('stopping.State', 'IsActive')], TypeT='bool')
    finished = gate('confirm_stopped', 'stop_watch.OnChanged', all_stopped)
    sequence('all_stopped_order', finished)
    edge(stopping, 'all_stopped_order.A', 'SetFalse')
    edge(output, 'all_stopped_order.B', 'stopped')

    solo = all_of(nodes, 'solo', ['fighting.State', invert('no_party', 'party_ready')])
    # KCD2's own playerhpconventioncheck also samples health on hit reaction;
    # player combat HP notifications are not identical to NPC state changes.
    hit_check = node('IfFunction', 'player_hit_health', [('player_health.Value', 'ValueA'),
        ('player_threshold.State', 'ValueB')], [('Op', 'LessEquals')], TypeT='float',
        MethodName='Control::Compare', DeclaringType='Control')
    for kind in ('armed', 'missile', 'unarmed', 'dog'):
        hit = node('AIConceptSignalTrigger', 'player_hit_' + kind,
            [('player_array.Array', 'victim_value_filter'), (solo, 'IsActive')],
            [('hitType_filter', kind)], NotificationName='hitReactionNotification')
        edge(hit_check, hit.get('Name') + '.OnNotification', 'Exec')
    edge(outcomes['lost'], 'player_hit_health.True', 'Exec')
    for subject, threshold, enabled, result in [('actor', plan['actor_threshold'], 'fighting.State', 'won'),
                                                ('player', None, solo, 'lost')]:
        n = node('SoulStateTrigger', subject + '_low_health', [(subject, 'Soul'), (enabled, 'IsActive')],
                 [('State', 'health'), ('Operator', 'LessEquals')])
        if threshold is None: edge(n, 'player_threshold.State', 'Value')
        else: constant(n, 'Value', threshold)
        edge(outcomes[result], subject + '_low_health.OnMatch', 'Exec')
        node('SoulUnconsciousTrigger', subject + '_unconscious',
             [(subject + '_array.Array', 'Souls'), (enabled, 'IsActive')])
        if subject == 'player':
            awake = node('Function', 'wake_player', [('player_array.Array', 'Souls'),
                (subject + '_unconscious.OnUnconscious', 'Exec')], [('Buff', plan['wake_buff'])],
                MethodName='wh::rpgmodule::AddBuff', DeclaringType='wh::rpgmodule')
            edge(outcomes[result], 'wake_player.OnExec', 'Exec')
        else:
            edge(outcomes[result], subject + '_unconscious.OnUnconscious', 'Exec')
    node('AIConceptSignalTrigger', 'surrender', [('fighting.State', 'IsActive')],
         NotificationName='skirmish_playerSurrendered')
    edge(outcomes['lost'], 'surrender.OnNotification', 'Exec')
    node('DistanceTrigger', 'outside_home', [('actor', 'Origin'), ('home', 'Target'), (solo, 'IsActive')],
         [('Operator', 'Greater'), ('Distance', plan['distance_high'])])
    edge(outcomes['distance_lost'], 'outside_home.OnMatch', 'Exec')
    return xml(root)
