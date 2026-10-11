"""Replace active KCD1 architectural door visuals with native locked doors."""
from contextlib import ExitStack
import copy
from pathlib import Path
from types import SimpleNamespace
import xml.etree.ElementTree as ET
import zipfile

from campaign_dependencies import DependencyImporter
from campaign_dependency_adapters import StaticAssetAdapter
from campaign_doors import NativeDoorCatalog, AnimatedDoorAssetAdapter, normalized
from campaign_entity_links import native_guid
from chairs import inventory
from cooking_pots import vector
from door_keys import build as build_keys
from door_locks import convert_properties, difficulty_rules
from entity_visuals import world_transform
from room_rental import source_room
from seating_animations import install
from upgrade_map import read, xml


def lower_helper(family, source_helpers, native_helpers, collections):
    """Retain the source lowered rear approach on the native helper family."""
    base = family.split('_backHelperLower')[0]
    target = 'gm_' + family
    originals = [e for e in native_helpers if e.get('name') == base and e.tag == 'Class'
                 or e.get('className') == base]
    if not originals: raise ValueError('Missing native helper family '+base)
    source_back, = [e for e in source_helpers if e.tag == 'Helper' and e.get('className') == family and e.get('name') == 'Back']
    for original in originals:
        node = copy.deepcopy(original)
        if node.tag == 'Class': node.set('name', target)
        else:
            node.set('className', target)
            if node.get('name') == 'Back':
                node.set('pos', source_back.get('pos'));node.set('rot', source_back.get('rot'))
        native_helpers.append(node)
    donor, = [e for e in collections if e.get('HelperSetName') == base]
    result = copy.deepcopy(donor);result.set('HelperSetName', target)
    return target, result


def build(files, source, target):
    source,target = Path(source),Path(target)
    with ExitStack() as stack:
        src = stack.enter_context(zipfile.ZipFile(source/'Data/Levels/rataje/level.pak'))
        native = stack.enter_context(zipfile.ZipFile(target/'Data/Levels/trosecko/level.pak'))
        old_game = stack.enter_context(zipfile.ZipFile(source/'Data/GameData.pak'))
        new_game = stack.enter_context(zipfile.ZipFile(target/'Data/IPL_GameData.pak'))
        scripts = stack.enter_context(zipfile.ZipFile(source/'Data/Scripts.pak'))
        rules = difficulty_rules(read(scripts,'Scripts/Entities/Doors/AnimDoor.lua').decode())
        entities,doors,deferred = inventory(src,'AnimDoor')
        mission = ET.fromstring(files['objects_mission0.xml'])
        visuals = {e.get('Name'): e for e in mission.iter('Entity')}
        if any(n.startswith('gm_door_') for n in visuals):raise ValueError('Doors already converted')
        rental = source_room(entities,'rato_innkeeper1')[1]['door'].get('EntityId') if 'gm_rental_door' in visuals else None
        pack = StaticAssetAdapter(stack,source.parent,'worlddoors',None)
        catalog = NativeDoorCatalog(target,stack)
        adapter = AnimatedDoorAssetAdapter(SimpleNamespace(adapter=pack),catalog,'worlddoors')
        importer = DependencyImporter({'animated_props':adapter,'assets':pack})
        old_helpers = ET.fromstring(read(old_game,'Libs/SmartObjects.xml'))
        new_helpers = ET.fromstring(read(new_game,'Libs/SmartObjects.xml'))
        collections = ET.fromstring(read(native,'smartobjecthelpersetanimations.xml'))
        custom_helpers,extra = {},[]
        next_id = max(int(e.get('EntityId','0')) for e in mission.iter('Entity'))+1
        records,exceptions,keys = [],[],set()
        for door in doors:
            sid = door.get('EntityId');source_props = door.find('Properties')
            if sid == rental:
                records.append(dict(source_id=sid,policy='existing rental service',name='gm_rental_door'))
                continue
            model = normalized(source_props.get('object_Model',''))
            if not model.endswith('.cdf'):
                # This is the library quest cabinet, not an architectural door.
                # Its bespoke CGA/quest animation must not become a hinged door.
                exceptions.append(dict(source_id=sid,name=door.get('Name'),model=model,
                                       reason='Quest cabinet requires CGA and quest-specific interaction conversion'))
                continue
            target_model = importer.ensure('animated_props',model)
            if target_model is None:
                failures = [r for r in importer.report()['jobs'] if r['status']=='conversion_failed']
                raise ValueError('Door asset conversion failed: '+str(failures))
            rig = importer.jobs[('animated_props',model)]['source']['rig']
            family = source_props.get('soclasses_SmartObjectHelpers')
            base = family.split('_backHelperLower')[0]
            contract = catalog.resolve(rig,base)
            if family != base:
                if family not in custom_helpers:
                    custom_helpers[family],collection = lower_helper(family,old_helpers,new_helpers,collections)
                    extra.append(collection)
                contract['helper'] = custom_helpers[family]
            props,evidence = convert_properties(source_props,target_model,contract,rules)
            key = props.find('Lock').get('guidItemClassId','').lower()
            if key and key != '00000000-0000-0000-0000-000000000000':keys.add(key)
            pos,rot,scale = world_transform(door,entities)
            entity = ET.Element('Entity',Name='gm_door_'+sid,EntityClass='AnimDoor',EntityId=str(next_id),
                                EntityGuid=native_guid(int(door.get('EntityGuid'),16)),
                                Pos=vector(pos),Rotate=vector(rot),Scale=vector(scale),CastShadowMinSpec='1')
            next_id+=1;entity.append(props)
            visual = visuals.get('glue_item_'+sid)
            if visual is None:raise ValueError('Missing original door visual '+sid)
            for parent in mission.iter():
                if visual in list(parent):parent.remove(visual);break
            mission.append(entity)
            records.append(dict(source_id=sid,name=entity.get('Name'),guid=entity.get('EntityGuid'),position=pos,
                                source_model=model,model=target_model,helper=contract['helper'],**evidence))
        result = dict(files);result['objects_mission0.xml'] = xml(mission)
        result,animations = install(result,native,prefixes=('gm_chair_','gm_bench_','gm_rental_'),extra_collections=extra)
        key_files,strings,recovered_keys = build_keys(source,keys,pack)
        resources = dict(importer.files);resources.update(key_files)
        if custom_helpers:resources['Libs/SmartObjects.xml'] = xml(new_helpers)
        resources = {n:b.read_bytes() if isinstance(b,Path) else b for n,b in resources.items()}
    return result,resources,strings,dict(converted=len(records)-(1 if rental else 0),
        preserved_rental_doors=1 if rental else 0,keys=len(keys),recreated_missing_source_keys=recovered_keys,records=records,
        inactive_layer_doors=deferred,non_architectural_exceptions=exceptions,animations=animations,
        runtime_verified=False,source_save_state_imported=False)
