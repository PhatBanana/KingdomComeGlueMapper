"""Connect a source-selected lesson to one native equipment worker.

All identities and objective bindings are caller inputs. The host never moves
an actor, advances time, awards quest progress on a timer, or acknowledges work
which an active worker has not finished.
"""
import xml.etree.ElementTree as E

from campaign_quest_graph import edge, constant, any_of, identifier


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
