"""One scheduled tutor invocation owns preparation, readiness and cleanup.

Stop requests are latched by the host and do not kill item creation midway.
The worker acknowledges quiescence before cleanup; borrowed instance variables
remain in this same scope until cleanup acknowledges success.
"""
import copy
import xml.etree.ElementTree as E

from campaign_quest_graph import xml, identifier
from campaign_training_controller import register_events
from campaign_training_plan import subject
from campaign_combat_plan import attrs


def basic_equipment_policy(phase, root, plan):
    """Adapt legacy weapon operations for a selected native Basic curriculum.

    Basic begins with its own draw-weapon instruction. Preserve equipped loans
    but leave drawing to that instruction. Native cleanup unequips the exact
    tutor loan before removing it; never clear an arbitrary inventory slot.
    """
    def visit(parent):
        for i, child in enumerate(list(parent['children'])):
            a = attrs(child)
            if phase == 'prepare' and child['op'] == 'InstantSendMessageToNPC':
                if (a.get('type') != 'player:drawWeapon' or a.get('target') not in ('__player','$__player')
                        or a.get('values') != 'set($enum:weaponSet.primary)'):
                    raise ValueError('Unsupported native Basic equipment message')
                parent['children'][i] = dict(op='Success', attributes={}, children=[])
            elif phase == 'cleanup' and child['op'] == 'InstantHolsterWeapon':
                owners = [v for v in plan['leases'] if v['owner'] == subject(a.get('who',''))]
                if len(owners) != 1:
                    raise ValueError('Holster requires one owned training loan')
                parent['children'][i] = dict(op='UnEquipItem', attributes={
                    'item':owners[0]['handle'], 'Target':a.get('who','')}, children=[])
            else:
                visit(child)
    visit(root)
    return root


def emit(stem, roots, variables, native_event_sets):
    identifier(stem)
    if set(roots) != {'prepare','cleanup'}:
        raise ValueError('Training worker requires both equipment programs')
    document = E.Element('BehaviorTrees')
    tree = E.SubElement(document,'BehaviorTree',name='lesson',is_function='0')
    declarations = E.SubElement(tree,'Variables')
    for v in variables:declarations.append(copy.deepcopy(v))
    parameters = E.SubElement(tree,'Parameters')
    for name in ('stopRequested','cleanupRequested'):
        E.SubElement(parameters,'Variable',name=name,type='_bool',values='',form='single',
                     isPersistent='0',requirementType='In')
    root = E.SubElement(tree,'Root',OneTimeOnly='false',FailState='Recoverable',saveVersion='2')
    sequence = E.SubElement(E.SubElement(root,'Behavior',canSkip='1'),'Sequence')

    def program(phase, success, failure):
        source = E.fromstring(roots[phase])
        fuse = source.find('Behavior/FuseBox')
        if fuse is None:raise ValueError('Equipment program lacks acknowledgement')
        body = fuse.find('Child')
        combined = E.Element('Sequence')
        optional_handles = set()
        for init in source.findall('OnInit'):
            for operation in init:
                if phase == 'cleanup' and operation.tag == 'GraphSearch':
                    results = operation.findall('Nodalyzer')
                    if len(results)!=1 or not results[0].get('Child','').startswith('$'):
                        raise ValueError('Unresolved original equipment search')
                    optional_handles.add(results[0].get('Child'))
                    E.SubElement(combined,'SuppressFailure').append(copy.deepcopy(operation))
                else:combined.append(copy.deepcopy(operation))
        for operation in list(body):combined.append(operation);body.remove(operation)
        body.append(combined)
        if phase == 'prepare':
            # Release the prior pose before acknowledging preparation. A failed
            # action release follows the same acknowledged cleanup path.
            E.SubElement(combined,'WaitAction')
        if phase == 'cleanup':
            # Preparation can fail after creating only one loan. Missing
            # handles are skipped; failures removing existing items still fail.
            for parent in list(combined.iter()):
                for i,operation in enumerate(list(parent)):
                    handle=operation.get('Item') if operation.tag=='RemoveItem' else operation.get('item')
                    if operation.tag in ('RemoveItem','UnEquipItem') or operation.tag=='EquipItem' and handle in optional_handles:
                        if not handle or not handle.startswith('$'):raise ValueError('Cleanup needs exact item handle')
                        gate=E.Element('VariableExistsGate',VarToTest=handle,VarIndexMode='All',FailSubtMissing='false',saveVersion='2')
                        E.SubElement(gate,'Then',canSkip='1').append(operation)
                        parent.remove(operation);parent.insert(i,gate)
        for outcome,event in (('Success',success),('Fail',failure)):
            callback=fuse.find('On'+outcome+'/Callback_empty')
            if callback is None:raise ValueError('Missing equipment callback')
            callback.set('EventName',repr(event))
        return fuse

    # Failure still joins the same stop/cleanup handshake. SuppressFailure
    # changes control flow only after the equipment failure callback fires.
    E.SubElement(sequence,'SuppressFailure').append(program('prepare','Prepared','PreparationFailed'))
    wait = E.SubElement(sequence,'SuppressFailure')
    gate = E.SubElement(wait,'IfGate',atomic='false',condition='~$stopRequested',RunLogic='Halt')
    ready = E.SubElement(gate,'Sequence')
    context = E.SubElement(ready,'EntityContext',context='tutorial_npcReadyForCombat',target='')
    ready_body=E.SubElement(context,'Sequence')
    E.SubElement(ready_body,'Callback_empty',EventName="'Ready'")
    E.SubElement(ready_body,'Wait',duration="'-1'",timeType='GameTime',doFail='false',variation='',skipInLOD='false')
    E.SubElement(sequence,'Callback_empty',EventName="'WorkersStopped'")
    # A native IfGate/Halt is used above to RELEASE readiness before signaling
    # stopped. The host's latched cleanupRequested opens this separate wait.
    waiting = E.SubElement(sequence,'SuppressFailure')
    cleanup_gate=E.SubElement(waiting,'IfGate',atomic='false',condition='~$cleanupRequested',RunLogic='Halt')
    E.SubElement(cleanup_gate,'Wait',duration="'-1'",timeType='GameTime',doFail='false',variation='',skipInLOD='false')
    E.SubElement(sequence,'SuppressFailure').append(program('cleanup','Cleaned','CleanupFailed'))
    # Successful cleanup disables the worker. A cleanup fault remains parked
    # instead of returning to the scheduler and creating a second set of loans.
    E.SubElement(sequence,'Wait',duration="'-1'",timeType='GameTime',doFail='false',variation='',skipInLOD='false')
    E.SubElement(tree,'EditorData',Signature=stem,EventSet='')
    events={n:'empty' for n in ('Prepared','PreparationFailed','Ready','WorkersStopped','Cleaned','CleanupFailed')}
    blob,event_table=register_events(xml(document),'lesson',stem+'_events',events,native_event_sets)
    table=E.Element('database',name='barbora')
    signature=E.SubElement(E.SubElement(table,'Signatures',version='1'),'TreeSignature',Name=stem,EnableBehavior='true')
    ps=E.SubElement(signature,'Parameters')
    for name in ('stopRequested','cleanupRequested'):
        E.SubElement(ps,'VariableInfo',name=name,type='_bool',form='Single',values='',isOptional='false',
                     isPersistent='false',requirementType='In')
    return {'AI/'+stem+'.xml':blob,'Libs/Tables/ai/Signature__'+stem+'.xml':xml(table),
            'Libs/Tables/ai/EventSet__'+stem+'.xml':event_table}
