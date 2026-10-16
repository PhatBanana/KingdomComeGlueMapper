"""Upgrade the bounded source broom route phase using native item lifetimes.

The source path geometry and dwell durations remain data. Native sweeping owns
the hand item and animation; the scheduler owns pickup/return and interruption.
This does not claim to convert cooking or the rest of the housework selector.
"""
import copy
import re
from pathlib import Path
import uuid
import xml.etree.ElementTree as E
import zipfile
from character_work_paths import validate_graph, bind_path
from upgrade_map import read, xml

TEMPLATE = str(uuid.uuid5(uuid.NAMESPACE_URL, 'gluemapper/source-sweeping-route'))


def resources(source, target):
    with zipfile.ZipFile(Path(source)/'Data/Scripts.pak') as z:
        original=E.fromstring(read(z,'Libs/AI/final/so_broom.xml')).find("BehaviorTree[@name='sweeping']")
    if original is None:raise ValueError('Missing source sweeping program')
    count=original.find("Variables/Variable[@name='lodWaitingTime']")
    loops=[n for n in original.findall('./Root//While')
           if n.get('condition','').strip('"').replace(' ','')=='$lodWaitingTime>0']
    waits={n.get('duration','').strip('"') for loop in loops for n in loop.findall('Sequence/Wait')}
    # Only translate the demonstrated two-stage route phase. Changed source
    # programs must be reviewed rather than silently assigned default timing.
    if count is None or not count.get('values','').isdigit() or int(count.get('values'))<=0 or len(waits)!=1:
        raise ValueError('Unsupported source sweeping dwell program')
    wait=next(iter(waits))
    if not re.fullmatch(r'[1-9][0-9]*s',wait) or not loops:
        raise ValueError('Unsupported source sweeping wait unit')
    for loop in loops:
        children=list(loop.find('Sequence'))
        if ([n.tag for n in children]!=['Wait','Expression'] or
            children[0].get('timeType','').strip('"')!='GameTime' or
            children[1].get('expressions','').strip('"').replace(' ','')!='$lodWaitingTime-=1'):
            raise ValueError('Source sweeping wait has additional effects')
    duration=str(int(count.get('values'))*int(wait[:-1]))+'s'
    with zipfile.ZipFile(Path(target)/'Data/Scripts.pak') as z:
        trees=E.fromstring(read(z,'AI/world/so_sweeping.xml'))
        move_catalog=E.fromstring(read(z,'AI/animal/so_animalBehaviors_horse.xml'))
    native_move=next((n for t in move_catalog for n in t.findall('.//Root//Move')
        if n.get('destinationSpecification2')=='$pathParams'),None)
    if native_move is None:raise ValueError('Native predefined-path movement contract missing')
    tree=trees.find("BehaviorTree[@name='use']")
    for n in list(tree):
        if n.tag not in ('Variables','Root'):tree.remove(n)
    variables=tree.find('Variables')
    E.SubElement(variables,'Variable',name='route',type='_wuid',values='',isPersistent='0',form='single')
    E.SubElement(variables,'Variable',name='pathParams',type='predefinedPathParams',values='',isPersistent='0',form='single')
    sequence=tree.find('.//Root/Behavior/HandContentElement/Exec/EntityContextElement/EntityContextElement/Sequence')
    if sequence is None:raise ValueError('Native sweeping item lifetime changed')
    animation=copy.deepcopy(sequence.find('UnstanceAction'))
    if animation is None:raise ValueError('Missing native sweeping animation')
    sequence.clear()
    search=E.SubElement(sequence,'GraphSearch',Origin='$__object.id',Borders='',depth='1',selection='true',
        SearchPattern='Depth',EdgePruning="'parent,inventory'",AllowedEdges='',SubGraph='',AllowSubtraph='false',
        includeOrigin='false',excludeOrigin='false',failOnEmpty='true',SetOperationChoice='Intersection|And',
        errorOnEmpty='false',shortCircuit='false',skipTraversed='true')
    E.SubElement(search,'LinkTagFilter',tag="'SweepingPath'",prune='true',negprune='unknown',Parent='',Child='',Data='')
    E.SubElement(search,'Nodalyzer',Quantifiers='Exists',Parent='',Child='$route',saveVersion='2')
    for approach in ('true','false'):
        E.SubElement(sequence,'Expression',expressions='$pathParams.approachFirstNode = '+approach+', $pathParams.reversePath = false')
        move=copy.deepcopy(native_move)
        move.set('destinationSpecification','$route');move.set('speed','Walk');move.set('successDistance','0')
        sequence.append(move)
        sequence.append(copy.deepcopy(animation))
        E.SubElement(sequence,'Wait',duration="'"+duration+"'",timeType='GameTime',doFail='false',variation='',skipInLOD='false')
    with zipfile.ZipFile(Path(target)/'Data/Tables.pak') as z:
        table=E.fromstring(read(z,'Libs/Tables/ai/smartEntity/SmartEntity__so_sweeping.xml'))
    template=table.find('.//SmartEntityTemplate');template.set('DatabaseId',TEMPLATE);template.set('Name','gm_sweeping_route')
    template.find('.//TreeLocation').set('FileName','gluemapper/sweeping_route.xml')
    return {'AI/gluemapper/sweeping_route.xml':xml(trees),
        'Libs/Tables/ai/smartEntity/SmartEntity__gm_sweeping_route.xml':xml(table)},dict(dwell_seconds=int(duration[:-1]),source='final/so_broom.xml:sweeping')


def bind(mission, job, routes, source_graph, target_graph):
    paths, evidence=validate_graph(source_graph,target_graph)
    edges=[]; records=[]
    for source in routes:
        path,record=bind_path(mission,source,paths)
        container=job.find('EntityLinks')
        if container is None:container=E.SubElement(job,'EntityLinks')
        E.SubElement(container,'Link',Name='SweepingPath',TargetId=path.get('EntityId'),TargetGuid=path.get('EntityGuid'))
        edges.append((job.get('EntityGuid'),path.get('EntityGuid'),'SweepingPath'));records.append(record)
    job.find('Properties').set('guidSmartObjectType',TEMPLATE)
    return edges,dict(graph=evidence,paths=records)
