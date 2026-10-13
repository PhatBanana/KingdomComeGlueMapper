"""Register authored work-area programs in the unified smart-entity registry."""
import xml.etree.ElementTree as ET
import re

from campaign_ai_registration import require_fields, rows_for, tree_identity, bool_value
from campaign_dependencies import ImportPlan
from campaign_quest_graph import identifier, xml


def source_geometry(source):
    from character_person_world import source_home_geometry
    def element(node):
        result=ET.Element(node['op'],node['attributes'])
        for child in node['children']:result.append(element(child))
        return result
    # This shared converter applies XML local-space rotation/scale once;
    # callers use it only when compiled world-space FUBAR data is absent.
    return source_home_geometry(element(source))


def place_area(entity, source, template):
    """Preserve authored shape properties; compiled vertices remain world-space."""
    properties = [n for n in source['children'] if n['op']=='Properties']
    if len(properties)!=1:
        raise ValueError('Source work area requires one properties record')
    original=properties[0]
    require_fields(original['attributes'], ('bSaved_by_game','sWH_AI_EntityCategory','guidSmartAreaTemplate',
        'Label','layerEventLayer','EventIds','fEventDespawnDistance','guidLocationId','bNo_POI',
        'bPOI_discoverable_by_location'), 'work-area properties')
    attrs=dict(original['attributes'])
    if attrs.get('guidLocationId') not in (None,'','00000000-0000-0000-0000-000000000000'):
        raise ValueError('Work-area RPG location requires converted location registration')
    if attrs.get('layerEventLayer') or attrs.get('EventIds'):
        raise ValueError('Work-area event dispatch requires profile event conversion')
    if attrs.get('guidSmartAreaTemplate','').lower() != template.lower():
        attrs['guidSmartAreaTemplate']=template
    props=ET.SubElement(entity,'Properties',attrs)
    for child in original['children']:
        if child['op']!='Script' or child['children']:
            raise ValueError('Unknown work-area script structure')
        require_fields(child['attributes'],('Misc','bValidWithoutTemplate'),'work-area script')
        if child['attributes'].get('Misc'):
            raise ValueError('Work-area Lua requires semantic conversion')
        ET.SubElement(props,'Script',child['attributes'])


def area_bindings(plans, world):
    """Carry quest ownership into placed templates, never infer it from a name."""
    from campaign_entity_links import native_guid
    entities={native_guid(int(r['attributes']['EntityGuid'],16)):r for r in world['entities'].values()
              if r['attributes'].get('EntityClass')=='SmartAreaShape'
              and re.fullmatch(r'[0-9a-fA-F]{16}',r['attributes'].get('EntityGuid',''))}
    result={}
    for owner,plan in plans.items():
        for binding in plan['bindings']:
            guid=binding['registration'].get('guid')
            if guid not in entities:
                continue
            props=[n for n in entities[guid]['entity']['children'] if n['op']=='Properties']
            if len(props)!=1 or not props[0]['attributes'].get('guidSmartAreaTemplate'):
                continue
            identity=owner+'|'+props[0]['attributes']['guidSmartAreaTemplate'].lower()
            if identity not in result.setdefault(guid,[]):result[guid].append(identity)
    return result


class SmartAreaAdapter:
    def __init__(self, tables, native):
        self.tables, self.native = tables, native

    def plan(self, identity):
        owner, guid = identity.split('|')
        identifier(owner)
        row = dict(self.tables.row('ai/sa_smart_area', 'sa_smart_area_id', guid))
        require_fields(row, ('sa_smart_area_id','sa_smart_area_name','brain_id','priority'), 'smart area')
        dependencies, behaviors = [], []
        if row.get('brain_id') not in (None, '', '00000000-0000-0000-0000-000000000000'):
            dependencies.append(('brains', owner + '|' + row['brain_id']))
        names = set()
        for link in rows_for(self.tables, 'sa_smart_area2sa_behaviour_tag', 'sa_smart_area_id', guid):
            require_fields(link, ('sa_smart_area_id','sa_behaviour_tag_id','priority'), 'area behavior link')
            if link['priority'] != '0':
                raise ValueError('Ranked area behaviors require request selection conversion')
            tag = dict(self.tables.row('ai/sa_behaviour_tag', 'sa_behaviour_tag_id', link['sa_behaviour_tag_id']))
            require_fields(tag, ('sa_behaviour_tag_id','sa_behaviour_tag_name','tree_file','tree_name',
                'on_enter_child_action','on_leave_action','on_success_action','on_fail_action'), 'area behavior')
            # Preserve the normal request lifetime. Other source policies need
            # explicit runtime transitions; do not silently discard them.
            for field, expected in [('on_enter_child_action','keep'), ('on_leave_action','keep'),
                                    ('on_success_action','drop'), ('on_fail_action','drop')]:
                action = self.tables.row('ai/sa_behaviour_action','sa_behaviour_action_id',tag[field])
                if action['sa_behaviour_action_name'] != expected:
                    raise ValueError('Area request lifecycle requires conversion: ' + field)
            if tag['sa_behaviour_tag_name'] in names:
                raise ValueError('Ambiguous source area behavior name')
            names.add(tag['sa_behaviour_tag_name'])
            reference = tree_identity(owner, tag['tree_file'], tag['tree_name'])
            dependencies.append(('behavior_trees', reference))
            behaviors.append(dict(row=tag, tree=reference, link=dict(link)))
        return ImportPlan(dependencies, dict(owner=owner,row=row,behaviors=behaviors))

    def convert(self, identity, plan, registered):
        source, target = plan.source, self.native.guid('smart_area', identity)
        row = source['row']
        root = ET.Element('database', name='barbora')
        templates = ET.SubElement(root,'SmartEntitys', version='1')
        attributes = dict(DatabaseId=target, Name=self.native.namespace + '_' + row['sa_smart_area_name'],
                          UpdatePriority=bool_value(row['priority']))
        if row.get('brain_id') not in (None, '', '00000000-0000-0000-0000-000000000000'):
            attributes['BrainId'] = registered['brains'][(source['owner']+'|'+row['brain_id']).lower()]
        entity = ET.SubElement(templates,'SmartEntityTemplate',attributes)
        if source['behaviors']:
            container = ET.SubElement(entity,'BehaviorTemplates')
            for record in source['behaviors']:
                # Source area behaviors have no per-job capacity or disabled
                # state; capacity comes from reservations inside their trees.
                behavior = ET.SubElement(container,'SmartBehaviorTemplate', InitialState='Enabled',
                    MaxInstances='-1',Name=record['row']['sa_behaviour_tag_name'])
                path, name = registered['behavior_trees'][record['tree'].lower()].split('|')
                ET.SubElement(behavior,'TreeLocation',FileName=path,TreeName=name)
        path = 'Libs/Tables/ai/smartEntity/SmartEntity__' + self.native.namespace + '_' + target + '.xml'
        return target, {path:xml(root)}, dict(source_template=row['sa_smart_area_id'],
            behavior_callbacks=len(source['behaviors']), runtime_validated=False)
