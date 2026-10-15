"""Native AI work phases for source-owned combat lifecycles.

Uses native hand/stance controllers so tools and sitting retain their item
reservations and animations. No direct animation playback or item duplication.
"""
import xml.etree.ElementTree as E
from campaign_quest_graph import xml


PARAMETERS = {'toolSlot': '_wuid', 'homeArea': '_wuid', 'workPlace': '_wuid',
              'cleanupTool': '_bool', 'removePrivacy': '_bool'}


def emit(stem, aftermath):
    signature = stem + '_work'
    root = E.Element('BehaviorTrees')
    def tree(name, variables):
        t = E.SubElement(root, 'BehaviorTree', name=name, is_function='0')
        vs = E.SubElement(t, 'Variables')
        for n, typ in variables.items():
            E.SubElement(vs, 'Variable', name=n, type=typ, values='', isPersistent='0', form='single')
        ps = E.SubElement(t, 'Parameters')
        for n, typ in PARAMETERS.items():
            E.SubElement(ps, 'Variable', name=n, type=typ, values='', isPersistent='0', form='single', requirementType='In')
        r = E.SubElement(t, 'Root', OneTimeOnly='false', FailState='Recoverable', saveVersion='2')
        completion = E.SubElement(E.SubElement(r, 'Behavior', canSkip='1'), 'FuseBox',
            StatusPropagation='Child', OneCleanup='false', saveVersion='2')
        seq = E.SubElement(E.SubElement(completion, 'Child', canSkip='1'), 'Sequence')
        for branch, event in [('OnSuccess', 'Success'), ('OnFail', 'Fail')]:
            E.SubElement(E.SubElement(completion, branch, canSkip='1'), 'Callback_empty', EventName=repr(event))
        E.SubElement(t, 'EditorData', Signature=signature, EventSet='resultNotification')
        return seq
    def condition(parent, expression):
        return E.SubElement(E.SubElement(parent, 'IfCondition', failOnCondition='false', condition=expression), 'Sequence')
    prepare = tree('prepare', {'item': '_wuid', 'occupied': '_wuid'})
    attempt = E.SubElement(E.SubElement(prepare, 'SuppressFailure'), 'Sequence')
    tool = condition(attempt, '$cleanupTool & ($toolSlot ~= $__null)')
    E.SubElement(tool, 'GetItemInSlot', slot='$toolSlot', useHomeItem='false', item='$occupied')
    empty = condition(tool, '$occupied == $__null')
    E.SubElement(empty, 'GetItemInSlot', slot='$toolSlot', useHomeItem='true', item='$item')
    available = condition(empty, '$item ~= $__null')
    # The native action controller owns pickup/placement. A source instant
    # manipulation is upgraded to an acknowledged native action; fighting
    # cannot start while that action still owns the actor's hand.
    hand = E.SubElement(available, 'HandContentElement', hand='Right', item='$item',
        allowAny='false', allowHomeSlotAutoReturn='true', decisionLabel=stem + '_cleanup',
        useDecision='false', enabled='true', saveVersion='2')
    E.SubElement(E.SubElement(hand, 'Exec', canSkip='1'), 'PlaceAction', item='$item', slot='$toolSlot')
    privacy = tree('privacy', {})
    remove = condition(privacy, '$removePrivacy')
    E.SubElement(remove, 'RemoveAreaLabel', Area='$homeArea', Label=repr(aftermath['privacy']['label']))
    routine = tree('routine', {})
    parallel = E.SubElement(routine, 'Parallel', successMode='Any', failureMode='Any')
    cycle = E.SubElement(E.SubElement(parallel, 'Loop', count='-1'), 'Sequence')
    bark = aftermath['bark']
    E.SubElement(cycle, 'Wait', duration=repr(bark['delay']), timeType='GameTime', doFail='false', variation='')
    gate = E.SubElement(cycle, 'DistanceGate', Origin='', ReferencePt='$__player',
        Low=str(bark['low']), High=str(bark['high']), Negation='false', OpenInMiddle='false', RunLogic='KeepRunning')
    E.SubElement(gate, 'InstantSendMessageToNPC', target='$this.id', type="'dialog:monologRequest'",
        values="alias('" + bark['alias'] + "'),lookAtId($__player)")
    awake = E.SubElement(parallel, 'EntityContextElement', context='bench_disableSnooze', enabled='true')
    E.SubElement(awake, 'CallBehavior', Target='$workPlace', BehaviorName=repr(aftermath['work']['behavior']),
        ignoreDropUnloading='false')
    signatures = E.Element('database', name='barbora')
    sig = E.SubElement(E.SubElement(signatures, 'Signatures', version='1'), 'TreeSignature', Name=signature, EnableBehavior='true')
    ps = E.SubElement(sig, 'Parameters')
    for n, typ in PARAMETERS.items():
        E.SubElement(ps, 'VariableInfo', name=n, type=typ, form='Single', values='',
                     isOptional='false', isPersistent='false', requirementType='In')
    return {'AI/' + stem + '_work.xml': xml(root),
            'Libs/Tables/ai/Signature__' + stem + '.xml': xml(signatures)}


def validate(files, native_game):
    """Check executable operation schemas against shipped native AI Roots."""
    import zipfile
    from upgrade_map import read
    catalog = {}
    with zipfile.ZipFile(native_game / 'Data/Tables.pak') as archive:
        event_sets = E.fromstring(read(archive, 'Libs/Tables/ai/EventSet.xml'))
        contract = next((n for n in event_sets.iter('TreeEventSet') if n.get('Name') == 'resultNotification'), None)
        if contract is None or {n.get('Name'): n.get('Signature') for n in contract.findall('Events/*')} != {'Success': 'empty', 'Fail': 'empty'}:
            raise ValueError('Native resultNotification callback contract changed')
    with zipfile.ZipFile(native_game / 'Data/Scripts.pak') as archive:
        for path in archive.namelist():
            if not path.startswith('AI/') or not path.endswith('.xml'): continue
            try: document = E.fromstring(read(archive, path))
            except E.ParseError: continue
            for root in document.findall('./BehaviorTree/Root'):
                for n in root.iter(): catalog.setdefault(n.tag, set()).update(n.attrib)
    signals = {n.get('Name') for path, data in files.items() if '/AIConceptSignalDatabase__' in path
               for n in E.fromstring(data).iter('AIConceptSignal')}
    for path, data in files.items():
        if not path.startswith('AI/'): continue
        for root in E.fromstring(data).findall('./BehaviorTree/Root'):
            for n in root.iter():
                if n.tag.startswith('SendAIConceptSignal_') and n.tag.removeprefix('SendAIConceptSignal_') in signals:
                    continue
                if n.tag not in catalog or set(n.attrib) - catalog[n.tag]:
                    raise ValueError('Unverified native work operation: ' + n.tag + ' ' + str(n.attrib))
