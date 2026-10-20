"""Upgrade source sweeping locations using native point movement and item lifetimes.

The source path vertices become ordered work destinations. Native sweeping owns
the approach checks, hand item and animation; the scheduler owns pickup/return
and interruption. Movement between points is delegated to native navigation.
This does not claim to convert cooking or the rest of the housework selector.
"""
import copy
import re
from pathlib import Path
import uuid
import xml.etree.ElementTree as E
import zipfile
from character_work_paths import read_paths, bind_path
from campaign_entity_links import guid_value, append_links
from upgrade_map import read, xml
from character_job_routes import bind_points, lookup, native_approach, FIRST, NEXT

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
    tree=trees.find("BehaviorTree[@name='use']")
    for n in list(tree):
        if n.tag not in ('Variables','Root'):tree.remove(n)
    variables=tree.find('Variables')
    E.SubElement(variables,'Variable',name='route',type='_wuid',values='',isPersistent='0',form='single')
    for name in ('workPoint', 'nextWorkPoint'):
        E.SubElement(variables,'Variable',name=name,type='_wuid',values='',isPersistent='0',form='single')
    sequence=tree.find('.//Root/Behavior/HandContentElement/Exec/EntityContextElement/EntityContextElement/Sequence')
    if sequence is None:raise ValueError('Native sweeping item lifetime changed')
    animation=copy.deepcopy(sequence.find('UnstanceAction'))
    if animation is None:raise ValueError('Missing native sweeping animation')
    approach = native_approach(sequence, '$workPoint')
    sequence.clear()
    search=E.SubElement(sequence,'GraphSearch',Origin='$__object.id',Borders='',depth='1',selection='true',
        SearchPattern='Depth',EdgePruning="'parent,inventory'",AllowedEdges='',SubGraph='',AllowSubtraph='false',
        includeOrigin='false',excludeOrigin='false',failOnEmpty='true',SetOperationChoice='Intersection|And',
        errorOnEmpty='false',shortCircuit='false',skipTraversed='true')
    E.SubElement(search,'LinkTagFilter',tag="'SweepingPath'",prune='true',negprune='unknown',Parent='',Child='',Data='')
    E.SubElement(search,'Nodalyzer',Quantifiers='Exists',Parent='',Child='$route',saveVersion='2')
    lookup(sequence, '$route', '$workPoint', FIRST)
    sequence.extend(copy.deepcopy(approach))
    sequence.append(copy.deepcopy(animation))
    E.SubElement(sequence,'Wait',duration="'"+duration+"'",timeType='GameTime',doFail='false',variation='',skipInLOD='false')
    # The work route supplies ordered destinations, not a forced movement
    # track. Each leg uses the native job's own point-navigation and hand guards.
    loop = E.SubElement(sequence, 'While', condition='$workPoint ~= $__null',
                        doFail='false', propagateChildFail='true')
    step = E.SubElement(loop, 'Sequence')
    E.SubElement(step, 'Expression', expressions='$nextWorkPoint = $__null')
    lookup(step, '$workPoint', '$nextWorkPoint', NEXT, required=False)
    E.SubElement(step, 'Expression', expressions='$workPoint = $nextWorkPoint')
    valid = E.SubElement(step, 'IfCondition', condition='$workPoint ~= $__null', failOnCondition='false')
    move = E.SubElement(valid, 'Sequence')
    move.extend(copy.deepcopy(approach))
    sequence.append(copy.deepcopy(animation))
    E.SubElement(sequence,'Wait',duration="'"+duration+"'",timeType='GameTime',doFail='false',variation='',skipInLOD='false')
    with zipfile.ZipFile(Path(target)/'Data/Tables.pak') as z:
        table=E.fromstring(read(z,'Libs/Tables/ai/smartEntity/SmartEntity__so_sweeping.xml'))
    template=table.find('.//SmartEntityTemplate');template.set('DatabaseId',TEMPLATE);template.set('Name','gm_sweeping_route')
    template.find('.//TreeLocation').set('FileName','gluemapper/sweeping_route.xml')
    return {'AI/gluemapper/sweeping_route.xml':xml(trees),
        'Libs/Tables/ai/smartEntity/SmartEntity__gm_sweeping_route.xml':xml(table)},dict(
            dwell_seconds=int(duration[:-1]),source='final/so_broom.xml:sweeping',
            movement='native_job_point_navigation', native='AI/world/so_sweeping.xml:use',
            runtime_verified=False)


def bind(mission, job, routes, source_graph, target_graph):
    # Only source route coordinates are consumed. Native point navigation must
    # not require the destination navigation graph to equal KCD1 byte-for-byte.
    paths=read_paths(source_graph)
    evidence=dict(route_count=len(paths), movement='native_job_point_navigation',
                  target_navigation_modified=False)
    edges=[]; records=[]
    for source in routes:
        path,record=bind_path(mission,source,paths)
        # SweepingPath is a choice pool; unlike each route's successor edge it
        # may legitimately have multiple targets.
        container=job.find('EntityLinks')
        if container is None:container=E.SubElement(job,'EntityLinks')
        attrs=dict(Name='SweepingPath',TargetId=path.get('EntityId'),TargetGuid=path.get('EntityGuid'))
        if not any(n.attrib == attrs for n in container): E.SubElement(container,'Link',attrs)
        edges.append((job.get('EntityGuid'),path.get('EntityGuid'),'SweepingPath'))
        edges.extend(bind_points(mission,path,paths[int(source.get('EntityGuid'),16)]['points']))
        record['movement']='native_job_point_navigation';records.append(record)
    job.find('Properties').set('guidSmartObjectType',TEMPLATE)
    return edges,dict(graph=evidence,paths=records)


def upgrade_installed(files, source_graph):
    """Refresh all registered instances of this adapter, regardless of actor."""
    mission=E.fromstring(files['objects_mission0.xml'])
    paths=read_paths(source_graph)
    by_guid={}
    for entity in mission:
        if entity.get('EntityGuid'):
            by_guid.setdefault(entity.get('EntityGuid'),[]).append(entity)
    edges, report = [], []
    for job in list(mission):
        props=job.find('Properties')
        if props is None or props.get('guidSmartObjectType') != TEMPLATE:
            continue
        links=job.findall("EntityLinks/Link[@Name='SweepingPath']")
        if not links: raise ValueError('Installed work job has no authored routes')
        for link in links:
            matches=by_guid.get(link.get('TargetGuid'),[])
            if len(matches) != 1 or matches[0].get('EntityId') != link.get('TargetId'):
                raise ValueError('Installed work route reference is unresolved')
            route=matches[0]
            record=paths.get(guid_value(route.get('EntityGuid')))
            if record is None: raise ValueError('Installed work route has no source coordinates')
            edges.extend(bind_points(mission,route,record['points']))
            report.append(dict(job=job.get('Name'),route=route.get('Name'),points=len(record['points'])))
    if not report: raise ValueError('No converted route jobs found to upgrade')
    result=dict(files)
    result['objects_mission0.xml']=xml(mission)
    result['waitinglinks.xml']=append_links(files['waitinglinks.xml'],edges)
    return result,dict(jobs=report,movement='native_job_point_navigation',runtime_verified=False)
