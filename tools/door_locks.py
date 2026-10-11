"""Translate authored KCD1 lock settings without borrowing KCD2 ownership."""
import copy
import re
import xml.etree.ElementTree as ET


def difficulty_rules(script):
    body = script.split('function AnimDoor:GenerateLockDifficulty()', 1)[1]
    body = body.split('for nameSnippet, difficulty', 1)[0]
    result = {name: float(value)/20 for name,value in re.findall(r'\["([^"]+)"\]\s*=\s*(\d+)', body)}
    if not result: raise ValueError('Source door difficulty rules were not found')
    return result


def true(value):
    return str(value).lower() in ('1','true')


def convert_properties(source, model, contract, rules):
    props = copy.deepcopy(source)
    old_lock = source.find('Lock')
    if old_lock is None: raise ValueError('Door has no lock policy')
    lock = props.find('Lock')
    overridden = true(old_lock.get('bLockDifficultyOverride','0'))
    if overridden: difficulty = float(old_lock.get('fLockDifficulty','0.5'))
    else:
        matches = [v for k,v in rules.items() if k in source.get('object_Model','').lower()]
        if len(matches)>1: raise ValueError('Ambiguous source lock difficulty')
        difficulty = matches[0] if matches else 0.0 # Shipped KCD1 fallback.
    if not 0 <= difficulty <= 1: raise ValueError('Invalid source lock difficulty')
    props.set('object_Model',model)
    props.set('soclass_SmartObjectHelpers',contract['helper'])
    props.set('esDoorAnimSet',contract['animation_set'])
    props.set('guidSmartObjectType',contract['smart_object'])
    props.set('esNavCompoment','Door')
    props.set('bSaved_by_game','1')
    props.set('bInteractiveCollisionClass','1')
    # Explicit user policy: unknown owner, no inferred Trosky home/crime links.
    props.set('bNoCrimeDoorLink','1')
    for key in ('esInteriorType','soclasses_SmartObjectHelpers','soclasses_SmartObjectClass'):
        props.attrib.pop(key,None)
    for old,new in [('fKeepOpenFrom','fKeepUnlockedFrom'),('fKeepOpenUntil','fKeepUnlockedTo')]:
        if old in props.attrib:lock.set(new,props.attrib.pop(old))
    lock.set('fLockDifficulty',format(difficulty,'.9g'))
    lock.set('bLockDifficultyOverride','1')
    lock.set('bLockFancinessOverride','1')
    lock.set('esLockFanciness','Common')
    lock.set('bCanUnlockWithDynamicKey','0')
    lock.set('bDoLockOnMissingHomeArea','0')
    lock.set('bNeverLockByPassingNPC','1')
    never = true(lock.get('bNeverLock','0'))
    lock.attrib.pop('bNeverLock',None)
    lock.attrib.pop('bLockpickIsLegal',None)
    if never:
        lock.set('bLocked','0');lock.set('bLockInside','0');lock.set('bLockOutside','0')
        lock.set('esLockTypes','none/none')
    physics=props.find('Physics')
    if physics is None:physics=ET.SubElement(props,'Physics')
    physics.set('bPhysicalize','1')
    return props,dict(difficulty=difficulty,difficulty_source='override' if overridden else 'KCD1 model rules',
                      never_lock=never,key=lock.get('guidItemClassId',''),locked=true(lock.get('bLocked','0')),
                      pickable=true(lock.get('bCanLockPick','1')),lock_types=lock.get('esLockTypes'),owner='unknown',
                      initial_pose='authored model closed pose; runtime save/quest state is not imported')
