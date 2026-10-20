"""Populate the selected source layout with native KCD2 animal contracts.

Existing wildlife and named service horses are retained. New ambient populations
are data driven; unsupported quest/master dependencies are explicitly reported.
"""
import copy
import hashlib
import json
import uuid
import xml.etree.ElementTree as E
import zipfile

from animal_population_sources import ANIMALS, FLOCKS, populations, transform, world
from animal_native_templates import habitat, horse_activity
from campaign_entity_links import append_links, guid_value, native_guid
from campaign_trigger_areas import read_areas
from character_person_world import source_home_geometry
from upgrade_map import read, xml
import wildlife

VERSION = 2
MANIFEST = 'gluemapper_animal_population.json'
LEVEL_FILES = (*wildlife.LEVEL_FILES, 'whdata_0')


def identity(text):
    return native_guid(int.from_bytes(hashlib.sha256(text.encode()).digest()[:8], 'little'))


def signature(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


def node_hash(node):
    return hashlib.sha256(E.canonicalize(E.tostring(node), strip_text=True).encode()).hexdigest()


def owned_state(files, guids):
    """Check only this converter's records; unrelated later stages may change."""
    mission = E.fromstring(files['objects_mission0.xml'])
    entities = {e.get('EntityGuid'): e for e in mission if e.get('EntityGuid') in guids}
    if len(entities) != len(guids): raise ValueError('Missing managed animal entity')
    numeric = {str(guid_value(g)) for g in guids}
    rows = {r.get('EntityGuid'): node_hash(r) for r in
            E.fromstring(files['tables/ai/scheduler.xml']).find('Schedulers') if r.get('EntityGuid') in numeric}
    shapes = {str(a.guid): signature((a.height, a.points)) for a in
              read_areas(files['triggerareas.fubar'])['areas'] if str(a.guid) in numeric}
    wh = E.fromstring(files['whdata_0'])
    souls = {s.findtext('EntityGuid'): node_hash(s) for s in wh.findall('SoulList/Souls/Soul')
             if s.findtext('EntityGuid') in guids}
    waiting = E.fromstring(files['waitinglinks.xml'])
    links = sorted([n.get('SourceId'), n.get('TargetId'), d.text or '']
                   for n in waiting.findall('WaitingLinks/WaitingLink')
                   if n.get('SourceId') in guids for d in n.findall('LinkDefinition'))
    return dict(entities={k: node_hash(e) for k, e in entities.items()}, rows=rows,
                shapes=shapes, souls=souls, links=links)


def validate(files, report):
    """No dangling generated IDs, delegates, areas or soul registrations."""
    mission = E.fromstring(files['objects_mission0.xml'])
    by_id = {e.get('EntityId'): e for e in mission if e.get('EntityId')}
    guids = {e.get('EntityGuid') for e in mission if e.get('EntityGuid')}
    if len(by_id) != sum(bool(e.get('EntityId')) for e in mission):
        raise ValueError('Duplicate destination entity IDs')
    if len(guids) != sum(bool(e.get('EntityGuid')) for e in mission):
        raise ValueError('Duplicate destination entity GUIDs')
    generated = set(report['owned_guids'])
    generated_numeric = {str(guid_value(g)) for g in generated}
    numeric = {str(guid_value(g)) for g in guids if g}
    scheduler_rows = list(E.fromstring(files['tables/ai/scheduler.xml']).find('Schedulers'))
    registered = {r.get('EntityGuid') for r in scheduler_rows}
    if len(registered) != len(scheduler_rows):
        raise ValueError('Duplicate destination scheduler registrations')
    shapes = {a.guid for a in read_areas(files['triggerareas.fubar'])['areas']}
    waiting = {(n.get('SourceId'), n.get('TargetId'), d.text or '')
               for n in E.fromstring(files['waitinglinks.xml']).findall('WaitingLinks/WaitingLink')
               for d in n.findall('LinkDefinition')}
    for e in mission:
        if e.get('EntityGuid') not in generated: continue
        if (e.get('EntityClass') in ('AnimalSpawner', 'Dog', 'Horse', 'SmartObjectHolder',
                                    'SchedulerHub', 'TriggerArea')
                and str(guid_value(e.get('EntityGuid'))) not in registered):
            raise ValueError('Missing animal scheduler registration: ' + e.get('Name', e.get('EntityGuid')))
        if e.get('EntityClass') == 'TriggerArea' and guid_value(e.get('EntityGuid')) not in shapes:
            raise ValueError('Animal habitat has no binary geometry')
        for link in e.findall('EntityLinks/Link'):
            target = by_id.get(link.get('TargetId'))
            if target is None or link.get('TargetGuid') != target.get('EntityGuid'):
                raise ValueError('Unresolved animal entity link')
            if (e.get('EntityGuid'), link.get('TargetGuid'), link.get('Name')) not in waiting:
                raise ValueError('Missing animal waiting link')
        for bound in e.findall('Area/Entities/Entity'):
            if bound.get('Id') != e.get('EntityId'):
                raise ValueError('Flock activation area retains a foreign entity ID')
    for row in scheduler_rows:
        if row.get('EntityGuid') not in generated_numeric: continue
        for link in row.findall('Links/S_ActivityLink'):
            if link.get('TargetGuid') not in numeric or link.get('PositioningDelegate', '0') not in numeric | {'0'}:
                raise ValueError('Unresolved animal scheduler dependency')
            if link.get('TargetGuid') not in registered:
                raise ValueError('Unregistered animal scheduler target: ' + link.get('TargetGuid'))
    if owned_state(files, generated) != report['owned_state']:
        raise ValueError('Managed animal records changed or are incomplete')


def native_catalog(target):
    with zipfile.ZipFile(target/'Data/Tables.pak') as z:
        souls = {s.get('soul_name'): s.get('soul_id') for s in
                 E.fromstring(read(z, 'Libs/Tables/rpg/soul__animal.xml')).iter('soul')}
        horse = E.fromstring(read(z, 'Libs/Tables/ai/smartEntity/SmartEntity__so_animalBehaviors_horse.xml'))
        horse_type = horse.find('.//SmartEntityTemplate').get('DatabaseId')
    worlds = []
    for level in ('trosecko', 'kutnohorsko'):
        with zipfile.ZipFile(target/'Data/Levels'/level/'level.pak') as z:
            worlds.append((level, E.fromstring(read(z, 'objects_mission0.xml')),
                           E.fromstring(read(z, 'tables/ai/scheduler.xml'))))
    return souls, horse_type, worlds


def choose_template(worlds, **selection):
    errors = []
    for level, mission, scheduler in worlds:
        try:
            template = habitat(mission, scheduler, **selection)
            template['world'] = level
            return template
        except ValueError as error:
            errors.append(str(error))
    raise ValueError('; '.join(errors))


def convert(files, source, target, profiles=()):
    files = dict(files)
    with zipfile.ZipFile(source/'Data/Levels/rataje/level.pak') as z:
        entities, active = world(z, profiles)
        sites, excluded = populations(entities, active)
    placed = [e for key, e in sorted(entities.items())
              if key in active and e.get('EntityClass') in (*FLOCKS, 'Dog', 'Horse')]
    dependencies = {l.get('TargetId') for e in placed for l in e.findall('EntityLinks/Link')}
    missing = dependencies - entities.keys()
    if missing: raise ValueError('Missing placed-animal dependencies: ' + ', '.join(sorted(missing)))
    inputs = signature(dict(version=VERSION, profiles=list(profiles), sites=sites,
        placed=[E.tostring(transform(e, entities)).decode() for e in placed],
        dependencies=[E.tostring(transform(entities[k], entities)).decode() for k in sorted(dependencies)]))
    if MANIFEST in files:
        report = json.loads(files[MANIFEST])
        if report.get('version') != VERSION or report.get('source_signature') != inputs:
            raise ValueError('Animal population inputs changed; rebuild this stage from its baseline')
        validate(files, report)
        return files, report
    souls, horse_type, native = native_catalog(target)
    mission = E.fromstring(files['objects_mission0.xml'])
    before_guids = {e.get('EntityGuid') for e in mission}
    by_name = {e.get('Name'): e for e in mission}
    additions, preserved = [], []
    pending = [item for item in excluded if item.get('requires_adapter')]
    templates = {}
    for site in sites:
        existing = by_name.get('gm_wildlife_' + site['guid'] + '_spawn')
        if existing is not None:
            p = existing.find('Properties')
            position = tuple(map(float, existing.get('Pos').split(',')))
            if (existing.get('EntityClass') != 'AnimalSpawner' or p is None
                    or p.get('guidSoul') != souls[ANIMALS[site['species']]]
                    or p.get('AnimalCount') != str(site['count'])
                    or max(abs(a-b) for a, b in zip(position, site['position'])) > 1e-4):
                raise ValueError('Existing animal population differs from source: ' + site['name'])
            preserved.append(site)
            continue
        species = site['species']
        if species not in templates:
            templates[species] = choose_template(native, soul=souls[ANIMALS[species]])
        additions.append(site)
    if additions:
        files, records = wildlife.apply(files, additions, templates)
    else: records = []
    # Direct animals retain their source identity and position. Guard dogs need
    # an authored territory; master-dependent dogs need the missing master
    # adapter instead of silently becoming unrelated ambient dogs.
    mission = E.fromstring(files['objects_mission0.xml'])
    resident = {e.get('EntityGuid'): e for e in mission}
    names = {e.get('Name'): e for e in mission}
    dogs, horses, flocks, existing_actors = [], [], [], []
    for key in sorted(active, key=int):
        original = entities[key]
        cls = original.get('EntityClass')
        if cls not in (*FLOCKS, 'Dog', 'Horse'): continue
        actor = transform(original, entities)
        guid = native_guid(int(actor.get('EntityGuid'), 16))
        existing = resident.get(guid)
        if existing is not None:
            if existing.get('EntityClass') != cls: raise ValueError('Animal identity collides with another class')
            existing_actors.append(dict(name=actor.get('Name'), entity_guid=guid, source_class=cls))
            continue
        if actor.get('Name') in names:
            raise ValueError('Animal name collides with another identity: ' + actor.get('Name'))
        if cls in FLOCKS:
            flocks.append(actor);continue
        links = original.findall('EntityLinks/Link')
        if cls == 'Horse':
            # Sales and quest-controlled horses must keep their service bindings.
            if any(l.get('Name') not in ('horseHome', 'horsePoint', 'standPoint') for l in links):
                pending.append(dict(name=actor.get('Name'), source_id=key, species=cls,
                    reason='source horse service/quest links require their owning adapter',
                    links=[l.attrib for l in links]));continue
            horses.append((actor, links));continue
        homes = [l for l in links if l.get('Name') in ('', 'Home')]
        if any(l.get('Name') == 'initMaster' for l in links) or len(homes) != 1:
            pending.append(dict(name=actor.get('Name'), source_id=key, species=cls,
                reason='source dog master or home contract requires its owning adapter',
                links=[l.attrib for l in links]));continue
        home = entities.get(homes[0].get('TargetId'))
        if home is None: raise ValueError('Missing dog territory: ' + actor.get('Name'))
        if home.find('Area/Points') is None:
            pending.append(dict(name=actor.get('Name'), source_id=key, species=cls,
                reason='source dog home is not a directly authored polygon'));continue
        area = source_home_geometry(transform(home, entities))
        dogs.append(dict(guid=original.get('EntityGuid'), name=actor.get('Name'), species='Dog',
            position=tuple(map(float, actor.get('Pos').split(','))), count=1, radius=0,
            respawn_days=0, actor=True, rotation=actor.get('Rotate'), scale=actor.get('Scale'),
            area=dict(height=area.height, points=area.points), source_id=key))
    if dogs:
        dog_template = choose_template(native, actor_class='Dog')
        files, dog_records = wildlife.apply(files, dogs, {'Dog': dog_template})
    else: dog_records = []
    files, flock_records = place_flocks(files, flocks, target)
    files, horse_records = place_horses(files, horses, entities, native, horse_type)
    wh = E.fromstring(files['whdata_0'])
    soul_list = wh.find('SoulList/Souls')
    if soul_list is None: raise ValueError('Destination animal soul registry is missing')
    for actor in [*dogs, *horse_records]:
        entity_guid = native_guid(int(actor['guid'], 16))
        if any(s.findtext('EntityGuid') == entity_guid or s.findtext('Name') == actor['name'] for s in soul_list):
            raise ValueError('Animal soul already registered: ' + actor['name'])
        row = E.SubElement(soul_list, 'Soul', version='8')
        for name, value in dict(Name=actor['name'], SharedSoulGuid=souls[ANIMALS[actor['species']]],
                Guid=str(uuid.uuid5(uuid.NAMESPACE_URL, 'gluemapper/animal/' + actor['guid'])),
                EntityGuid=entity_guid).items(): E.SubElement(row, name).text = value
    files['whdata_0'] = xml(wh)
    owned = sorted({e.get('EntityGuid') for e in E.fromstring(files['objects_mission0.xml'])} - before_guids)
    report = dict(version=VERSION, source_signature=inputs, profiles=list(profiles),
        populations_added=records, populations_preserved=preserved, dogs=dog_records,
        horses=horse_records, flocks=flock_records, existing_actors=existing_actors,
        pending=pending, excluded=excluded, owned_guids=owned, runtime_verified=False,
        complete=not pending)
    report['owned_state'] = owned_state(files, set(owned))
    validate(files, report)
    files[MANIFEST] = json.dumps(report, indent=2).encode()
    return files, report


def place_flocks(files, actors, target):
    mission = E.fromstring(files['objects_mission0.xml'])
    next_id = max(int(e.get('EntityId', '0')) for e in mission) + 1
    report = []
    with zipfile.ZipFile(target/'Data/Scripts.pak') as scripts:
        for source in actors:
            cls = source.get('EntityClass')
            # Default models, smart-object types, sounds and animation sets
            # must come from the target class, not serialized KCD1 properties.
            read(scripts, 'Scripts/Entities/Boids/' + cls + '.lua')
            e = E.Element('Entity', Name=source.get('Name'), EntityClass=cls,
                EntityId=str(next_id), EntityGuid=native_guid(int(source.get('EntityGuid'), 16)),
                **{a: source.get(a) for a in ('Pos', 'Rotate', 'Scale')})
            next_id += 1
            props = E.SubElement(e, 'Properties')
            old = source.find('Properties')
            count = old.find('Boid').get('nCount')
            if not count.isdecimal(): raise ValueError('Invalid source flock count')
            E.SubElement(props, 'Boid', nCount=count)
            options = old.find('Options')
            radius = float(options.get('Radius'))
            if not 0 < radius < float('inf'): raise ValueError('Invalid source flock radius')
            E.SubElement(props, 'Options', Radius=str(radius), bActivate=options.get('bActivate', '1'))
            # Movement, animations and models retain KCD2 class defaults.
            area = copy.deepcopy(source.find('Area'))
            if area is None or area.find('Entities') is None: raise ValueError('Missing flock activation area')
            if len(area.find('Entities')) != 1: raise ValueError('Unsupported shared flock activation area')
            area.find('Entities/Entity').set('Id', e.get('EntityId'))
            e.append(area);mission.append(e)
            report.append(dict(name=e.get('Name'), species=cls, count=int(count),
                position=e.get('Pos'), native_class=cls, radius=radius))
    result = dict(files);result['objects_mission0.xml'] = xml(mission)
    return result, report


def place_horses(files, actors, source_entities, worlds, horse_type):
    if not actors: return dict(files), []
    mission = E.fromstring(files['objects_mission0.xml'])
    scheduler = E.fromstring(files['tables/ai/scheduler.xml'])
    holder, activity, holder_row = horse_activity(worlds[0][1], worlds[0][2], horse_type)
    next_id = max(int(e.get('EntityId', '0')) for e in mission) + 1
    links, report = [], []
    for source, original_links in actors:
        guid = native_guid(int(source.get('EntityGuid'), 16))
        e = E.SubElement(mission, 'Entity', Name=source.get('Name'), EntityClass='Horse',
            EntityId=str(next_id), EntityGuid=guid, **{a:source.get(a) for a in ('Pos','Rotate','Scale')})
        next_id += 1
        # Unowned placement/point jobs have no imported household. Preserve the
        # native horse class; don't bind it to a random Trosky household.
        E.SubElement(e, 'Properties', bWH_RequiresHome='0',
            bMountIsLegal=source.find('Properties').get('bMountIsLegal', '0'),
            bNotPlayerMountable=source.find('Properties').get('bNotPlayerMountable', '0'))
        row = E.SubElement(scheduler.find('Schedulers'), 'C_SmartHub', EntityGuid=str(guid_value(guid)),
                           IgnoreDeadEnds='false', StupidHub='false')
        jobs = E.SubElement(row, 'Links')
        destinations = [source_entities[l.get('TargetId')] for l in original_links]
        if any(p.get('EntityClass') not in ('TagPoint', 'SmartObjectHolder') for p in destinations):
            raise ValueError('Horse destination is not an authored point: ' + source.get('Name'))
        if not destinations: destinations = [source]
        for index, destination in enumerate(destinations):
            point = transform(destination, source_entities)
            native = copy.deepcopy(holder)
            for a in ('Prefab','EditorLayer','Layer','ParentId','ParentGuid','Scale'): native.attrib.pop(a, None)
            target_guid = identity('animal-horse-work/' + guid + '/' + str(index))
            native.attrib.update(EntityId=str(next_id), EntityGuid=target_guid,
                Name='gm_animal_horse_work_' + target_guid, Pos=point.get('Pos'), Rotate=point.get('Rotate'))
            next_id += 1;mission.append(native)
            # Native grazing leaves still have an empty compiled C_SmartHub.
            # Without it, the incoming activity resolves to a null node in retail.
            registration = copy.deepcopy(holder_row)
            registration.set('EntityGuid', str(guid_value(target_guid)))
            if 'Position' in registration.attrib:
                registration.set('Position', native.get('Pos'))
            scheduler.find('Schedulers').append(registration)
            link = copy.deepcopy(activity);link.set('TargetGuid', str(guid_value(target_guid)));jobs.append(link)
            container = e.find('EntityLinks')
            if container is None: container = E.SubElement(e, 'EntityLinks')
            E.SubElement(container, 'Link', Name='_,grazing', TargetId=native.get('EntityId'), TargetGuid=target_guid)
            links.append((guid, target_guid, '_,grazing'))
        report.append(dict(name=source.get('Name'), guid=source.get('EntityGuid'), species='Horse',
            position=source.get('Pos'), native_behavior='grazing', destinations=len(destinations)))
    result = dict(files)
    result.update({'objects_mission0.xml':xml(mission), 'tables/ai/scheduler.xml':xml(scheduler),
                   'waitinglinks.xml':append_links(files['waitinglinks.xml'], links)})
    return result, report
