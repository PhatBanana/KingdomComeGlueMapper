"""Convert authored KCD1 wildlife sites to native KCD2 spawner networks."""
import copy
import hashlib
import math
import re
import xml.etree.ElementTree as ET
import zipfile

from campaign_entity_links import append_links, guid_value, native_guid
from campaign_trigger_areas import TriggerArea, read_areas, write_areas
from upgrade_map import read, xml

LEVEL_FILES = ('objects_mission0.xml', 'tables/ai/scheduler.xml', 'triggerareas.fubar', 'waitinglinks.xml')

SPECIES = {'Boar': 'animal_boar', 'RedDeer': 'animal_red_deer_stag',
           'DeerDoe': 'animal_red_deer_doe', 'RoeBuck': 'animal_roe_deer_buck',
           'Hare': 'animal_hare'}
PATTERN = re.compile(r'animalSpawn\[amount\((\d+)\),class\((\w+)\),'
                     r'radius\(([\d.]+)\),respawn\(([\d.]+)([hd])\)\]')


def source_sites(mission):
    """Use self-linked proximity spawners, not a second regional population.

    KCD1 so_animal_proximity searches its own animalSpawn graph edges.
    Regional links to the same holder are retained in the audit, not summed.
    Non-self-only populations and dynamic hare regions require separate adapters.
    """
    sites, deferred = [], []
    for entity in mission:
        for link in entity.findall('EntityLinks/Link'):
            text = link.get('Name', '').strip()
            if not text.startswith('animalSpawn['):
                continue
            species_match = re.search(r'class\((\w+)\)', text)
            if species_match and species_match.group(1) not in SPECIES:
                deferred.append(dict(owner=entity.get('Name'), target=link.get('TargetId'), definition=text))
                continue
            match = PATTERN.fullmatch(text)
            if not match:
                raise ValueError('Unsupported animal spawn instruction: ' + text)
            count, species, radius, respawn, unit = match.groups()
            if species not in SPECIES or link.get('TargetId') != entity.get('EntityId'):
                deferred.append(dict(owner=entity.get('Name'), target=link.get('TargetId'), definition=text))
                continue
            pos = tuple(map(float, entity.get('Pos').split(',')))
            if len(pos) != 3 or not all(map(math.isfinite, pos)) or int(count) < 1 or float(radius) <= 0:
                raise ValueError('Invalid wildlife site')
            sites.append(dict(guid=entity.get('EntityGuid'), name=entity.get('Name'),
                              species=species, position=pos, count=int(count), radius=float(radius),
                              respawn_days=float(respawn) / (24 if unit == 'h' else 1)))
    if len({s['guid'] for s in sites}) != len(sites):
        raise ValueError('Ambiguous source self-linked animal population')
    return sites, deferred


def native_template(mission, scheduler, soul):
    """Choose the smallest self-contained native activity network for a species."""
    entities = {str(guid_value(e.get('EntityGuid'))): e for e in mission if e.get('EntityGuid')}
    rows = {r.get('EntityGuid'): r for r in scheduler.find('Schedulers')}
    by_id = {e.get('EntityId'): k for k, e in entities.items()}
    candidates = []
    allowed = {'AnimalSpawner', 'SmartObjectHolder', 'SchedulerHub', 'TagPoint', 'TriggerArea'}
    for key, entity in entities.items():
        if entity.get('EntityClass') != 'AnimalSpawner' or entity.find('Properties').get('guidSoul') != soul:
            continue
        todo, seen, bad = [key], set(), False
        while todo and len(seen) < 32:
            k = todo.pop()
            if k == '0' or k in seen:
                continue
            seen.add(k)
            e, row = entities.get(k), rows.get(k)
            if e is None and row is None:
                bad = True; break
            if e is not None:
                if e.get('EntityClass') not in allowed or (k != key and e.get('EntityClass') == 'AnimalSpawner'):
                    bad = True; break
                for link in e.findall('EntityLinks/Link'):
                    target = by_id.get(link.get('TargetId'))
                    # Optimized-away scheduler hubs survive in compiled rows.
                    if target is None:
                        if link.get('Name') == '_':
                            continue
                        bad = True; break
                    todo.append(target)
            if row is not None:
                for link in row.findall('Links/S_ActivityLink'):
                    todo.extend((link.get('TargetGuid'), link.get('PositioningDelegate', '0')))
        areas = [k for k in seen if k in entities and entities[k].get('EntityClass') == 'TriggerArea']
        if not bad and not todo and len(areas) == 1 and key in rows:
            candidates.append((len(seen), key, seen, areas[0]))
    if not candidates:
        raise ValueError('No bounded native wildlife template for soul ' + soul)
    _, key, selected, area = min(candidates, key=lambda c: (c[0], c[1]))
    return dict(root=key, area=area, entities={k: entities[k] for k in selected if k in entities},
                rows={k: rows[k] for k in selected if k in rows}, keys=selected, by_id=by_id)


def hare_sites(mission, height):
    """Preserve source dynamic-area polygons, with KCD2 population scheduling.

    KCD1 sa_forest and sa_dynamicSpawnAnimals reference final/dynamic.xml,
    whose default is eight hares, overridden by Script Misc 'hares:N'.
    KCD2 distributes this population in the region instead of KCD1's
    player-centred 45m spawning; this is a deliberate native-system adaptation.
    """
    from character_person_world import source_home_geometry
    templates = {'40b53966-60ca-d312-d919-54b6c741a2b8', '49aa1edc-0a0e-4a07-84f8-f3c08ccc2a09'}
    sites = []
    for e in mission:
        props = e.find('Properties')
        if props is None or props.get('guidSmartAreaTemplate') not in templates:
            continue
        area = source_home_geometry(e)
        script = props.find('Script')
        override = re.search(r'(?:^|\|)hares:(\d+)(?:\||$)', script.get('Misc', '') if script is not None else '')
        count = int(override.group(1)) if override else 8
        if count == 0: continue
        points = area.points
        low, high = min(p[1] for p in points), max(p[1] for p in points)
        candidates = []
        for i in range(1, 20):
            y = low + (high-low)*i/20
            crossings = sorted(a[0]+(y-a[1])*(b[0]-a[0])/(b[1]-a[1])
                               for a,b in zip(points, points[1:]+points[:1]) if (a[1]>y)!=(b[1]>y))
            for a,b in zip(crossings[::2], crossings[1::2]):
                x=(a+b)/2;z=height(x,y)
                if min(p[2] for p in points) <= z <= max(p[2] for p in points)+area.height:
                    candidates.append((b-a,x,y,z))
        if not candidates: raise ValueError('No terrain-grounded interior point for '+e.get('Name'))
        _,x,y,z=max(candidates)
        sites.append(dict(guid=e.get('EntityGuid'), name=e.get('Name'), species='Hare', position=(x,y,z),
                          count=count, radius=45., respawn_days=1/3,
                          area=dict(height=area.height, points=area.points)))
    return sites


def apply(files, sites, templates):
    """Merge native entities, compiled activities, areas and persistent links."""
    files = dict(files)
    mission = ET.fromstring(files['objects_mission0.xml'])
    scheduler = ET.fromstring(files['tables/ai/scheduler.xml'])
    shapes = read_areas(files['triggerareas.fubar'])
    rows = scheduler.find('Schedulers')
    occupied = {e.get('EntityGuid') for e in mission}
    next_id = max(int(e.get('EntityId', '0')) for e in mission) + 1
    links, report = [], []
    for site in sites:
        template = templates[site['species']]
        keys = sorted(template['keys'])
        identities = {k: native_guid(int.from_bytes(hashlib.sha256(
            ('wildlife/' + site['guid'] + '/' + k).encode()).digest()[:8], 'little')) for k in keys}
        if occupied.intersection(identities.values()):
            raise ValueError('Wildlife site already installed: ' + site['name'])
        occupied.update(identities.values())
        ids = {k: str(next_id + i) for i, k in enumerate(keys)}
        next_id += len(keys)
        x, y, z = site['position']
        radius = site['radius']
        for key in keys:
            original = template['entities'].get(key)
            entity = copy.deepcopy(original) if original is not None else ET.Element('Entity', EntityClass='SchedulerHub')
            for attr in ('Prefab', 'EditorLayer', 'ParentId', 'Rotate', 'Scale'):
                entity.attrib.pop(attr, None)
            entity.set('Name', 'gm_wildlife_' + site['guid'] + '_' + ('spawn' if key == template['root'] else key))
            entity.set('EntityGuid', identities[key]);entity.set('EntityId', ids[key])
            entity.set('Pos', f'{x},{y},{z}')
            old_links = entity.find('EntityLinks')
            if old_links is not None: entity.remove(old_links)
            new_links = ET.SubElement(entity, 'EntityLinks')
            if original is not None:
                for link in original.findall('EntityLinks/Link'):
                    target = template['by_id'].get(link.get('TargetId'))
                    if target not in identities:
                        if link.get('Name') == '_': continue  # compiled scheduler is authoritative
                        raise ValueError('Unresolved wildlife editor link')
                    definition = link.get('Name')
                    ET.SubElement(new_links, 'Link', Name=definition, TargetId=ids[target], TargetGuid=identities[target])
                    links.append((identities[key], identities[target], definition))
            if key == template['root']:
                props = entity.find('Properties')
                props.set('AnimalCount', str(site['count']))
                props.set('RespawnDays', format(site['respawn_days'], '.9g'))
            mission.append(entity)
            if key in template['rows']:
                row = copy.deepcopy(template['rows'][key]);row.set('EntityGuid', str(guid_value(identities[key])))
                for link in row.findall('Links/S_ActivityLink'):
                    for attr in ('TargetGuid', 'PositioningDelegate'):
                        old = link.get(attr, '0')
                        if old != '0': link.set(attr, str(guid_value(identities[old])))
                rows.append(row)
        # KCD1 specifies a spawn disc, not a KCD2 polygon. Inscribe the polygon
        # in the original radius; vertical clearance includes uneven ground.
        points = tuple((x + radius * math.cos(i * math.tau / 24),
                        y + radius * math.sin(i * math.tau / 24), z - 5) for i in range(24))
        area_height = 10
        if 'area' in site:
            points, area_height = site['area']['points'], site['area']['height']
        shapes['areas'].append(TriggerArea(guid_value(identities[template['area']]), area_height, points))
        report.append(dict(**site, spawn_name='gm_wildlife_' + site['guid'] + '_spawn',
                           native_template_guid=template['root'], entities=len(keys),
                           activity_rows=len(template['rows']), runtime_verified=False,
                           habitat='original dynamic-area polygon' if 'area' in site else 'source spawn radius'))
    files['objects_mission0.xml'] = xml(mission)
    files['tables/ai/scheduler.xml'] = xml(scheduler)
    files['triggerareas.fubar'] = write_areas(shapes['areas'], shapes['export_version'])
    files['waitinglinks.xml'] = append_links(files.get('waitinglinks.xml'), links)
    return files, report


def convert_level(files, source, target, height, species=None, limit=0):
    """Shared entry point for staged probes and normal world builds."""
    with zipfile.ZipFile(source / 'Data/Levels/rataje/level.pak') as z:
        mission = ET.fromstring(read(z, 'objects_mission0.xml'))
        sites, deferred = source_sites(mission)
        sites += hare_sites(mission, height)
    with zipfile.ZipFile(target / 'Data/Tables.pak') as z:
        souls = {e.get('soul_name'): e.get('soul_id') for e in
                 ET.fromstring(read(z, 'Libs/Tables/rpg/soul__animal.xml')).iter() if e.get('soul_name')}
    selected = [s for s in sites if not species or s['species'] == species]
    selected.sort(key=lambda s: sum((v-t)**2 for v,t in zip(s['position'][:2], (923,3358))))
    if limit: selected = selected[:limit]
    if not selected: raise ValueError('No source wildlife sites selected')
    with zipfile.ZipFile(target / 'Data/Levels/trosecko/level.pak') as z:
        native = ET.fromstring(read(z, 'objects_mission0.xml'))
        scheduler = ET.fromstring(read(z, 'tables/ai/scheduler.xml'))
        templates = {s: native_template(native, scheduler, souls[SPECIES[s]]) for s in {a['species'] for a in selected}}
    changed, report = apply(files, selected, templates)
    return changed, dict(sites=report, source_sites=len(sites), deferred_links=deferred,
                         native_models=True, runtime_verified=False,
                         limitations=['Hares use native region population instead of player-centred 45m spawning',
                                      'Non-self-linked regional populations deferred',
                                      'Fractional RespawnDays runtime semantics unverified'])
