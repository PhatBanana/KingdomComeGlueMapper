"""Read and relocate the complete native collect/chop/store workstation graph."""
import copy
import re
from pathlib import Path
import xml.etree.ElementTree as E
import zipfile

from campaign_entity_links import guid_value
from character_person import unique
from character_job_items import reservation_contract
from cooking_pots import rotate
from entity_visuals import quaternion_product
from upgrade_map import read

TABLE = 'Libs/Tables/ai/smartEntity/SmartEntity__so_choppingWood.xml'


def graph(job, entities):
    def linked(e, label, category=None):
        found = [entities[l.get('TargetId')] for l in e.findall('EntityLinks/Link') if l.get('Name') == label]
        if category:
            found = [e for e in found if category in e.find('Properties').get('sWH_AI_EntityCategory', '').split(',')]
        return unique(found, 'native chopping '+label)
    pivot = linked(job, 'chopping', 'Pivot')
    collect, unload = linked(job, 'collect'), linked(job, 'setAside')
    reservation = unique(reservation_contract(job, entities), 'chopping item reservation')
    if (reservation['behavior'], reservation['decision']) != ('use', 'camper_woodChopping'):
        raise ValueError('Native chopping item decision changed')
    reservation_point = linked(job, reservation['definition'])
    roles = dict(job=job, pivot=pivot, collect=collect, unload=unload,
        chopBasket=linked(job, 'chopping', 'BasketSlot'),
        axe=linked(pivot, 'axeSlot'), log=linked(pivot, 'logSlot'), half=linked(pivot, 'logHalfSlot'),
        collectBasket=linked(collect, 'slot'), unloadBasket=linked(unload, 'basket'),
        reservation=reservation_point, basket=linked(reservation_point, ''))
    ids = {e.get('EntityId') for e in roles.values()}
    if len(ids) != len(roles) or any(l.get('TargetId') not in ids for e in roles.values() for l in e.findall('EntityLinks/Link')):
        raise ValueError('Native chopping graph is not self-contained')
    names = {e.get('EntityId'): r for r,e in roles.items()}
    actual = sorted((r, names[l.get('TargetId')], l.get('Name')) for r,e in roles.items() for l in e.findall('EntityLinks/Link'))
    expected = [('job','pivot','chopping'), ('job','chopBasket','chopping'), ('job','collect','collect'),
        ('job','unload','setAside'), ('job','job','+Soil[use,4]'), ('job','reservation',reservation['definition']),
        ('reservation','basket',''), ('pivot','axe','axeSlot'), ('pivot','log','logSlot'),
        ('pivot','half','logHalfSlot'), ('collect','collectBasket','slot'), ('unload','unloadBasket','basket')]
    if actual != sorted(expected): raise ValueError('Native chopping links changed')
    if [l.get('Name') for l in job.findall('EntityLinks/Link')].count('+Soil[use,4]') != 1:
        raise ValueError('Native chopping soil role changed')
    for role, family in (('pivot', 'chopping'), ('collect', 'wood_big'), ('unload', 'wood_small')):
        if roles[role].find('Properties').get('soclass_SmartObjectHelpers') != family:
            raise ValueError('Native chopping helper changed')
    for role in ('chopBasket', 'collectBasket', 'unloadBasket'):
        p = roles[role].find('Properties')
        if p.get('bSpawnOnStart') != '0' or p.get('guidItemClassId') != reservation['item_id']:
            raise ValueError('Native chopping set-aside slot changed')
    for role in ('log', 'half'):
        if roles[role].find('Properties').get('bInvisibleContent') != '1':
            raise ValueError('Native chopping phase item changed')
    return roles, reservation


def native_contract(target):
    target = Path(target)
    with zipfile.ZipFile(target/'Data/Tables.pak') as z:
        template = E.fromstring(read(z, TABLE)).find('.//SmartEntityTemplate')
    use = template.find("BehaviorTemplates/SmartBehaviorTemplate[@Name='use']")
    if use is None or use.get('MaxInstances') != '1' or use.get('InitialState') != 'Enabled':
        raise ValueError('Native chopping lost exclusive use')
    location = use.find('TreeLocation')
    with zipfile.ZipFile(target/'Data/Scripts.pak') as z:
        filename = re.sub(r'[\\/]+', '/', location.get('FileName'))
        root = E.fromstring(read(z, 'AI/'+filename)).find("BehaviorTree[@name='"+location.get('TreeName')+"']/Root")
    hand = None if root is None else root.find('.//HandContentElement')
    if (hand is None or hand.get('decisionLabel') != 'camper_woodChopping' or hand.get('useDecision') != 'true'
            or hand.get('allowHomeSlotAutoReturn') != 'false'
            or root.find(".//ItemSetAsideElement[@slot='$chopSetAsideSlot']") is None
            or root.find(".//UnstanceAction[@unstance='lumberjack_woodChopping']") is None
            or {a.get('fragment', '').strip("'") for a in root.iter('AnimationAction')} !=
                {'WoodChopping_logsToBasket', 'WoodChopping_choppedToBasket', 'WoodChopping_choppedToStack'}):
        raise ValueError('Native chopping lifecycle changed')
    queries = list(root.iter('GraphSearch'))
    expected = [('$__object.id','collect','$collectAlignPoint',''), ('$collectAlignPoint','slot','$collectSetAsideSlot',''),
        ('$__object.id','chopping','$chopAlignPoint','Pivot'), ('$__object.id','chopping','$chopSetAsideSlot','BasketSlot'),
        ('$__object.id','setAside','$putAwayAlignPoint',''), ('$putAwayAlignPoint','basket','$putAwaySetAsideSlot','')]
    if len(queries) != len(expected): raise ValueError('Native chopping queries changed')
    for query, (origin, label, result, category) in zip(queries, expected):
        filters = ['LinkTagFilter'] + (['CategoryFilter'] if category else []) + ['Nodalyzer']
        if ([c.tag for c in query] != filters or query.get('Origin') != origin or query.get('depth') != '1'
                or query.find('LinkTagFilter').get('tag') != "'"+label+"'"
                or query.find('Nodalyzer').get('Child') != result
                or (category and query.find('CategoryFilter').get('categories') != "'"+category+"'")):
            raise ValueError('Native chopping query links changed')
    with zipfile.ZipFile(target/'Data/Levels/trosecko/level.pak') as z:
        mission = E.fromstring(read(z, 'objects_mission0.xml'))
        rows = E.fromstring(read(z, 'tables/ai/scheduler.xml')).find('Schedulers')
        helpers = E.fromstring(read(z, 'smartobjecthelpersetanimations.xml'))
    from seating_animations import collection_hash
    for family in ('chopping', 'wood_big', 'wood_small', 'ChoppingAxe', 'Basket_empty'):
        collection = unique((c for c in helpers if c.get('HelperSetName') == family), 'native chopping helpers')
        collection_hash(collection)
        if family in ('chopping', 'wood_big', 'wood_small') and any(t.attrib != dict(Rotation='1,0,0,0', Position='0,0,0') for t in collection.iter('HelperTransformLocal')):
            raise ValueError('Native chopping origin changed')
    entities = {e.get('EntityId'): e for e in mission}
    candidates = {str(guid_value(e.get('EntityGuid'))): e for e in mission if e.find('Properties') is not None
                  and e.find('Properties').get('guidSmartObjectType') == template.get('DatabaseId')}
    for activity in rows.findall('.//S_ActivityLink'):
        p = activity.find('Parameters'); job = candidates.get(activity.get('TargetGuid'))
        if job is None or p is None: continue
        if activity.get('PositioningDelegate') != '0' or any(p.get(k) != v for k, v in
                dict(BehaviorName='use', BehaviorOverride='false', ProvidedRole='use', AllowedGenders='0', TimeOfDayStart='0', TimeOfDayEnd='1440').items()): continue
        if any(k in p.attrib for k in ('RequiredRole', 'RequiredContext', 'LinkTag')): continue
        terminal = unique((r for r in rows if r.get('EntityGuid') == activity.get('TargetGuid')), 'native chopping terminal')
        if terminal.tag != 'C_SmartHub' or terminal.find('Links') is not None or terminal.find(".//EffectSoil[@Role='use'][@SoilRate='4.000000']") is None: continue
        roles, reservation = graph(job, entities)
        return dict(roles=roles, reservation=reservation, activity=copy.deepcopy(activity), terminal=copy.deepcopy(terminal))
    raise ValueError('Missing native chopping scheduler contract')


def relocate(entity, origin, contact):
    """Rigid placement of native attachment offsets around a source animation contact."""
    vec = lambda v: tuple(map(float, v.split(',')))
    q = vec(origin.get('Rotate', '1,0,0,0')); inverse = (q[0], -q[1], -q[2], -q[3])
    q = quaternion_product(vec(contact['Rotate']), inverse)
    delta = rotate(q, tuple(a-b for a, b in zip(vec(entity.get('Pos')), vec(origin.get('Pos')))))
    result = copy.deepcopy(entity)
    result.set('Pos', ','.join(format(a+b, '.10g') for a,b in zip(vec(contact['Pos']), delta)))
    result.set('Rotate', ','.join(format(x, '.10g') for x in quaternion_product(q, vec(entity.get('Rotate', '1,0,0,0')))))
    return result
