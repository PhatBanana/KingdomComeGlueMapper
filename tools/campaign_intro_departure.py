"""Source-selected invitation departure: Move, acknowledge arrival, then lean.

The selected quest/tree comes from the recipe. Place, objective, movement and
request policy come from source XML; native leaning owns stance and occupancy.
"""
import re
import xml.etree.ElementTree as E
from campaign_intro_activity import normalized
from campaign_quest_start_placement import unique
from campaign_quest_graph import xml


def plan(blob, name):
    document = normalized(blob)
    tree = unique(document.findall("BehaviorTree[@name='"+name+"']"), 'departure tree')
    body = unique(tree.findall('Root/Behavior/Sequence'), 'departure sequence')
    if [n.tag for n in body] != ['QuestObjectiveCondition', 'CallBehavior']:
        raise ValueError('Unsupported departure lifetime')
    guard, wait = body
    sequence = unique(guard.findall('Then/Sequence'), 'departure movement')
    if [n.tag for n in sequence] != ['Move', 'SetQuestObjective']:
        raise ValueError('Departure must acknowledge successful movement')
    move, complete = sequence
    objective = guard.get('objective')
    if (guard.get('quest') not in ('', '$__object.name') or guard.get('function') != 'IsObjectiveStarted'
            or complete.get('quest') not in ('', '$__object.name')
            or complete.get('objective') != objective or complete.get('function') != 'CompleteObjective'
            or wait.get('BehaviorName') != 'use' or wait.get('Target') != move.get('destinationSpecification')):
        raise ValueError('Unsupported departure objective or destination')
    binding = unique((n for n in tree.findall('Root/OnInit//LinkDataFilter')
                      if n.get('Child') == wait.get('Target')), 'departure place')
    role = re.fullmatch(r"\$QuestPlace == '(\w+)'", binding.get('condition', ''))
    if binding.get('tag') != 'QuestPlace' or not role:
        raise ValueError('Unresolved departure place')
    request = unique((n for n in document.iter('InstantSendMessageToNPC')
                      if n.get('type') == 'daycycle:change' and "name('"+name+"')" in n.get('values','')),
                     'departure request')
    from campaign_behavior_schedule import source_policy
    priority, speed = source_policy(request.attrib)
    actor = re.fullmatch(r"\$?t_actors\['?(\w+)'?\]", request.get('target', ''))
    if not actor or 'once(true)' not in request.get('values',''):
        raise ValueError('Departure requires a resolved once-only actor request')
    return dict(tree=name, objective=objective, place_role=role[1], move=dict(move.attrib),
                actor_role=actor[1], priority=priority, speed=speed)


def emit(stem, source, catalog):
    from campaign_behavior import BehaviorCompiler
    compiler = BehaviorCompiler([], stem, catalog)
    move = dict(source['move'], destinationSpecification='workPlace')
    record = {'unresolved': []}
    movement = compiler.lower_node(dict(op='Move', attributes=move, children=[]), '', '', '', '', record)
    if record['unresolved']:
        raise ValueError('Departure movement is not convertible: '+str(record['unresolved']))
    root = E.Element('BehaviorTrees')
    tree = E.SubElement(root,'BehaviorTree',name='departure',is_function='0')
    E.SubElement(tree,'Variables')
    params = E.SubElement(tree,'Parameters')
    for name,typ in [('workPlace','_wuid'),('arrivalPending','_bool')]:
        E.SubElement(params,'Variable',name=name,type=typ,values='',form='single',isPersistent='0',requirementType='In')
    r = E.SubElement(tree,'Root',OneTimeOnly='false',FailState='Recoverable',saveVersion='2')
    seq = E.SubElement(E.SubElement(r,'Behavior',canSkip='1'),'Sequence')
    pending = E.SubElement(E.SubElement(seq,'IfCondition',condition='$arrivalPending',failOnCondition='false'),'Sequence')
    pending.append(movement)
    # Success means the source Move completed, not that the indefinite leaning
    # tail finished. The callback advances only the source arrival objective.
    E.SubElement(pending,'Callback_empty',EventName="'Success'")
    context = E.SubElement(seq,'EntityContextElement',context='activity_disableSchedulerLooping',enabled='true')
    E.SubElement(context,'CallBehavior',Target='$workPlace',BehaviorName="'use'",ignoreDropUnloading='false')
    E.SubElement(tree,'EditorData',Signature=stem,EventSet='resultNotification')
    table = E.Element('database',name='barbora')
    sig = E.SubElement(E.SubElement(table,'Signatures',version='1'),'TreeSignature',Name=stem,EnableBehavior='true')
    ps = E.SubElement(sig,'Parameters')
    for name,typ in [('workPlace','_wuid'),('arrivalPending','_bool')]:
        E.SubElement(ps,'VariableInfo',name=name,type=typ,form='Single',values='',isOptional='false',isPersistent='false',requirementType='In')
    return {'AI/'+stem+'.xml':xml(root),'Libs/Tables/ai/Signature__'+stem+'.xml':xml(table)}
