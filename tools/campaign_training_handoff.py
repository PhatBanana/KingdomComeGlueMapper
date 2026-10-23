"""Resolve a selected training request from source event and actor bindings."""
import re
from campaign_intro_activity import normalized
from campaign_intro_departure import plan as departure
from campaign_quest_start_placement import unique
from campaign_behavior_schedule import source_policy


def resolve(blob, arrival_tree, request_tree):
    source=normalized(blob)
    arrival=departure(blob,arrival_tree)
    parents={c:p for p in source.iter() for c in p}
    request=unique((n for n in source.iter('InstantSendMessageToNPC')
        if n.get('type')=='daycycle:change' and "name('"+request_tree+"')" in n.get('values','')),
        'training request')
    actor=re.fullmatch(r"\$?t_actors\['?(\w+)'?\]",request.get('target',''))
    if not actor or actor[1]!=arrival['actor_role'] or 'once(true)' not in request.get('values',''):
        raise ValueError('Training request must belong to the arriving actor')
    ancestors=[];p=request
    while p in parents:p=parents[p];ancestors.append(p)
    branch=unique((n for n in ancestors if n.tag=='IfCondition'),'training authorization branch')
    message=unique((n for n in ancestors if n.tag=='ProcessMessage'),'training authorization message')
    variable=message.get('variable')
    pattern=r"\$"+re.escape(variable)+r"\.State == \$enum:ObjectiveState.Started & \$"+re.escape(variable)+r"\.ObjectiveName == '([A-Za-z_]\w*)'"
    authorization=re.fullmatch(pattern,branch.get('condition',''))
    if not authorization:raise ValueError('Unsupported training authorization condition')
    # The source publishes its completion objective on the duel result event.
    completions=[]
    for tree in source.findall('BehaviorTree'):
        variables={v.get('name'):v.get('type') for v in tree.findall('Variables/Variable')}
        for event in tree.findall('Root//ProcessMessage'):
            if variables.get(event.get('variable'))!='duel:duelResult':continue
            for guard in event.findall('QuestObjectiveCondition'):
                actions=guard.findall('Else/SetQuestObjective')
                if (guard.get('function')=='IsObjectiveCompleted' and len(actions)==1
                        and actions[0].get('function')=='CompleteObjective'
                        and actions[0].get('objective')==guard.get('objective')
                        and guard.get('quest')==actions[0].get('quest')==''):
                    completions.append(guard.get('objective'))
                else:raise ValueError('Unsupported training completion branch')
    completion=unique(completions,'training completion objective')
    priority,speed=source_policy(request.attrib)
    return dict(actor_role=actor[1],priority=priority,speed=speed,
        objectives=dict(arrival=arrival['objective'],authorization=authorization[1],completion=completion),
        arrival=arrival,request_tree=request_tree)
