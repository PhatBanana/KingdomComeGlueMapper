"""Resolve bounded native animal networks with destination-owned home areas."""
import copy
import xml.etree.ElementTree as E

from campaign_entity_links import guid_value


def habitat(mission, scheduler, *, soul=None, actor_class=None):
    entities = {str(guid_value(e.get('EntityGuid'))): e for e in mission if e.get('EntityGuid')}
    rows = {r.get('EntityGuid'): r for r in scheduler.find('Schedulers')}
    by_id = {e.get('EntityId'): k for k, e in entities.items()}
    allowed = {'AnimalSpawner', 'SmartObjectHolder', 'SchedulerHub', 'TagPoint', 'TriggerArea'}
    candidates = []
    for root, actor in entities.items():
        props = actor.find('Properties')
        if actor_class:
            if actor.get('EntityClass') != actor_class: continue
        elif actor.get('EntityClass') != 'AnimalSpawner' or props is None or props.get('guidSoul') != soul:
            continue
        todo, seen, bad = [root], set(), False
        while todo and len(seen) < 32:
            key = todo.pop()
            if key == '0' or key in seen: continue
            seen.add(key)
            e, row = entities.get(key), rows.get(key)
            if e is None and row is None: bad = True; break
            if e is not None:
                if key != root and (e.get('EntityClass') not in allowed or e.get('EntityClass') == 'AnimalSpawner'):
                    bad = True; break
                for link in e.findall('EntityLinks/Link'):
                    # Home is a destination binding, never a reason to copy
                    # native houses, owners, doors or crime districts.
                    if link.get('Name', '').split(',')[0] == 'home': continue
                    target = by_id.get(link.get('TargetId'))
                    if target: todo.append(target)
                    elif link.get('Name') != '_': bad = True
            if row is not None:
                if any(child.tag != 'Links' for child in row): bad = True
                for link in row.findall('Links/S_ActivityLink'):
                    params = link.find('Parameters')
                    if params is None or any(params.get(a) for a in ('RequiredContext', 'LinkTag')):
                        bad = True
                    todo.extend((link.get('TargetGuid'), link.get('PositioningDelegate', '0')))
        areas = [k for k in seen if k in entities and entities[k].get('EntityClass') == 'TriggerArea']
        if not bad and not todo and root in rows and len(areas) == 1:
            candidates.append((len(seen), root, seen, areas[0]))
    if not candidates:
        raise ValueError('No self-contained native habitat for ' + str(soul or actor_class))
    _, root, keys, area = min(candidates, key=lambda x: (x[0], x[1]))
    selected = {k: copy.deepcopy(entities[k]) for k in keys if k in entities}
    home = False
    homes = {}
    for e in selected.values():
        for link in e.findall('EntityLinks/Link'):
            if link.get('Name', '').split(',')[0] == 'home':
                home_key = by_id[link.get('TargetId')]
                original = entities[home_key]
                if original.get('EntityClass') != 'SchedulerHub':
                    raise ValueError('Unsupported native animal home binding')
                hub = E.Element('Entity', EntityClass='SchedulerHub',
                    EntityId=original.get('EntityId'), EntityGuid=original.get('EntityGuid'))
                links = E.SubElement(hub, 'EntityLinks')
                E.SubElement(links, 'Link', Name='home_area', TargetId=selected[area].get('EntityId'),
                             TargetGuid=selected[area].get('EntityGuid'))
                homes[home_key] = hub
                home = True
    selected.update(homes)
    # Native home rows may reach households and unrelated world activities.
    # Keep their scheduler registration, but not those outgoing activities.
    # An entity/editor link does not register a compiled scheduler node.
    selected_rows = {k: copy.deepcopy(rows[k]) for k in keys if k in rows and k not in homes}
    for key in homes:
        original = rows.get(key)
        if original is None or original.tag != 'C_SmartHub':
            raise ValueError('Missing native animal home scheduler registration')
        row = copy.deepcopy(original)
        for child in list(row):
            row.remove(child)
        selected_rows[key] = row
    keys = keys | homes.keys()
    return dict(root=root, area=area, keys=keys, entities=selected,
        rows=selected_rows, by_id=by_id,
        home_bound_to_source_habitat=home)


def horse_activity(mission, scheduler, smart_type):
    """Resolve an unrestricted native grazing leaf, not a campaign controller."""
    entities = {str(guid_value(e.get('EntityGuid'))): e for e in mission if e.get('EntityGuid')}
    rows = {r.get('EntityGuid'): r for r in scheduler.find('Schedulers')}
    candidates = []
    for row in scheduler.find('Schedulers'):
        for link in row.findall('Links/S_ActivityLink'):
            p = link.find('Parameters')
            target = entities.get(link.get('TargetGuid'))
            target_row = rows.get(link.get('TargetGuid'))
            if target is None or target.find('Properties') is None or p is None: continue
            if (target.find('Properties').get('guidSmartObjectType') != smart_type
                    or p.get('BehaviorName') != 'grazing' or link.get('PositioningDelegate', '0') != '0'
                    or p.get('TimeOfDayStart') != '0' or p.get('TimeOfDayEnd') != '1440'
                    or any(p.get(a) for a in ('LinkTag', 'RequiredRole', 'RequiredContext', 'ProvidedRole'))
                    or target.findall('EntityLinks/Link')
                    or target_row is None or target_row.tag != 'C_SmartHub'
                    or any(child.tag != 'Links' or len(child) for child in target_row)):
                continue
            candidates.append((link.get('TargetGuid'), target, link, target_row))
    if not candidates: raise ValueError('Missing native horse grazing contract')
    _, target, link, target_row = min(candidates, key=lambda x: x[0])
    return copy.deepcopy(target), copy.deepcopy(link), copy.deepcopy(target_row)
