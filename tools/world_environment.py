"""Import initial-world environmental entities with native dependency validation.

No KCD1 audio banks, particle libraries, gameplay scripts or AI trigger polygons
are installed. Audio area boundaries use the engine's AreaShape XML contract.
"""
import copy
from collections import Counter
from pathlib import Path
import xml.etree.ElementTree as ET
import zipfile

from entity_visuals import initial_layer, world_transform
from upgrade_map import read, xml
from environment_audio import RETIRED, aliases as native_aliases

CLASSES = {'ParticleEffect', 'FogVolume', 'AudioAreaAmbience', 'AudioAreaRandom',
           'AudioAreaEntity', 'AudioTriggerSpot'}
CONTROL_TYPES = {'audioTrigger': 'ATLTrigger', 'audioRTPC': 'ATLRtpc',
                 'audioEnvironment': 'ATLEnvironment'}


def particle_count_limit(props):
    """Bound the two legacy effects observed overflowing KCD2's helper array.

    Retain their native effect, size, lifetime and activity. This is a density
    reduction, not a general performance or visual-parity claim.
    """
    if props.get('ParticleEffect', '').lower() not in {
            'wh_vranik.vranik.fire_c_vranik', 'wh_vranik.vranik.fire_e'}:
        return None
    before = float(props.get('CountScale', '1'))
    after = min(before, .25)
    if after == before:
        return None
    props.set('CountScale', format(after, '.9g'))
    return dict(before=before, after=after, reason='native_helper_array_limit')


def inventory(source):
    entities, active = {}, set()
    with zipfile.ZipFile(Path(source)/'Data/Levels/rataje/level.pak') as archive:
        # Mission exports take precedence over layer duplicates.
        names = sorted(archive.namelist(), key=lambda n: n.lower() != 'objects_mission0.xml')
        for name in names:
            main = name.lower() == 'objects_mission0.xml'
            if not main and not (name.lower().startswith('layers/') and name.lower().endswith('.xml')):
                continue
            for entity in ET.fromstring(read(archive, name)).iter('Entity'):
                key = entity.get('EntityId')
                if not key: continue
                entities.setdefault(key, entity)
                if (main and not entity.get('Layer')) or initial_layer(entity.get('Layer', '')):
                    active.add(key)
    return entities, active


def native_catalog(target):
    effects, controls = {}, {}
    def particle(node, prefix):
        name = prefix + '.' + node.get('Name')
        effects[name.lower()] = name
        for child in node.findall('Childs/Particles'): particle(child, name)
    paths = [Path(target)/'Data/GameData.pak', Path(target)/'Data/IPL_GameData.pak']
    for path in paths:
        if not path.exists(): continue
        with zipfile.ZipFile(path) as archive:
            for name in archive.namelist():
                lower = name.lower()
                if not lower.endswith('.xml'): continue
                if lower.startswith('libs/particles/'):
                    root = ET.fromstring(read(archive, name))
                    for node in root.findall('Particles'): particle(node, root.get('Name'))
                elif lower.startswith('libs/gameaudio/'):
                    for node in ET.fromstring(read(archive, name)).iter():
                        if node.tag in CONTROL_TYPES.values() and node.get('atl_name'):
                            controls[(node.tag, node.get('atl_name').lower())] = node.get('atl_name')
    if not effects or not controls: raise ValueError('Native environmental catalog is missing')
    return effects, controls


def control_type(attribute):
    return next((kind for prefix, kind in CONTROL_TYPES.items()
                 if attribute.lower().startswith(prefix.lower())), None)


def convert(mission, entities, active, effects, controls, guid, aliases=None):
    """Return an additive mission patch and a per-source coverage receipt.

    Aliases are explicit (kind, source-name) -> native-name mappings. Unknown
    dependencies fail closed per entity and remain visible in the receipt.
    """
    aliases = aliases or {}
    root = ET.fromstring(mission)
    if any(e.get('Name', '').startswith('gm_environment_') for e in root):
        raise ValueError('Environment conversion already installed')
    counter = max((int(e.get('EntityId', '0')) for e in root), default=0)+1
    def allocate_id():
        nonlocal counter
        # CryEngine reserves 0x7777 for the local player. Taking this ID
        # prevents Actor.CreateActor during SinglePlayer.OnClientConnect.
        if counter == 0x7777:
            counter += 1
        if counter >= 65534:
            raise ValueError('Environmental entities exceed available static entity IDs')
        result = str(counter)
        counter += 1
        return result
    selected, records = {}, []
    for key, original in entities.items():
        cls = original.get('EntityClass')
        if cls not in CLASSES: continue
        record = dict(source_id=key, source_name=original.get('Name'), entity_class=cls,
                      source_layer=original.get('Layer', ''), status='deferred', mappings=[], retired_controls=[])
        records.append(record)
        if key not in active:
            record['reason'] = 'inactive_layer'; continue
        entity = copy.deepcopy(original)
        props = entity.find('Properties')
        errors = []
        if props is None:
            record['reason'] = 'missing_properties'; continue
        if cls == 'ParticleEffect':
            effect = props.get('ParticleEffect', '')
            if effect.lower() not in effects:
                record['reason'] = 'empty_effect' if not effect else 'missing_native_effect'
                record['dependency'] = effect; continue
            props.set('ParticleEffect', effects[effect.lower()])
            adjustment = particle_count_limit(props)
            if adjustment:
                record['particle_count_adjustment'] = adjustment
        for node in entity.iter():
            for attribute, value in list(node.attrib.items()):
                kind = control_type(attribute)
                if not kind or not value: continue
                if value.lower() in RETIRED.get(kind, set()):
                    record['retired_controls'].append(dict(kind=kind, name=value))
                    node.set(attribute, '')
                    continue
                replacement = aliases.get((kind, value.lower()), value)
                native = controls.get((kind, replacement.lower()))
                if native is None:
                    errors.append(dict(kind=kind, name=value)); continue
                node.set(attribute, native)
                if native != value: record['mappings'].append(dict(source=value, target=native, kind=kind))
        if errors:
            record.update(reason='missing_native_audio_controls', dependencies=errors); continue
        if cls == 'AudioAreaRandom' and props.get('audioTriggerPlayTrigger', '').lower().startswith('a_l_'):
            # A looping native substitute must be area-faded, not retriggered
            # indefinitely by the original randomized one-shot timer.
            entity.set('EntityClass', 'AudioAreaAmbience')
            props.set('audioRTPCRtpc', controls[('ATLRtpc', 'amb_fade_dist')])
            for attr in ('fMinDelay', 'fMaxDelay', 'fRadiusRandom', 'bMoveWithEntity'):
                props.attrib.pop(attr, None)
            record['loop_substitution'] = True
        if cls == 'AudioTriggerSpot' and props.get('audioTriggerPlayTriggerName', '').lower().startswith('a_l_'):
            props.set('bPlayRandom', '0')
        if cls in {'AudioAreaAmbience', 'AudioAreaRandom', 'AudioTriggerSpot'} and not (
                props.get('audioTriggerPlayTrigger') or props.get('audioTriggerPlayTriggerName')
                or props.get('audioEnvironmentEnvironment')):
            record.update(status='retired', reason='no_native_ambient_action'); continue
        try:
            position, rotation, scale = world_transform(original, entities)
        except ValueError as error:
            record.update(reason='unsupported_transform', detail=str(error)); continue
        for attr in ('Layer', 'EditorLayer', 'Prefab', 'ParentId', 'ParentGuid'):
            entity.attrib.pop(attr, None)
        entity.set('Pos', ','.join(map(str, position)))
        entity.set('Rotate', ','.join(map(str, rotation)))
        entity.set('Scale', ','.join(map(str, scale)))
        entity.set('Name', 'gm_environment_'+key)
        entity.set('EntityGuid', guid('environment/'+original.get('EntityGuid', key)))
        entity.set('EntityId', allocate_id())
        # Source authoring/debug keys must not become player input bindings.
        graph = entity.find('FlowGraph')
        if graph is not None:
            nodes = graph.find('Nodes'); edges = graph.find('Edges')
            debug = {n.get('Id') for n in nodes if n.get('Class', '').startswith('Debug:')}
            debug.update(n.get('Id') for n in nodes if n.get('Class') == 'Audio:Rtpc'
                         and not n.find('Inputs').get('audioRTPC_Name'))
            for n in list(nodes):
                if n.get('Id') in debug: nodes.remove(n)
            if edges is not None:
                for edge in list(edges):
                    if edge.get('nodeIn') in debug or edge.get('nodeOut') in debug: edges.remove(edge)
            if edges is None or not len(edges):
                entity.remove(graph)
                if cls == 'AudioAreaEntity' and not props.get('audioEnvironmentEnvironment'):
                    record.update(status='retired', reason='legacy_global_mixer_control'); continue
        selected[key] = (entity, record)

    # Clone only boundaries associated with imported audio, retaining local
    # points, obstruction flags, priority, fade distance and full world TRS.
    boundaries = []
    for key, original in entities.items():
        area = original.find('Area')
        if key not in active or area is None: continue
        targets = [e.get('Id') for e in area.findall('Entities/Entity')
                   if e.get('Id') in selected and selected[e.get('Id')][0].get('EntityClass', '').startswith('Audio')]
        if not targets: continue
        if original.get('EntityClass') not in {'AreaShape', 'AreaBox', 'SmartAreaShape'}:
            raise ValueError('Unsupported audio boundary class: '+str(original.get('EntityClass')))
        p,q,s = world_transform(original, entities)
        boundary = ET.Element('Entity', Name='gm_environment_area_'+key,
                              EntityClass='AreaBox' if original.get('EntityClass') == 'AreaBox' else 'AreaShape',
                              EntityId=allocate_id(), EntityGuid=guid('environment/area/'+key),
                              Pos=','.join(map(str,p)), Rotate=','.join(map(str,q)), Scale=','.join(map(str,s)))
        copied = copy.deepcopy(area)
        refs = copied.find('Entities')
        for child in list(refs): refs.remove(child)
        for target in targets: ET.SubElement(refs, 'Entity', Id=selected[target][0].get('EntityId'))
        boundary.append(copied); boundaries.append(boundary)

    # Resolve source entity references only within this imported network.
    # GraphEntity=0 and entityId=0 refer to the flowgraph's owning entity.
    for key, (entity, record) in selected.items():
        for node in entity.findall('FlowGraph/Nodes/Node'):
            inputs = node.find('Inputs')
            if inputs is not None and inputs.get('entityId', '0') != '0':
                target = inputs.get('entityId')
                if target not in selected: raise ValueError('External environmental graph reference: '+target)
                inputs.set('entityId', selected[target][0].get('EntityId'))
        links = entity.find('EntityLinks')
        if links is not None:
            for link in list(links):
                target = selected.get(link.get('TargetId'))
                if target is None: raise ValueError('External environmental entity link')
                link.set('TargetId', target[0].get('EntityId')); link.set('TargetGuid', target[0].get('EntityGuid'))
        root.append(entity)
        record.update(status='converted', target_name=entity.get('Name'), position=entity.get('Pos'))
    root.extend(boundaries)
    all_guids = [e.get('EntityGuid') for e in root if e.get('EntityGuid')]
    all_ids = [e.get('EntityId') for e in root if e.get('EntityId')]
    if len(set(all_guids)) != len(all_guids) or len(set(all_ids)) != len(all_ids):
        raise ValueError('Environment identity collision')
    return xml(root), dict(records=records, converted=dict(Counter(r['entity_class'] for r in records if r['status']=='converted')),
                           deferred=dict(Counter(r.get('reason') for r in records if r['status']=='deferred')),
                           retired=dict(Counter(r.get('reason') for r in records if r['status']=='retired')),
                           audio_boundaries=len(boundaries), runtime_verified=False)


def build(mission, source, target, guid, aliases=None):
    entities, active = inventory(source)
    effects, controls = native_catalog(target)
    return convert(mission, entities, active, effects, controls, guid,
                   native_aliases() if aliases is None else aliases)


def retire_converted_audio(mission, source=None, *, entities=None):
    """Apply the current source-control retirement policy to an older mission.

    Resolve ownership through the converter's source-ID names. Never infer a
    retirement from a native trigger name: legitimate loops use the same names
    as obsolete substitutions. Keep surviving identities and transforms intact.
    """
    root = ET.fromstring(mission)
    candidates = [e for e in root if e.get('Name', '').startswith('gm_environment_')
                  and e.get('EntityClass') in {'AudioAreaAmbience', 'AudioAreaRandom', 'AudioTriggerSpot'}]
    report = dict(version=1, cleared_controls=[], removed_emitters=[], removed_boundaries=[],
                  runtime_verified=False)
    if not candidates:
        return mission, report
    if entities is None:
        if source is None:
            raise ValueError('KCD1 source folder required to upgrade imported ambient audio')
        entities, _ = inventory(source)
    removed = set()
    actions = ('audioTriggerPlayTrigger', 'audioTriggerPlayTriggerName', 'audioEnvironmentEnvironment')
    for entity in candidates:
        source_id = entity.get('Name')[len('gm_environment_'):]
        original = entities.get(source_id)
        if original is None or original.get('EntityClass') not in CLASSES:
            raise ValueError('Missing source ambient entity: ' + source_id)
        before, after = original.find('Properties'), entity.find('Properties')
        if before is None or after is None:
            raise ValueError('Missing ambient properties: ' + source_id)
        changed = False
        for attribute in actions:
            name = before.get(attribute, '')
            if name.lower() in RETIRED.get(control_type(attribute), set()) and after.get(attribute):
                after.set(attribute, '')
                report['cleared_controls'].append(dict(source_id=source_id, attribute=attribute, source=name))
                changed = True
        if changed and not any(after.get(a) for a in actions):
            if not entity.get('EntityId'):
                raise ValueError('Missing converted ambient identity: ' + source_id)
            removed.add(entity.get('EntityId'))
            report['removed_emitters'].append(entity.get('Name'))
            root.remove(entity)
    # Shared boundaries keep their other emitters. Only converter-owned, newly
    # empty boundaries are removed; foreign references cause a safe failure.
    for entity in list(root):
        refs = entity.find('Area/Entities')
        if refs is None or not any(r.get('Id') in removed for r in refs):
            continue
        if not entity.get('Name', '').startswith('gm_environment_area_'):
            raise ValueError('Foreign area references retired ambient audio')
        for ref in list(refs):
            if ref.get('Id') in removed:
                refs.remove(ref)
        if not len(refs):
            removed.add(entity.get('EntityId'))
            report['removed_boundaries'].append(entity.get('Name'))
            root.remove(entity)
    for entity in root:
        for path, attr in (('Area/Entities/Entity', 'Id'), ('EntityLinks/Link', 'TargetId'),
                           ('FlowGraph/Nodes/Node/Inputs', 'entityId')):
            if any(n.get(attr) in removed for n in entity.findall(path)):
                raise ValueError('Retained entity references retired ambient audio')
    return (xml(root) if report['cleared_controls'] else mission), report
