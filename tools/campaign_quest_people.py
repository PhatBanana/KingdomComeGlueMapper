"""Resolve explicit quest NPC dependencies and bind native journal soul markers.

Importing a person does not convert that person's dialogue or daily schedule.
"""
import uuid
import xml.etree.ElementTree as ET
from collections import defaultdict
from campaign_quest_graph import identifier, objective_identifier, xml


def dependencies(model):
    result = {}
    for row in model['tables'].get('quest_npc', {}).get('rows', []):
        aid = row['quest_asset_id']
        if row['quest_id'] != model['quest_id'] or aid in result:
            raise ValueError('Mismatched or duplicate quest NPC')
        if row.get('soul_id'):
            uuid.UUID(row['soul_id'])
        result[aid] = row
    return result


def bind_markers(project_blob, quest_blob, model, registered):
    """Only bind explicit, registered souls; never interpret editor graph positions."""
    people = dependencies(model)
    project = ET.fromstring(project_blob)
    owner = project.find('./Skald/Project')
    quest = ET.fromstring(quest_blob)
    q = quest.find('./Skald/Quest')
    if owner is None or q is None or q.get('Name') != model['quest']:
        raise ValueError('Wrong project or quest definition')
    assets = owner.find('Assets')
    if assets is None: assets = ET.SubElement(owner, 'Assets')
    objectives = {r['objective_id']: r for r in model['tables']['quest_objective']['rows']}
    grouped = defaultdict(list)
    for row in model['tables'].get('quest_tracked_asset', {}).get('rows', []):
        if row['quest_id'] != model['quest_id'] or row['objective_id'] not in objectives:
            raise ValueError('Unknown tracked objective')
        target = row.get('map_asset_id') or row['quest_asset_id']
        if target in people and row.get('on_map', '').lower() == 'true':
            grouped[row['objective_id']].append(dict(row, quest_asset_id=target))
    converted, pending = [], []
    for oid, rows in grouped.items():
        name = objective_identifier(objectives[oid]['objective_name'])
        if any(people[r['quest_asset_id']].get('soul_class_id') or
               people[r['quest_asset_id']].get('soul_faction_id') for r in rows):
            pending.append(dict(objective=name, reason='Unsupported NPC filter')); continue
        soul_ids = {people[r['quest_asset_id']].get('soul_id') for r in rows}
        if len(soul_ids) != 1 or not soul_ids <= set(registered):
            pending.append(dict(objective=name, reason='Unresolved or multiple soul targets')); continue
        sid = next(iter(soul_ids))
        matches = [a for a in assets.findall('SoulAsset') if a.get('SharedSoulGuids') == sid]
        if matches:
            alias = matches[0].get('Name')
        else:
            alias = identifier('quest_person_' + sid.replace('-', '_'))
            if any(a.get('Name') == alias for a in assets): raise ValueError('Conflicting asset alias')
            ET.SubElement(assets, 'SoulAsset', Name=alias, SharedSoulGuids=sid)
        log = q.find(f"Objectives/Objective[@Name='{name}']/Logs/EnumLog[@Type='Started']")
        if log is None: raise ValueError('Missing native objective log: ' + name)
        if log.get('Marker') not in (None, alias): raise ValueError('Conflicting objective marker')
        log.set('Marker', alias)
        converted.append(dict(objective=name, soul_id=sid, marker=alias))
    return xml(project), xml(quest), dict(converted=converted, pending=pending, runtime_verified=False)
