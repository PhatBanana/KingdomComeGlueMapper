"""Discover authored roadside sites without enabling source quest profiles."""
import math
import xml.etree.ElementTree as E

from animal_population_sources import transform
from campaign_trigger_areas import read_areas
from upgrade_map import read

FAMILIES = {'Wanderer': ('pocestny', ('wanderer',)),
            'AmbushPlayer': ('prepadeniNaCeste', ('spawn',))}
GENERIC_CONDITIONS = {'1', "gvar('fast_travel_suppress_events') == 0"}


def discover(archive, tables):
    index = {n.replace('\\','/').lower():n for n in archive.namelist()}
    main = E.fromstring(read(archive,index['objects_mission0.xml']))
    entities = {e.get('EntityId'):e for e in main}
    profiles = {p.findtext('Name'):p for p in E.fromstring(read(archive,index['whdata_1'])).iter('GameProfile')}
    records = {r['random_event_id']:r for r in tables['random_event']}
    sets = {r['random_event_option_set_id']:r['random_event_option_set_name'] for r in tables['random_event_option_set']}
    shapes = {a.guid:a for a in read_areas(read(archive,index['triggerareas.fubar']))['areas']}
    sites, deferred = [], []
    for event in sorted((e for e in main if e.get('EntityClass')=='RandomEvent'), key=lambda e:e.get('EntityGuid')):
        props = event.find('Properties'); record = records.get(props.get('nRandomEventDBId'),{})
        kind = sets.get(record.get('random_event_option_set_id'))
        info = dict(name=event.get('Name'),guid=event.get('EntityGuid'),family=kind,
                    profile=props.get('gpGameProfile'),condition=record.get('condition_expression'))
        reason = None
        if kind not in FAMILIES: reason='requires a separate native scenery/route or quest adapter'
        elif record.get('condition_expression') not in GENERIC_CONDITIONS: reason='source quest-specific activation cannot be discarded'
        elif float(record.get('base_run_chance','0'))<=0: reason='disabled source event'
        if reason:
            deferred.append(dict(info,reason=reason));continue
        profile = profiles.get(info['profile'])
        if profile is None:
            deferred.append(dict(info,reason='no authored event profile'));continue
        placed = {}
        for layer in profile.findall('GameLayers/GameLayer'):
            path = 'layers/'+layer.text.lower()+'.xml'
            if path not in index: raise ValueError('Missing encounter profile layer: '+path)
            for e in E.fromstring(read(archive,index[path])).iter('Entity'):
                placed[e.get('EntityId')]=e
        family,categories=FAMILIES[kind]
        context={**entities,**placed}
        points=[transform(e,context) for e in placed.values() if e.get('EntityClass')=='TagPoint'
                and e.find('Properties') is not None and e.find('Properties').get('sWH_AI_EntityCategory') in categories]
        triggers=[]
        for link in event.findall('EntityLinks/Link'):
            if link.get('Name')!='trigger':continue
            e=context.get(link.get('TargetId'))
            if e is None or int(e.get('EntityGuid'),16) not in shapes: raise ValueError('Missing authored encounter trigger')
            triggers.append((transform(e,context),shapes[int(e.get('EntityGuid'),16)]))
        if not points or not triggers:
            deferred.append(dict(info,reason='missing authored spawn points or road approaches'));continue
        if len({p.get('EntityGuid') for p in points})!=len(points):raise ValueError('Duplicate encounter spawn identity')
        sites.append(dict(info,native_family=family,spawns=points,triggers=triggers,
                          source_record=record))
    return sites,deferred


def hull(points):
    """Footprint of the authored approach triggers; no guessed radius/centre."""
    points=sorted(set((float(p[0]),float(p[1])) for p in points))
    if len(points)<3 or not all(math.isfinite(v) for p in points for v in p):raise ValueError('Invalid encounter footprint')
    def cross(o,a,b):return (a[0]-o[0])*(b[1]-o[1])-(a[1]-o[1])*(b[0]-o[0])
    def half(items):
        result=[]
        for p in items:
            while len(result)>1 and cross(result[-2],result[-1],p)<=0:result.pop()
            result.append(p)
        return result
    result=half(points)[:-1]+half(reversed(points))[:-1]
    if len(result)<3:raise ValueError('Degenerate encounter footprint')
    return result
