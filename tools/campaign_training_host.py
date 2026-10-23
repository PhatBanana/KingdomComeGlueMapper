"""Connect a source-selected lesson to one native equipment worker.

All identities and objective bindings are caller inputs. The host never moves
an actor, advances time, awards quest progress on a timer, or acknowledges work
which an active worker has not finished.
"""
import xml.etree.ElementTree as E

from campaign_quest_graph import edge, constant, any_of, all_of, identifier


def guard_authorization(nodes, stem, quest, objectives, dialogue_nodes):
    """Offer lesson authorization only after its resolved arrival handoff.

    A dialogue may contain unconditional continuation alternatives. Quest
    activation alone must not make those alternatives bypass the arrival
    worker. Keep each conversation's existing activation predicate as well.
    """
    from setup_quest_invitation import graph_digest
    stem = identifier(stem) + '_authorization'
    quest = identifier(quest)
    expected = E.Element('Nodes')
    done = E.SubElement(expected, 'Function', Name=stem+'_unfinished',
        MethodName='math::boolean::Not', DeclaringType='math::boolean')
    edge(done, quest+'.'+identifier(objectives['completion'])+'_Completed', 'Value')
    ready = all_of(expected, stem+'_ready', [quest+'.started',
        quest+'.'+identifier(objectives['arrival'])+'_Completed', done.get('Name')+'.bool'])
    additions = []
    for n in expected:
        matches = [old for old in nodes if old.get('Name') == n.get('Name')]
        if matches:
            if len(matches) != 1 or graph_digest(matches[0]) != graph_digest(n):
                raise ValueError('Conflicting lesson authorization gate')
        else:
            additions.append(n)
    rewires = []
    if not dialogue_nodes: raise ValueError('Missing lesson authorization conversations')
    for dialog in dialogue_nodes:
        links = dialog.findall("Edge[@To='active']")
        if len(links) != 1 or dialog.find("Constant[@Name='active']") is not None:
            raise ValueError('Ambiguous lesson conversation activation')
        link = links[0]; name = stem+'_'+identifier(dialog.get('Name'))
        found = [n for n in nodes if n.get('Name') == name]
        if found:
            if (len(found) != 1 or found[0].tag != 'Function'
                    or found[0].get('MethodName') != 'math::boolean::And'
                    or found[0].find("Edge[@To='B'][@From='"+ready+"']") is None
                    or link.get('From') != name+'.bool'):
                raise ValueError('Conflicting lesson conversation gate')
        else:
            gate = E.Element('Function', Name=name,
                MethodName='math::boolean::And', DeclaringType='math::boolean')
            edge(gate, link.get('From'), 'A'); edge(gate, ready, 'B')
            additions.append(gate); rewires.append((link,name+'.bool'))
    nodes.extend(additions)
    for link, value in rewires: link.set('From',value)
    return bool(additions or rewires)


def bind(nodes, lesson, worker, *, dialogue_nodes):
    stem=identifier(lesson.get('Name'))+'_host'
    if worker.tag!='EnableBehavior' or worker.get('EventSet')!=worker.get('Signature')+'_events':
        raise ValueError('Training host needs its acknowledged equipment worker')
    if any(n.get('Name','').startswith(stem+'_') for n in nodes):
        raise ValueError('Training host already bound')
    life=lesson.get('Name'); work=worker.get('Name')
    def state(suffix):
        n=E.SubElement(nodes,'State',Name=stem+'_'+suffix,TypeT='bool')
        constant(n,'DefaultValue','false');return n
    active,stop,cleanup=state('active'),state('stop_requested'),state('cleanup_requested')
    prepare=E.SubElement(nodes,'TriggerSequence',Name=stem+'_prepare')
    edge(prepare,life+'.prepare','Exec')
    for flag in (stop,cleanup):edge(flag,prepare.get('Name')+'.A','SetFalse')
    edge(active,prepare.get('Name')+'.B','SetTrue')
    edge(active,work+'.Cleaned','SetFalse')
    edge(worker,active.get('Name')+'.State','IsActive')
    edge(worker,stop.get('Name')+'.State','stopRequested')
    edge(worker,cleanup.get('Name')+'.State','cleanupRequested')
    for outcome,port in [('Prepared','prepared'),('PreparationFailed','preparation_failed'),
                         ('WorkersStopped','workers_stopped'),('Cleaned','cleanup_done'),
                         ('CleanupFailed','cleanup_failed')]:
        edge(lesson,work+'.'+outcome,port)
    for event,flag,ack in [('stop_workers',stop,'workers_stopped'),('cleanup',cleanup,'cleanup_done')]:
        gate=E.SubElement(nodes,'If',Name=stem+'_'+event)
        edge(gate,life+'.'+event,'Exec');edge(gate,active.get('Name')+'.State','Condition')
        edge(flag,gate.get('Name')+'.True','SetTrue')
        # There is no worker or equipment before preparation. Only this branch
        # can acknowledge cancellation without a worker callback.
        edge(lesson,gate.get('Name')+'.False',ack)
    ready=state('ready')
    # The callback occurs inside the readiness context, after WaitAction.
    # Possessing a weapon or starting the worker is not a readiness signal.
    edge(ready,work+'.Ready','SetTrue')
    edge(ready,work+'.WorkersStopped','SetFalse')
    edge(lesson,ready.get('Name')+'.State','tutor_ready')
    edge(lesson,ready.get('Name')+'.OnExec','readiness_changed')
    occupancy=[]
    for dialog in dialogue_nodes:
        name=identifier(dialog.get('Name'));busy=state('talking_'+name)
        edge(busy,name+'.BeforePlay','SetTrue')
        release=E.SubElement(nodes,'SceneFinishedWaiter',Name=stem+'_release_'+name)
        edge(release,name+'.AfterPlay','Enqueue')
        order=E.SubElement(nodes,'TriggerSequence',Name=stem+'_released_'+name)
        edge(order,release.get('Name')+'.OnFinished','Exec')
        edge(busy,order.get('Name')+'.A','SetFalse')
        edge(lesson,order.get('Name')+'.B','dialogue_finished')
        occupancy.append(busy.get('Name')+'.State')
    if not occupancy:raise ValueError('Training authorization needs its real conversation release')
    edge(lesson,any_of(nodes,stem+'_talking',occupancy),'dialogue_busy')
    return dict(shared_worker=True,acknowledged_cleanup=True,runtime_verified=False)
