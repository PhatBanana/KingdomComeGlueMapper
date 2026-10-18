"""Convert source single-point GraphSearch -> ExactMove -> Wait routines.

Selection is structural, never a character, quest or location name. Resolve the
authored graph edge before replacing its local variable with the work holder.
Other routines remain unsupported rather than silently becoming idle jobs.
"""
import hashlib
import re
import uuid
import xml.etree.ElementTree as E
from campaign_bindings import parse_link_labels
from character_person import resolve_link_targets
from upgrade_map import read, xml


def unquote(value):
    return value[1:-1] if value.startswith('"') and value.endswith('"') else value


def recognize(tree):
    root = tree.find('Root')
    if root is None or [c.tag for c in root] != ['Behavior']:
        return None
    body = root.find('Behavior')
    if len(body) != 1 or body[0].tag != 'Sequence': return None
    nodes = list(body[0])
    if [n.tag for n in nodes] != ['GraphSearch', 'ExactMove', 'Wait']: return None
    search, move, wait = nodes
    attrs = {k:unquote(v) for k,v in search.attrib.items()}
    if attrs.get('Origin') != '__object.id' or attrs.get('depth') != '1': return None
    if attrs.get('selection') != 'true' or attrs.get('includeOrigin') != 'false': return None
    if any(attrs.get(k,'') for k in ('Borders','AllowedEdges','SubGraph')): return None
    if attrs.get('AllowSubtraph','false') != 'false' or attrs.get('excludeOrigin','false') != 'false': return None
    if len(search) != 1 or search[0].tag != 'LinkDataFilter': return None
    filt = {k:unquote(v) for k,v in search[0].attrib.items()}
    tag = filt.get('tag', '')
    match = re.fullmatch(r'\$'+re.escape(tag)+r"\s*==\s*'([^']+)'", filt.get('condition',''))
    if not match or filt.get('Parent') or filt.get('Data'): return None
    if filt.get('prune','true') != 'true' or filt.get('negprune','unknown') != 'unknown': return None
    variable = filt.get('Child')
    movement = {k:unquote(v) for k,v in move.attrib.items()}
    waiting = {k:unquote(v) for k,v in wait.attrib.items()}
    if not variable or movement.get('destinationSpecification') != variable: return None
    if movement.get('directionType') != 'AlignWithEntity' or movement.get('directionSpecification') != variable: return None
    if any(movement.get(k) for k in ('destinationSpecification2','destinationSpecification3',
            'additionalParams','pathFindingParams','staminaPolicy','pathInfo','AnimationToPlay','AnimationContext')): return None
    if waiting != dict(duration='-1',timeType='GameTime',doFail='false',variation='',skipInLOD='false'): return None
    from campaign_behavior import CONTRACTS
    if set(movement) - CONTRACTS['ExactMove'].keys(): return None
    movement['destinationSpecification'] = '$__object.id'
    movement['directionSpecification'] = '$__object.id'
    return dict(tag=tag, value=match[1], movement=movement, wait=waiting)


def resolve(entry, archive, source, reader):
    behavior = entry['behavior']
    blob = reader(source, {'work':('Scripts.pak','Libs/AI/'+behavior['tree_file'])})['work']['data']
    trees = [t for t in E.fromstring(blob).findall('BehaviorTree') if t.get('name') == behavior['tree_name']]
    if len(trees) != 1: raise ValueError('Missing or ambiguous source work tree')
    contract = recognize(trees[0])
    if contract is None: raise ValueError('Unsupported source controller work routine: '+behavior['tree_name'])
    links = []
    for link in entry['target_links']:
        if not link.get('Name'): continue
        for tag in parse_link_labels(link['Name']):
            if tag['tag'] == contract['tag'] and tag['positional'] == [contract['value']] and not tag['named']:
                links.append(link)
    if len(links) != 1: raise ValueError('Station routine requires one authored destination')
    area = E.Element('Entity', entry['area'])
    E.SubElement(E.SubElement(area,'EntityLinks'),'Link',links[0])
    entities = resolve_link_targets(archive,area,list(E.fromstring(read(archive,'objects_mission0.xml'))),{})
    points = [e for e in entities if e.get('EntityId') == links[0]['TargetId']]
    if len(points) != 1 or points[0].get('EntityClass') != 'TagPoint':
        raise ValueError('Station destination must be an authored TagPoint')
    return dict(entry, arrival=dict(points[0].attrib), station_work=contract)


def resources(contract):
    import json
    identity = hashlib.sha256(json.dumps(contract,sort_keys=True).encode()).hexdigest()[:16]
    name = 'gm_station_'+identity
    template = str(uuid.uuid5(uuid.NAMESPACE_URL,'kingdomcomegluemapper/'+name))
    table = E.Element('database',name='barbora')
    obj = E.SubElement(E.SubElement(table,'SmartEntitys',version='1'),'SmartEntityTemplate',
        DatabaseId=template,Name=name,UpdatePriority='false')
    bt = E.SubElement(E.SubElement(obj,'BehaviorTemplates'),'SmartBehaviorTemplate',Name='use',InitialState='Enabled',MaxInstances='1')
    E.SubElement(bt,'TreeLocation',FileName='gluemapper/'+name+'.xml',TreeName='use')
    trees = E.Element('BehaviorTrees')
    tree = E.SubElement(trees,'BehaviorTree',name='use',is_function='0')
    E.SubElement(tree,'Variables')
    root = E.SubElement(tree,'Root',OneTimeOnly='false',FailState='Recoverable',saveVersion='2')
    seq = E.SubElement(E.SubElement(root,'Behavior',canSkip='1'),'Sequence')
    E.SubElement(seq,'ExactMove',contract['movement'])
    E.SubElement(seq,'WaitAction')
    from campaign_behavior import quote
    waiting = dict(contract['wait'])
    waiting['duration'] = quote(waiting['duration'])
    E.SubElement(seq,'Wait',waiting)
    return template, {'Libs/Tables/ai/smartEntity/SmartEntity__'+name+'.xml':xml(table),
                      'AI/gluemapper/'+name+'.xml':xml(trees)}
