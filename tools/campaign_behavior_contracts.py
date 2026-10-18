"""Source/native AI contracts used by complete work and controller trees.

These are operation schemas, not substitutions for named jobs. The compiler
also checks each field against the installed game's runtime examples.
"""

WORK_CONTRACTS = {
    # Shipped beggar, movement and ladder controllers retain these work APIs.
    # Entity names, participants and helper outputs remain runtime references.
    'GetBehaviorHolders': dict(area='reference', behaviors='string_expression',
                              targetVar='reference'),
    'GetHelperData': dict(smartObjectName='reference', helperID='reference',
        positionTargetVar='reference', orientationTargetVar='reference',
        transformTargetVar='reference', fragmentTargetVar='reference',
        tagsTargetVar='reference'),
    'GetLockParticipants': dict(OutArray='reference', IncludeSelf='value'),
    'TimerBox': dict(startTime='string_expression', endTime='string_expression',
                    variation='string_expression', duration='string_expression'),
    'HasGenderCheck': dict(Gender='human_gender', SoulWUID='reference',
                          FailSubtMissing='value', saveVersion='value'),
    # The native door behaviors retain the source helper-query ABI, including
    # runtime fragment/tag selection and separate position/rotation outputs.
    'GetAnimationHelperData': dict(smartObject='reference', helperID='reference',
        fragment='string_expression', tags='string_expression', positionTargetVar='reference',
        orientationTargetVar='reference', transformTargetVar='reference'),
    # Native crime/watch and inventory searches retain these queries. Their
    # state/parameter literals are checked against the installed runtime.
    'HasPerceivableState': dict(PerceivableState='perceivable_state',
        PerceivedWUID='reference', PerceptorWUID='reference',
        FailSubtMissing='value', saveVersion='value'),
    'ItemParamFilter': dict(Param='item_filter_parameter', owner='reference',
        Source='value', prune='value', negprune='value', Parent='reference', Child='reference'),
    # Shipped animal/basic/switch trees retain these entity query contracts.
    # Output variables are references too; checks retain Then/Else semantics.
    'CheckWuidValid': dict(wuid='reference', FailSubtMissing='value', saveVersion='value'),
    'IsDeadCheck': dict(SoulWUID='reference', FailSubtMissing='value', saveVersion='value'),
    'GetType': dict(WUID='reference', OutString='reference', ShowTrueIdentity='value', TreatPlayerAsNPC='value'),
    'DistanceCondition': dict(Origin='reference', ReferencePt='reference', Low='expression', High='expression',
                              Negation='value', ValueOnMiddle='value', failOnCondition='value'),
    # Retail animal_determineTrespassReaction.xml and so_animalBehaviors.xml:
    # the labelled query returns its matching area through Area, while the
    # plain query consumes an existing area. Preserve both conditional arms.
    'IsInsideAreaWithLabel': {'Position': 'reference', 'Label': 'string_expression',
        'Area': 'reference', 'FailSubtMissing': 'value', 'saveVersion': 'value'},
    'IsInsideArea': {'Origin': 'reference', 'Area': 'reference',
        'FailSubtMissing': 'value', 'saveVersion': 'value'},
    'IsInsideAreaWithLabelBarrier': {'Who': 'reference', 'Label': 'string_expression',
        'Negation': 'value', 'RunLogic': 'value'},
    'EntityClassFilter': dict(Class='entity_class', Source='value', prune='value',
                             negprune='value', Parent='reference', Child='reference'),
    # Native AI/_lukas/test_lukas_helper.xml and
    # AI/npc/basic/switch/interrupt_mourn.xml retain these work-selection ABIs.
    # Weather remains a runtime expression; it is not evaluated at import time.
    'RangeSorter': {'point': 'reference', 'SortOrder': 'value', 'Source': 'value'},
    # Native so_playerHorseDefault and closedCastle/guardWalk use these
    # queries. Preserve runtime range and random selection, not a chosen
    # waypoint baked into the converted job.
    'RangeFilter': {'min': 'expression', 'max': 'expression', 'point': 'reference',
        'excludeRef': 'value', 'Source': 'value', 'prune': 'value', 'negprune': 'value',
        'Parent': 'reference', 'Child': 'reference'},
    'RandomItem': {'Array': 'reference', 'Result': 'reference', 'Clamp': 'expression'},
    'WeatherCondition': {'condition': 'expression', 'failOnCondition': 'value'},
    'LinkDataFilter': {'tag': 'link_type', 'condition': 'expression',
                       'prune': 'value', 'negprune': 'value',
                       'Parent': 'reference', 'Child': 'reference', 'Data': 'reference'},
    'Child0': {'canSkip': 'value'},
    'ForEach': {'startIndex': 'expression', 'step': 'expression',
                'array': 'reference', 'iterator': 'reference',
                'value': 'reference', 'break': 'expression'},
    'LoopUntil': {'until': 'value', 'attemptCount': 'expression'},
    'Nodalyzer': {'Quantifiers': 'value', 'Parent': 'reference',
                  'Child': 'reference', 'id': 'reference', 'saveVersion': 'value'},
    'DistanceGate': {'Origin': 'reference', 'ReferencePt': 'reference',
                     'Low': 'expression', 'High': 'expression', 'Negation': 'value',
                     'OpenInMiddle': 'value', 'RunLogic': 'value'},
    'DialogGate': {'Who': 'reference', 'Negation': 'value',
                   'EndDialogInRoot': 'value', 'WaitForTwins': 'value',
                   'Condition': 'value', 'RunLogic': 'value'},
    'DeadUnconsciousGate': {'Who': 'reference', 'Negation': 'value',
                            'State': 'value', 'RunLogic': 'value'},
    'NPCStateGate': {'Target': 'reference', 'State': 'value',
                     'Low': 'expression', 'High': 'expression',
                     'Negation': 'value', 'RunLogic': 'value'},
    'ReadMessage': {'timeout': 'string_expression', 'timeType': 'value',
                    'variable': 'reference', 'senderInfo': 'reference',
                    'inbox': 'mailbox', 'condition': 'expression'},
    'ClearInbox': {'inbox': 'mailbox', 'type': 'optional_message_type',
                   'condition': 'expression'},
    'InstantReadMessage': {'inbox': 'mailbox', 'condition': 'expression',
                           'variable': 'reference', 'senderInfo': 'reference'},
    'ForceLook': {'LookTarget': 'reference', 'DisableVariations': 'value'},
    'DoDialog': {'DialogId': 'expression'},
    'CategoryFilter': {'categories': 'string_expression', 'Source': 'value', 'prune': 'value',
                        'negprune': 'value', 'Parent': 'reference', 'Child': 'reference', 'id': 'reference'},
    'GetHelper': {'smartObjectName': 'reference', 'helperName': 'string_expression',
                   'categoryName': 'string_expression', 'targetVar': 'reference', 'policy': 'value'},
    'Concatenation': {'OutString': 'reference', 'Pattern': 'literal_pattern'},
    'InstantExternalLock': {'LockManagerType': 'value', 'SemaphoreName': 'string_expression', 'RunLogic': 'value'},
    'RandomGate': {'opensWithChance': 'expression', 'saveVersion': 'value'},
    'InstantMultiSendMessageToNPC': {'targets': 'reference', 'type': 'message_type',
                                    'values': 'expression', 'variable': 'reference',
                                    'failureMode': 'value', 'successMode': 'value'},
    'SetVariable': {'variable': 'reference', 'script': 'empty_script',
                    'values': 'expression'},
    'CallBehavior': {'Target': 'reference', 'BehaviorName': 'string_expression',
                     'ignoreDropUnloading': 'value', 'stopAfterFirstFound': 'value',
                     'nodeLabel': 'value'},
    'ErrorNode': {'Message': 'string_expression'},
    'LogToConsole': {'Message': 'string_expression', 'LogLevel': 'value'},
    'WaitAction': {},
    'IsLoadedGate': {'saveVersion': 'value'},
    'WUIDFilter': {'Child': 'reference', 'Parent': 'reference', 'Source': 'value',
                   'WUID': 'reference', 'negprune': 'value', 'prune': 'value'},
    'HasBehaviorFilter': {'BehaviorList': 'string_expression', 'Child': 'reference',
                          'FilterChoice': 'value', 'Parent': 'reference', 'Source': 'value',
                          'negprune': 'value', 'prune': 'value'},
    'ReserveBehavior': {'behaviorName': 'string_expression', 'reserveFrom': 'reference',
                        'saveVersion': 'value'},
    'ReserveBehaviorSearch': {},
    'Search': {'canSkip': 'value'},
    'Exec': {'canSkip': 'value'},
    'Subtree': {'canSkip': 'value'},
    'TryCatch': {'atomicCatch': 'value'},
    'BehaviorTagCatch': {'Reason': 'behavior_request_event', 'ConsumeInnerEvents': 'value'},
    'NotNearPlayer': {'target': 'reference', 'result': 'reference'},
    'NumericalOperation': {'In1VariableName': 'numeric_operand', 'In2VariableName': 'numeric_operand',
                           'In3VariableName': 'numeric_operand', 'OutVariableName': 'reference',
                           'Operation': 'numeric_operation'},
    'IfGate': {'RunLogic': 'value', 'atomic': 'value', 'condition': 'expression'},
    'ContinuousSwitch': {},
    'HandCheck': {'who': 'reference', 'LeftHand': 'reference', 'RightHand': 'reference'},
    'GetPredefPathTraverseInfo': {'ObjectWuid': 'reference', 'PathWuid': 'reference',
        'Out_ClosestPointOnPath': 'reference', 'Out_DistToEnd': 'reference', 'Out_DistToPath': 'reference'},
    'NegationOp': {'Advance': 'value', 'EndOp': 'value', 'Results': 'value', 'saveVersion': 'value'},
    'AnyLinkFilter': {'Child': 'reference', 'Parent': 'reference', 'Source': 'value',
        'negprune': 'value', 'prune': 'value'},
    'AddLink': {'From': 'reference', 'To': 'reference', 'Tag': 'link_type',
        'Data': 'expression', 'LinkOpHandleMode': 'value'},
    'RemoveLink': {'From': 'reference', 'To': 'reference', 'Tag': 'link_type',
        'RemoveAll': 'value', 'LinkOpHandleMode': 'value'},
}

_SEMAPHORE = dict(atomic='value', OutsideQueuePosVariable='reference',
    InsidePosVariable='reference', TimerType='value', OutsideTimerValue='string_expression',
    LockManagerType='value', SemaphoreName='string_expression', SemaphoreCount='expression')
WORK_CONTRACTS['Semaphore'] = dict(_SEMAPHORE)
# Retail AI/carts/carts.xml and crime routines use this non-waiting lock.
# Preserve its child subtree: contention is a runtime result, not a reason to
# flatten the job or execute it without reserving the shared resource.
WORK_CONTRACTS['InstantSemaphore'] = dict(LockManagerType='value',
    SemaphoreName='string_expression', SemaphoreCount='expression')
WORK_CONTRACTS['GetItemProperty'] = dict(itemId='reference', property='item_property', result='reference')
WORK_CONTRACTS['SetItemProperty'] = dict(itemId='reference', property='item_property',
    sourceVar='reference', isRelative='value')
WORK_CONTRACTS['RemoveItem'] = dict(Item='reference', ItemGUID='string_expression', Source='reference',
    Amount='expression', FailOnDoesntExist='value', NotifyUI='value')
WORK_CONTRACTS['LuaGate'] = dict(code='native_lua', saveVersion='value')
WORK_CONTRACTS['LuaWrapper'] = dict(onEnter='native_lua', onExit='native_lua')
# Native crime/home routines use labels to change access policy, and quest
# controllers enable/disable registered jobs through SetBehaviorState.
WORK_CONTRACTS['AddAreaLabel'] = dict(Area='reference', Label='area_label')
WORK_CONTRACTS['RemoveAreaLabel'] = dict(Area='reference', Label='area_label')
WORK_CONTRACTS['SetBehaviorState'] = dict(behaviors='string_expression', state='behavior_state')
WORK_CONTRACTS['Synchronize'] = dict(_SEMAPHORE, InsideTimerValue='string_expression',
    InvalidateOnExpire='value', RunLogic='value')

# Both native filters use item-class GUIDs, not placed-item WUIDs. Their
# definitions must pass through the same registry as CreateItem and job slots.
for _filter in ('SlotClassFilter', 'ItemClassFilter'):
    WORK_CONTRACTS[_filter] = dict(ClassId='item_class', Category='empty_category',
        Child='reference', Parent='reference', Source='value', negprune='value', prune='value')
