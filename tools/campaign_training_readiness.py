"""Native tutor readiness worker, independent of any source quest or actor.

WaitAction releases the actor's current action before publishing readiness.
The context lives only while the behavior is active; the host must stop this
worker before restoring equipment or resuming the source routine.
"""
import re
import xml.etree.ElementTree as E

from campaign_quest_graph import xml


def emit(stem):
    if not re.fullmatch(r'[A-Za-z_][A-Za-z_0-9]*', stem):
        raise ValueError('Training worker needs a safe generated identifier')
    root = E.Element('BehaviorTrees')
    tree = E.SubElement(root, 'BehaviorTree', name=stem + '_ready', is_function='0')
    E.SubElement(tree, 'Variables')
    body = E.SubElement(tree, 'Root', OneTimeOnly='false', FailState='Recoverable', saveVersion='2')
    sequence = E.SubElement(E.SubElement(body, 'Behavior', canSkip='1'), 'Sequence')
    E.SubElement(sequence, 'WaitAction')
    context = E.SubElement(sequence, 'EntityContext', context='tutorial_npcReadyForCombat', target='')
    E.SubElement(context, 'Wait', duration="'-1'", timeType='GameTime', doFail='false',
                 variation='', skipInLOD='false')
    E.SubElement(tree, 'EditorData', EventSet='')
    return {'AI/' + stem + '_ready.xml': xml(root)}
