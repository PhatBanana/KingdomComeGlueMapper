"""Upgrade separate source map assets without confusing them with counted items."""
import xml.etree.ElementTree as ET
from campaign_entity_links import native_guid, append_links
from campaign_quest_graph import objective_identifier, xml
from campaign_bindings import asset_name


def bind(project_blob, quest_blob, objects_blob, waiting_blob, model, source_entities):
    project, quest, objects = map(ET.fromstring, (project_blob, quest_blob, objects_blob))
    host = project.find('./Skald/Project')
    holders = [e for e in objects.iter('Entity') if e.get('Name') == host.get('Name')]
    if len(holders) != 1:
        raise ValueError('Missing or ambiguous project holder for map assets')
    holder = holders[0]
    places = {r['quest_asset_id']: r for r in model['tables'].get('quest_place', {}).get('rows', [])}
    objectives = {r['objective_id']: r['objective_name'] for r in model['tables']['quest_objective']['rows']}
    assets = host.find('Assets')
    if assets is None: assets = ET.SubElement(host, 'Assets')
    links = holder.find('EntityLinks')
    if links is None: links = ET.SubElement(holder, 'EntityLinks')
    additions, report, pending = [], [], []
    for row in model['tables'].get('quest_tracked_asset', {}).get('rows', []):
        key = row.get('map_asset_id') or row.get('quest_asset_id')
        if row.get('on_map', '').lower() != 'true' or key not in places: continue
        place = places[key]
        if place.get('map') or place.get('show_as_area', 'False').lower() == 'true':
            pending.append(dict(source=place, reason='Cross-map or area marker requires a spatial adapter'))
            continue
        candidates = {ET.tostring(e): e for e in source_entities if e.get('Name') == place['entity']}
        if len(candidates) != 1: raise ValueError('Missing or ambiguous source map place: ' + place['entity'])
        source = next(iter(candidates.values()))
        if source.get('EntityClass') != 'TagPoint':
            pending.append(dict(source=place, reason='Unsupported map place class: ' + str(source.get('EntityClass'))))
            continue
        guid = native_guid(int(source.get('EntityGuid').replace('-', ''), 16))
        alias = asset_name(model['quest'], 'map_place', key)
        existing = [e for e in objects.iter('Entity') if e.get('EntityGuid') == guid]
        if existing:
            if len(existing) != 1 or existing[0].get('EntityClass') != 'TagPoint' or existing[0].get('Pos') != source.get('Pos'):
                raise ValueError('Conflicting destination map place')
            target = existing[0]
        else:
            target = ET.SubElement(objects, 'Entity', Name=source.get('Name'), EntityClass='TagPoint',
                EntityGuid=guid, EntityId=str(max(int(e.get('EntityId', '0')) for e in objects.iter('Entity'))+1),
                Pos=source.get('Pos'))
            ET.SubElement(target, 'Properties', bSaved_by_game='0')
        matches = [a for a in assets if a.get('Name') == alias]
        if matches and (len(matches) != 1 or matches[0].tag != 'TagPointAsset'):
            raise ValueError('Conflicting map asset alias')
        if not matches: ET.SubElement(assets, 'TagPointAsset', Name=alias)
        label = "asset['" + alias + "']"
        old_links = [e for e in links if e.get('Name') == label]
        if old_links and any(e.get('TargetGuid') != guid for e in old_links):
            raise ValueError('Conflicting map asset link')
        if not old_links: ET.SubElement(links, 'Link', Name=label, TargetId=target.get('EntityId'), TargetGuid=guid)
        additions.append((holder.get('EntityGuid'), guid, label))
        name = objective_identifier(objectives[row['objective_id']])
        log = quest.find("./Skald/Quest/Objectives/Objective[@Name='"+name+"']/Logs/EnumLog[@Type='Started']")
        if log is None: raise ValueError('Missing objective Started log')
        if log.get('Marker') not in (None, alias): raise ValueError('Conflicting objective map marker')
        log.set('Marker', alias)
        report.append(dict(objective=name, source_place=place['entity'], marker=alias, position=source.get('Pos')))
    return xml(project), xml(quest), xml(objects), append_links(waiting_blob, additions), dict(converted=report, pending=pending)
