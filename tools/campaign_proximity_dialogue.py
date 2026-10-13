"""Convert bounded source proximity-monologue observers to native quest nodes.

The source parallel work branch is owned by the schedule importer. This adapter
accepts only a complete, side-effect-free greeting observer: initial delay,
entry distance, repeating distance/request/delay lanes, exit distance, forever
wait. Unknown topology is an error, never a flattened list of speech calls.
"""
import math
import re
import xml.etree.ElementTree as E
from campaign_quest_graph import constant, edge, identifier, xml
from quest_import import literal


def attrs(node):
    return {k: literal(v) for k,v in node.attrib.items()}


def parse(tree, objective):
    variables = {v.get('name'): v.get('values') for v in tree.findall('./Variables/Variable')}
    gates = [g for g in tree.findall('./Root//QuestObjectiveGate')
             if attrs(g).get('objectiveName') == objective]
    if len(gates) != 1: raise ValueError('Missing or ambiguous source proximity objective')
    gate = gates[0]
    a = attrs(gate)
    if a.get('objectiveState') != 'Started' or a.get('NegateTo') != 'false' or a.get('RunLogic') != 'KeepRunning':
        raise ValueError('Unsupported proximity objective lifecycle')
    def children(node, tags):
        if node is None or [e.tag for e in node] != tags:
            raise ValueError('Unsupported proximity control flow: ' + str(tags))
        return list(node)
    def wait(node, forever=False):
        a = attrs(node)
        if a.get('timeType') not in ('GameTime','WorldTime') or a.get('doFail') != 'false' or a.get('variation') or a.get('skipInLOD','false') != 'false' or len(node):
            raise ValueError('Unsupported proximity wait')
        duration = a['duration']
        if forever:
            if duration != '-1': raise ValueError('Proximity observer must end in an infinite wait')
        elif not re.fullmatch(r'\d+(?:\.\d+)?[smh]', duration):
            raise ValueError('Unsupported proximity duration')
        return dict(duration=duration, time_type=a['timeType'])
    def distance(node):
        a = attrs(node)
        if a.get('Origin') not in ('', 'this.id', '$this.id') or a.get('ReferencePt') not in ('__player','$__player') or a.get('OpenInMiddle') != 'false' or a.get('RunLogic') != 'KeepRunning':
            raise ValueError('Unsupported proximity distance reference/lifecycle')
        if a['Low'] != a['High'] or a['Negation'] not in ('true','false'):
            raise ValueError('Proximity hysteresis requires a separate adapter')
        value = a['Low']
        if value.startswith('$'): value = variables.get(value[1:])
        radius = float(value)
        if not math.isfinite(radius) or radius <= 0: raise ValueError('Invalid proximity radius')
        return dict(radius=radius, operator='GreaterEquals' if a['Negation']=='true' else 'LessEquals')
    sequence, = children(gate, ['Sequence'])
    initial, parallel, terminal = children(sequence, ['Wait','Parallel','Wait'])
    if attrs(parallel) != dict(successMode='Any',failureMode='Any'): raise ValueError('Unsupported observer completion')
    entry, exit_gate = children(parallel, ['DistanceGate','DistanceGate'])
    lanes, = children(entry, ['Parallel'])
    if attrs(lanes) != dict(successMode='All',failureMode='Any'): raise ValueError('Unsupported lane completion')
    children(exit_gate, ['Success']); wait(terminal, True)
    result = dict(objective=objective, initial=wait(initial), entry=distance(entry), exit=distance(exit_gate), lanes=[])
    for loop in lanes:
        if loop.tag != 'Loop' or attrs(loop) != {'count':'-1'}: raise ValueError('Unsupported proximity repetition')
        seq, = children(loop, ['Sequence'])
        d, delay = children(seq, ['DistanceGate','Wait'])
        message, = children(d, ['SendMessageToNPC'])
        m = attrs(message)
        if m != dict(target='this.id', type='dialog:monologRequest', values=m.get('values'), timeType='GameTime',timeoutType='OnProcessed',timeout='-1',answer=''):
            raise ValueError('Unsupported proximity message contract')
        match = re.fullmatch(r'alias\(([A-Za-z_]\w*)\),lookAtId\(\$__player\)', m['values'])
        if not match: raise ValueError('Unsupported proximity speech arguments')
        result['lanes'].append(dict(distance=distance(d), delay=wait(delay), alias=match[1]))
    if not result['lanes']: raise ValueError('Empty proximity observer')
    return result


def install(blob, plan, actor_guid, player_guid, prefix='gm_proximity'):
    import uuid
    uuid.UUID(actor_guid); uuid.UUID(player_guid); identifier(prefix)
    root = E.fromstring(blob); host = root.find('./Skald/Quest')
    if host is None: raise ValueError('Proximity observer requires its owning quest')
    nodes = host.find('Nodes'); out = nodes.find("Output[@Name='Output']")
    matches = [e.get('From') for e in out.findall('Edge') if e.get('To') == plan['objective']+'_Started']
    if len(matches)!=1: raise ValueError('Missing proximity objective state')
    state = matches[0].removesuffix('.Started')
    if any(n.get('Name','').startswith(prefix+'_') for n in nodes): raise ValueError('Proximity observer already installed')
    assets = host.find('Assets')
    if assets is None: assets = E.SubElement(host,'Assets')
    for suffix,guid in [('speaker',actor_guid),('player',player_guid)]:
        E.SubElement(assets,'SoulAsset',Name=prefix+'_'+suffix,SharedSoulGuids=guid)
    def node(tag,name,**kw):return E.SubElement(nodes,tag,Name=prefix+'_'+name,**kw)
    def ref(name,port):return prefix+'_'+name+'.'+port
    def boolean(name, value=False):
        n=node('State',name,TypeT='bool');constant(n,'DefaultValue',str(value).lower());return n
    def both(name,a,b):
        n=node('Function',name,MethodName='math::boolean::And',DeclaringType='math::boolean')
        edge(n,a,'A');edge(n,b,'B');return ref(name,'bool')
    def inverse(name,value):
        n=node('Function',name,MethodName='math::boolean::Not',DeclaringType='math::boolean')
        edge(n,value,'Value');return ref(name,'bool')
    def timer(name, specification):
        n=node('Timer',name);constant(n,'Duration',specification['duration']);constant(n,'TimeType',specification['time_type']);return n
    def distance(name, specification, active):
        n=node('DistanceTrigger',name)
        E.SubElement(n,'Asset',Name='Origin',Alias=prefix+'_speaker')
        E.SubElement(n,'Asset',Name='Target',Alias=prefix+'_player')
        constant(n,'Operator',specification['operator']);constant(n,'Distance',specification['radius']);edge(n,active,'IsActive')
        return ref(name,'OnMatch')
    initial=timer('initial',plan['initial']);edge(initial,state+'.OnStarted','SetRunning')
    ended=boolean('ended'); entered=boolean('entered')
    alive=both('alive',state+'.Started',inverse('not_ended',ref('ended','State')))
    armed=both('armed',alive,ref('initial','Finished'))
    enter=distance('enter',plan['entry'],armed);edge(entered,enter,'SetTrue')
    leave=distance('exit',plan['exit'],armed);edge(ended,leave,'SetTrue')
    active=both('active',armed,ref('entered','State'))
    for i,lane in enumerate(plan['lanes']):
        name='lane_'+str(i);ready=boolean(name+'_ready',True)
        allowed=both(name+'_allowed',active,ref(name+'_ready','State'))
        request=distance(name+'_distance',lane['distance'],allowed)
        call=node('Function',name+'_request',MethodName='wh::xgenaimodule::RequestMonologue',DeclaringType='wh::xgenaimodule')
        E.SubElement(call,'Asset',Name='Souls',Alias=prefix+'_speaker')
        E.SubElement(call,'Asset',Name='LookAtTarget',Alias=prefix+'_player')
        constant(call,'DecisionAlias',lane['alias']);edge(call,request,'Exec')
        edge(ready,request,'SetFalse')
        retry=timer(name+'_retry',lane['delay']);edge(retry,request,'SetRunning')
        edge(ready,ref(name+'_retry','OnFinished'),'SetTrue')
        for event in (state+'.OnCompleted',state+'.OnFailed',state+'.OnCanceled',state+'.OnUnchanged',leave):edge(retry,event,'SetStopped')
        trace=node('Trace',name+'_trace',TypeT='string');constant(trace,'Value',lane['alias']);edge(trace,request,'Exec')
    for event in (state+'.OnCompleted',state+'.OnFailed',state+'.OnCanceled',state+'.OnUnchanged'):
        edge(initial,event,'SetStopped')
    # Re-entering the objective begins a fresh observer; sequence history stays
    # in native dialogue save state and still prevents replay of one-shot lines.
    edge(ended,state+'.OnStarted','SetFalse');edge(entered,state+'.OnStarted','SetFalse')
    for observed in (ended,entered):
        name=observed.get('Name')
        trace=E.SubElement(nodes,'Trace',Name=name+'_trace',TypeT='bool')
        edge(trace,name+'.State','Value');edge(trace,name+'.OnExec','Exec')
    return xml(root)
