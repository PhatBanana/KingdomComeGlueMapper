"""Source-person AI contracts, explicit native adapters, and coverage receipts.

Identity, appearance, and a brain ID alone are not a complete NPC import. Keep
the original record and every authored link available to world/activity adapters.
Unsupported dependencies remain in the receipt instead of silently disappearing.
"""
import copy
import json
import math
import xml.etree.ElementTree as ET


# Names are verified against the shipped Storm abilities operations. Combat
# level is intentionally absent: KCD1's integer level is not KCD2's 0..1 factor.
STATS = {'str': 'strength', 'agi': 'agility', 'vit': 'vitality', 'spc': 'speech',
         'vision': 'vision', 'hearing': 'hearing', 'courage': 'courage',
         'charisma': 'charisma', 'shadiness': 'shadiness'}
PROPERTIES = ('bWH_PerceptorObject', 'bWH_PerceptibleObject', 'bWH_ListenerObject')
BRAIN_ADAPTERS = {'npc_daycycle': 'npc_basic'}
FACTION_PATH = 'Libs/Tables/rpg/FactionTree__gluemapper_people.xml'


def register_factions(files, ai):
    from character_factions import register
    if 'faction_graph' not in ai:
        raise ValueError('Recapture source AI: faction and superfaction catalogs are required')
    return register(files, ai['faction_graph'])


def capture_person_ai(tables, soul, actor, instance, entities, link_index=None):
    links = capture_person_links(actor, entities, link_index)
    brain = tables.row('ai/brain', 'brain_id', soul['brain_id'])
    social = tables.row('rpg/social_class', 'social_class_id', soul['social_class_id'])
    from character_factions import capture
    faction_graph = capture(tables, soul['faction'])
    schedule = []
    for index in range(9):
        activity, clock = soul.get(f'activity_{index}'), soul.get(f'time_{index}')
        if not activity and not clock: continue
        if not activity or not clock: raise ValueError('Incomplete source daycycle entry')
        hour, minute = map(int, clock.split(':'))
        if not (0 <= hour < 24 and 0 <= minute < 60): raise ValueError('Invalid daycycle time')
        schedule.append(dict(activity=activity, start_minute=hour * 60 + minute, status='pending'))
    return dict(source_brain=brain, source_social_class=social, source_factions=[faction_graph['faction']],
                faction_graph=faction_graph,
                source_soul=dict(soul), source_instance=ET.tostring(instance, encoding='unicode'),
                source_properties=ET.tostring(actor.find('Properties'), encoding='unicode')
                    if actor.find('Properties') is not None else None,
                links=links, schedule=schedule)


def index_person_links(entities):
    """Build once per source world; retain every candidate for ambiguity checks."""
    by_id, by_guid = {}, {}
    for entity in entities:
        if entity.get('EntityId'):
            by_id.setdefault(entity.get('EntityId'), []).append(entity)
        if entity.get('EntityGuid'):
            by_guid.setdefault(entity.get('EntityGuid').lower(), []).append(entity)
    return by_id, by_guid


def capture_person_links(actor, entities, link_index=None):
    """Resolve authored home/work references without choosing a layer by order."""
    by_id, by_guid = link_index if link_index is not None else index_person_links(entities)
    links = []
    for link in actor.findall('EntityLinks/Link'):
        guid, eid = link.get('TargetGuid'), link.get('TargetId')
        matches = (by_guid.get(guid.lower(), []) if guid not in (None, '', '0')
                   else by_id.get(eid, []) if eid not in (None, '', '0') else [])
        if len(matches) != 1:
            raise ValueError('Missing or ambiguous source person link: ' + repr(link.attrib))
        target = matches[0]
        if eid not in (None, '', '0') and target.get('EntityId') != eid:
            raise ValueError('Source person link GUID and ID disagree: ' + repr(link.attrib))
        links.append(dict(label=link.get('Name'), target=dict(target.attrib),
                          source_xml=ET.tostring(target, encoding='unicode'), status='pending'))
    return links


def native_brain_and_class(ai, brains, classes):
    name = ai['source_brain']['brain_name']
    target_name = BRAIN_ADAPTERS.get(name)
    if target_name is None:
        raise ValueError('No native person brain adapter for ' + name)
    matches = [e for e in brains.iter('brain') if e.get('brain_name') == target_name]
    social_name = ai['source_social_class']['social_class_name']
    socials = [e for e in classes.iter('social_class') if e.get('social_class_name') == social_name]
    source_role = ai['source_social_class'].get('soul_crime_role_id')
    if source_role is not None and len(socials) == 1 and socials[0].get('soul_crime_role_id') != source_role:
        # KCD2 split the former soldier authority into soldier and
        # soldier_crimeAuthority. Retain the profession AND crime role;
        # accepting the same display name alone silently removes policing.
        socials = [e for e in classes.iter('social_class')
                   if e.get('social_class_name', '').startswith(social_name + '_')
                   and e.get('soul_crime_role_id') == source_role]
    if len(matches) != 1 or len(socials) != 1:
        raise ValueError('Missing/ambiguous native brain or social class contract')
    return matches[0].get('brain_id'), socials[0].get('social_class_id')


def stat_operations(soul):
    operations = []
    for old, new in STATS.items():
        value = soul.get(old)
        if value in ('', None): continue
        if not math.isfinite(float(value)) or float(value) < 0:
            raise ValueError('Invalid source NPC stat: ' + old)
        operations.append(('setAttribute', dict(stat=new, value=value)))
    return operations


def apply_person_properties(npc, actor):
    source = actor.find('Properties')
    if source is None: return
    props = ET.SubElement(npc, 'Properties')
    for name in PROPERTIES:
        value = source.get(name)
        if value is not None:
            if value not in ('0', '1', 'true', 'false'):
                raise ValueError('Invalid source perception flag: ' + name)
            props.set(name, value)
    # Legacy bIdleUntilFirstPatch and quest script contexts are NOT copied into
    # KCD2. They require converted quest ownership, not a permanently idle actor.


def receipt(person, target_soul, namespace):
    report = copy.deepcopy(person['ai'])
    coverage = {}
    for field, value in person['soul'].items():
        status, adapter = 'pending', None
        if value in ('', None): status = 'unset_in_source'
        elif field in STATS: status, adapter = 'mapped', 'Storm.setAttribute:' + STATS[field]
        elif field in ('soul_id', 'soul_name', 'xp_multiplier', 'digestion_multiplier', 'initial_clothing_dirt'):
            status, adapter = 'mapped', 'native soul record'
        elif field == 'brain_id': status, adapter = 'mapped', 'npc_daycycle -> npc_basic; daycycle activities pending'
        elif field == 'social_class_id': status, adapter = 'mapped', 'native profession and source crime role'
        elif field == 'faction': status, adapter = 'partial', 'native faction/superfaction hierarchy, signed directional relations and player reputation'
        elif field.startswith('character_') or field in ('initial_clothing_preset_id', 'soul_archetype_id'):
            status, adapter = 'delegated', 'character_person_appearance and character_source_clothing receipts'
        elif field in ('computer_name', 'timestamp', 'level_name'):
            status, adapter = 'source_metadata', 'retained in this receipt'
        coverage[field] = dict(status=status, adapter=adapter, source_value=value)
    report.update(person=person['name'], namespace=namespace,
        native_brain=target_soul.get('brain_id'), native_social_class=target_soul.get('social_class_id'),
        native_faction=target_soul.get('factionName'),
        mapped_stats=STATS, perception_properties=PROPERTIES,
        appearance='character_person_appearance', equipment='character_source_clothing',
        field_coverage=coverage, complete=False, runtime_verified=False,
        pending=['location and faction UI; native player outgoing group relationships', 'daycycle and home/work graph',
                 'combat-level and skills scale conversion', 'source inventory beyond outfit',
                 'quest contexts and original dialogue/voice', 'save/load and reaction verification'])
    return json.dumps(report, indent=2, ensure_ascii=True).encode('utf-8')
