"""Lower source crime district volumes into the native district discovery graph.

No NPC/place names or hand-authored bounds are used. Native district brains own
authority entry/exit; the converter does not permanently attach guards to areas.
"""
import copy
import xml.etree.ElementTree as ET
from campaign_entity_links import append_links, native_guid
from campaign_trigger_areas import read_areas, write_areas
from character_person_world import source_home_geometry
from upgrade_map import xml


def contains(area, position):
    x, y, z = position
    points = area.points
    if len(points) < 3:
        raise ValueError('Crime district requires a polygon')
    if not min(p[2] for p in points) <= z <= max(p[2] for p in points) + area.height:
        return False
    inside = False
    for a, b in zip(points, (*points[1:], points[0])):
        cross = (x-a[0])*(b[1]-a[1])-(y-a[1])*(b[0]-a[0])
        if abs(cross) < 1e-6 and min(a[0],b[0]) <= x <= max(a[0],b[0]) and min(a[1],b[1]) <= y <= max(a[1],b[1]):
            return True
        if (a[1] > y) != (b[1] > y) and x < (b[0]-a[0])*(y-a[1])/(b[1]-a[1])+a[0]:
            inside = not inside
    return inside


def discover(entities, tables, positions):
    templates = {r['sa_smart_area_id']: r['sa_smart_area_name']
                 for r in tables.get('ai/sa_smart_area')['rows']}
    roots, districts = [], []
    for entity in entities:
        props = entity.find('Properties')
        if props is None:
            continue
        kind = templates.get(props.get('guidSmartAreaTemplate'))
        if kind not in ('sa_crimeDistrictRoot', 'sa_crimeDistrict'):
            continue
        geometry = source_home_geometry(entity)
        if any(contains(geometry, p) for p in positions):
            (roots if kind == 'sa_crimeDistrictRoot' else districts).append(entity)
    if len(roots) != 1:
        raise ValueError('Profile population requires one unambiguous source crime root')
    if not districts:
        raise ValueError('Profile population has no source crime districts')
    return roots[0], districts


def convert(files, entities, root, districts, native_template):
    if native_template.get('Name') != 'sa_crime_district' or not native_template.get('BrainId'):
        raise ValueError('Native crime district brain contract missing')
    target_type = native_template.get('DatabaseId')
    if not target_type:
        raise ValueError('Native crime district type missing')
    mission = ET.fromstring(files['objects_mission0.xml'])
    originals = {}
    for entity in entities:
        originals.setdefault(entity.get('EntityId'), []).append(entity)
    geometries = read_areas(files['triggerareas.fubar'])
    areas = {a.guid: a for a in geometries['areas']}
    next_id = max((int(e.get('EntityId','0')) for e in mission), default=0)+1
    links, report = [], []
    def add(source, cls, props):
        nonlocal next_id
        guid = native_guid(int(source.get('EntityGuid'),16))
        existing = [e for e in mission if e.get('EntityGuid') == guid]
        target = ET.Element('Entity', {k:v for k,v in source.attrib.items()
            if k in ('Name','Pos','Rotate','Scale','CastShadowMinSpec')})
        target.set('EntityClass',cls);target.set('EntityGuid',guid)
        target.set('EntityId',existing[0].get('EntityId') if len(existing)==1 else str(next_id))
        target.append(ET.Element('Properties',props))
        if cls == 'SmartAreaShape':
            target.append(copy.deepcopy(source.find('Area')))
            geometry=source_home_geometry(source)
            if geometry.guid in areas and write_areas([areas[geometry.guid]],1)!=write_areas([geometry],1):
                raise ValueError('Conflicting crime district geometry: '+source.get('Name'))
            areas[geometry.guid]=geometry
        if existing:
            # Never replace an existing area/home/quest graph implicitly.
            if len(existing)!=1:
                raise ValueError('Duplicate destination crime entity')
            for k in ('EntityClass','Name','Pos','Rotate','Scale'):
                if existing[0].get(k)!=target.get(k):
                    raise ValueError('Conflicting existing crime entity: '+source.get('Name'))
            if ET.tostring(existing[0].find('Properties')) != ET.tostring(target.find('Properties')):
                raise ValueError('Existing crime entity needs explicit migration: '+source.get('Name'))
            return existing[0]
        if any(e.get('Name')==target.get('Name') for e in mission):
            raise ValueError('Crime entity name collision: '+target.get('Name'))
        next_id+=1;mission.append(target);return target
    def link(a,b,label):
        container=a.find('EntityLinks')
        if container is None:container=ET.SubElement(a,'EntityLinks')
        if not any(l.get('TargetGuid')==b.get('EntityGuid') and l.get('Name')==label for l in container):
            ET.SubElement(container,'Link',TargetId=b.get('EntityId'),TargetGuid=b.get('EntityGuid'),Name=label)
        links.append((a.get('EntityGuid'),b.get('EntityGuid'),label))
    main=add(root,'SmartAreaShape',dict(Label='crimeDistrict_main',bSaved_by_game='0'))
    for source in districts:
        arrivals=source.findall("EntityLinks/Link[@Name='inside']")
        if len(arrivals)!=1 or len(originals.get(arrivals[0].get('TargetId'),[]))!=1:
            raise ValueError('District requires one authored origin')
        origin=originals[arrivals[0].get('TargetId')][0]
        if origin.get('EntityClass')!='TagPoint':
            raise ValueError('District origin must be a source TagPoint')
        district=add(source,'SmartAreaShape',dict(Label='crimeDistrict',guidSmartAreaTemplate=target_type,bSaved_by_game='0'))
        anchor=add(origin,'TagPoint',dict(bSaved_by_game='0'))
        link(main,district,'crime_district');link(district,anchor,'crime_districtOrigin')
        report.append(dict(source=source.get('Name'),guid=district.get('EntityGuid'),origin=anchor.get('EntityGuid'),
            pending_links=[dict(l.attrib) for l in source.findall('EntityLinks/Link') if l.get('Name')!='inside']))
    result=dict(files)
    result['objects_mission0.xml']=xml(mission)
    result['triggerareas.fubar']=write_areas(list(areas.values()),geometries['export_version'])
    result['waitinglinks.xml']=append_links(files['waitinglinks.xml'],links)
    return result,dict(main=main.get('EntityGuid'),districts=report,
        native_authority_entry_exit=True,runtime_verified=False,
        pending_root_links=[dict(l.attrib) for l in root.findall('EntityLinks/Link')],
        pending=['confiscated item storage and jail sentence handling are separate source contracts'])
