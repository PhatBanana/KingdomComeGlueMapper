"""Author a flat retail control using the complete native open_world graph.

World locations are test fixtures, not native quest locations. Native prefab
service definitions are exported by Sandbox; this tool does not manufacture
their compiled scheduler rows.
"""
import argparse
import copy
import json
from pathlib import Path
import shutil
import uuid
import xml.etree.ElementTree as ET
import zipfile

from control_system_sources import SourceObjects, authored_links
from world_gameplay_basis import NativeGraphs, NATIVE
from upgrade_map import read, xml

LEVEL = 'fritz_systems_control'
LEVEL_ID = 1002
PROJECT = 'Barbora'
GRAPH = 'Quests/Final/Barbora.xml'
ACTOR = 'gmtest_trosky_ska_fricek'
CREATURES = {'NPC', 'NPC_Female', 'Horse', 'Dog'}


def identity(name):
    return str(uuid.uuid5(uuid.NAMESPACE_URL, LEVEL + '/' + name))


def prepare(editor, reference, output):
    if output.exists(): raise FileExistsError(output)
    index = SourceObjects(editor / 'Data/Levels/trosecko/Layers')
    policy = []
    def links_for(obj):
        cls, name = obj.get('EntityClass', ''), obj.get('Name', '')
        if cls in CREATURES:
            return  # Authored control residents receive local homes below.
        if cls == 'TriggerArea' and not name.startswith('crime_punishment'):
            return  # Codex/region observation areas become independent fixtures.
        for label, target in authored_links(obj):
            owner = index.owners.get(target.lower())
            path = index.paths.get(owner, '').replace('\\', '/').lower()
            if name == 'playerProxy' and '/_quest/' in path:
                policy.append(dict(source=name, label=label, target=target,
                    reason='Trosky story activity; no story quest is authored in this control'))
                continue
            yield label, target

    roots = ['sa_land', 'open_world', 'playerProxy', 'so_player_scheduler',
             'playerHorseDefaultSmartObject', 'PlayerLinkRerouter', 'hangoverSpotsHub']
    # Root assets inherited by the unmodified native open_world definition.
    with zipfile.ZipFile(editor / 'Data/Scripts.pak') as scripts:
        native = NativeGraphs(scripts)
        paths, inherited = native.audit(NATIVE, set())
        project_template = native.get('quests/final/barbora.xml')
        assets = [copy.deepcopy(a) for a in project_template.findall('Assets/*') if a.get('Name') in inherited]
        if {a.get('Name') for a in assets} != inherited: raise ValueError('Unknown inherited native asset')
        # Retain native save-state paths and ALL root systems, including horse,
        # professions and shared utilities outside open_world. Only the new
        # Level definition/instance and its current-region signal are added.
        project = ET.Element('Database', Name='brambora')
        host = copy.deepcopy(project_template)
        ET.SubElement(project, 'Skald').append(host)
        definitions = host.find('Definitions')
        ET.SubElement(definitions, 'Definition', File='../GlueControl/' + LEVEL + '.xml')
        nodes = host.find('Nodes')
        ET.SubElement(nodes, LEVEL, Name=LEVEL)
        state = nodes.find("State[@Name='currentLevel']")
        if state is None: raise ValueError('Native region state is missing')
        ET.SubElement(state, 'Edge', From=LEVEL + '.control_entered', To='SetTrosecko')
        graph_hashes = {p: native.cache[p][1] for p in sorted(paths)}
        native_ports = [dict(p.attrib) for p in native.get(NATIVE).findall('Ports/Port') if p.get('Direction') == 'In']

    native_root = index.objects[index.named('Barbora')]
    root_bindings = [copy.deepcopy(l) for l in native_root.findall('EntityLinks/Link') if l.get('Name', '').startswith('asset[')]
    asset_labels = {l.get('Name') for l in root_bindings} | {"asset['bibiana']"}
    # The story normally links Bohuta's horse dynamically. Supply that native
    # actor explicitly in this standalone fixture rather than leaving the port
    # dependent on a story quest that is not running here.
    if "asset['bibiana']" in asset_labels and not any(l.get('Name') == "asset['bibiana']" for l in root_bindings):
        root_bindings.append(ET.Element('Link', Name="asset['bibiana']",
            TargetId=index.objects[index.named('tneb_bibiana')].get('Id')))
    required = set(asset_labels)
    if {l.get('Name') for l in root_bindings} != required:
        raise ValueError('Missing native root asset bindings: ' + str(required - {l.get('Name') for l in root_bindings}))
    seeds = [index.named(n) for n in roots]
    seeds.extend(index.owners[l.get('TargetId').lower()] for l in root_bindings)
    root_modules = [copy.deepcopy(l) for l in native_root.findall("EntityLinks/Link[@Name='module']")
                    if index.objects[index.owners[l.get('TargetId').lower()]].get('Name') != 'trosecko']
    seeds.extend(index.owners[l.get('TargetId').lower()] for l in root_modules)
    selected, edges, missing = index.closure(seeds, links_for)
    # Private observation fixtures still need a real home owner. Import the
    # native ownership path, but give the owner a local control schedule.
    private_homes = []
    for key in sorted(selected):
        obj = index.objects[key]
        labels = obj.find('Properties')
        if obj.get('EntityClass') != 'TriggerArea' or labels is None or 'private' not in labels.get('Label', '').split(';'):
            continue
        hubs = [h for h, o in index.objects.items() if any(
            label == 'home_area' and target.lower() == key for label, target in authored_links(o))]
        if len(hubs) != 1: raise ValueError('Expected native private-area home for ' + obj.get('Name'))
        queue, seen, residents = [hubs[0]], set(), []
        while queue and not residents:
            target = queue.pop(0)
            if target in seen: continue
            seen.add(target)
            for owner, source in index.objects.items():
                links = [(label, dest) for label, dest in authored_links(source) if dest.lower() == target and ('home' in label or label == 'owner')]
                if not links: continue
                if source.get('EntityClass') in {'NPC', 'NPC_Female'}:
                    residents.append((not any(label == 'owner' for label, _ in links), owner))
                elif any(label == 'owner' for label, _ in links): queue.append(owner)
        if not residents: raise ValueError('Private fixture has no source resident: ' + obj.get('Name'))
        owner = sorted(residents)[0][1]
        private_homes.append((key, owner))
    selected.update(owner for _, owner in private_homes)
    # Rebind stale native location ports to an equivalent authored fixture.
    # The source contains orphaned editor links; do not turn them into zero IDs.
    rebindings = {}
    for item in missing:
        source = index.objects[index.named(item['source'])]
        link = next(l for l in source.findall('EntityLinks/Link') if l.get('TargetId').lower() == item['target'])
        debug = link.get('DebugTargetName', '').split(':')[-1].split('[')[0]
        candidates = [(guid, owner) for guid, owner in index.owners.items() if owner in selected
                      for g in index.objects[owner].iter('ObjectGUID')
                      if g.get('Instance', '').lower() == guid and g.get('Name', '').split('[')[0] == debug]
        if not debug or not candidates:
            raise ValueError('No equivalent fixture port for ' + json.dumps(item))
        rebindings[item['target']] = sorted(candidates)[0][0]

    output.mkdir(parents=True)
    level = output / LEVEL
    # This is source input for a fresh official export, not a renamed old PAK.
    level.mkdir()
    for name in ('terrain', 'leveldata', 'Tables'):
        shutil.copytree(reference / name, level / name)
    shutil.copy2(reference / 'level.editor_xml', level / 'level.editor_xml')
    shutil.copy2(reference / (reference.name + '.cry'), level / (LEVEL + '.cry'))
    (level / 'Layers').mkdir()
    layer = ET.Element('Layer', GUID=identity('layer'), Name='Main', HavePhysics='1', IsDefaultColor='1')
    objects = ET.SubElement(layer, 'Objects')
    originals = {k: copy.deepcopy(index.objects[k]) for k in selected}
    layout = {}
    for number, key in enumerate(sorted(selected)):
        obj = originals[key]
        cls, name = obj.get('EntityClass'), obj.get('Name')
        # Services are spaced across the same flat navigable field. Markers and
        # related props remain within their own native prefab's local space.
        pos = (160 + number % 16 * 44, 160 + number // 16 * 44, 32.05)
        if name == 'sa_land': pos = (64, 64, 0)
        elif cls in CREATURES: pos = (680, 520 + sum(1 for v in layout.values() if v['class'] in CREATURES) * 8, 32.05)
        obj.set('Pos', ','.join(map(str, pos)))
        for key_attr in ('Parent', 'LinkedTo'): obj.attrib.pop(key_attr, None)
        links = obj.find('EntityLinks')
        allowed = {(label, target.lower()) for label, target in links_for(index.objects[key])}
        if links is not None:
            for link in list(links):
                target = link.get('TargetId', '').lower()
                if (link.get('Name', ''), target) not in allowed: links.remove(link)
                elif target in rebindings: link.set('TargetId', rebindings[target])
        if obj.find('Points') is not None:
            obj.remove(obj.find('Points'))
            pts = ET.SubElement(obj, 'Points')
            size = 896 if name == 'sa_land' else 14
            for point in ((0, 0, 0), (0, size, 0), (size, size, 0), (size, 0, 0)):
                ET.SubElement(pts, 'Point', Pos=','.join(map(str, point)))
            obj.set('Height', '150' if name == 'sa_land' else '12')
        objects.append(obj)
        layout[key] = dict(name=name, position=pos, source=index.paths[key], **{'class': cls or obj.get('Type')})
    souls = ET.SubElement(ET.SubElement(ET.SubElement(layer, 'WHData0', version='1'), 'SoulList'), 'Souls')
    for obj in list(objects):
        if obj.get('EntityClass') not in CREATURES: continue
        source_soul = index.souls.get(obj.get('Name'))
        if source_soul is None: raise ValueError('Missing resident soul: ' + obj.get('Name'))
        souls.append(copy.deepcopy(source_soul))
        local_home(objects, obj, index.objects[index.named('sa_land')].get('Id'))
    # Import Fritz's editor actor identity; his appearance comes from the actual
    # converted character package, never the native-appearance debug override.
    previous = ET.parse(reference / 'Layers/main.lyr')
    actor = copy.deepcopy(next(o for o in previous.findall('Objects/Object') if o.get('Name') == ACTOR))
    actor.set('Pos', '512,530,32.05')
    if actor.find('EntityLinks') is not None: actor.remove(actor.find('EntityLinks'))
    objects.append(actor)
    souls.append(copy.deepcopy(next(s for s in previous.findall('WHData0/SoulList/Souls/Soul') if s.findtext('Name') == ACTOR)))
    local_home(objects, actor, index.objects[index.named('sa_land')].get('Id'))
    for area, owner in private_homes:
        home_id = identity(index.objects[owner].get('Name') + '/home')
        home = next(o for o in objects if o.get('Id') == home_id)
        ET.SubElement(home.find('EntityLinks'), 'Link', Name='home_area', TargetId=area)
    for name, cls, pos in [('ControlArrival', 'TagPoint', '512,500,32.05'), ('ControlPlayerSpawn', 'SpawnPoint', '512,500,33.7'),
                            (LEVEL, 'LevelHolder', '512,490,32.05'), (PROJECT, 'SmartObjectHolder', '512,490,32.05'),
                            ('ControlConcept', 'Concept', '512,490,32.05')]:
        obj = ET.SubElement(objects, 'Object', Id=identity(name), Name=name, EntityClass=cls, Type='TagPoint' if cls == 'TagPoint' else 'Entity', Pos=pos)
        if cls == 'SpawnPoint': ET.SubElement(obj, 'Properties', bSaved_by_game='0', bEnabled='1', bInitialSpawn='1')
        if cls == 'LevelHolder': ET.SubElement(obj, 'Properties', iLevelId=str(LEVEL_ID))
        if cls == 'Concept': ET.SubElement(obj, 'Properties', fileConcept=GRAPH, bIncludeModConcepts='0')
        if name == PROJECT:
            links = ET.SubElement(obj, 'EntityLinks')
            links.extend(root_bindings)
            links.extend(root_modules)
            # LevelHolder is registered by its name by the native exporter.
            # A second root module link double-registers that same module.
    nav = copy.deepcopy(next(o for o in previous.findall('Objects/Object') if o.get('Type') == 'NavigationArea'))
    nav.set('Pos', '64,64,0');nav.set('Height', '100')
    nav.remove(nav.find('Points'));pts = ET.SubElement(nav, 'Points')
    for p in ('0,0,0', '0,896,0', '896,896,0', '896,0,0'): ET.SubElement(pts, 'Point', Pos=p)
    objects.append(nav)
    ET.SubElement(objects, 'Object', Id=identity('navigation-seed'), Name='ControlNavigationSeed',
                  EntityClass='NavigationSeedPoint', Type='NavigationSeedPoint', Pos='512,512,32.1')
    for obj in previous.findall('Objects/Object'):
        if obj.get('Name') == 'ControlEnvironmentProbe': objects.append(copy.deepcopy(obj))
    (level / 'Layers/main.lyr').write_bytes(xml(layer))
    # Inventory/player previews and shop UI require the native off-map
    # showroom prefabs even in a combat control. Keep their authored domain.
    showroom_path = editor / 'Data/Levels/trosecko/Layers/showroom.lyr'
    showroom = ET.parse(showroom_path).getroot()
    shutil.copyfile(showroom_path, level / 'Layers/showroom.lyr')
    profile = ET.Element('LayerProfile', HasNavigation='1');ET.SubElement(profile, 'ParentProfiles')
    ET.SubElement(ET.SubElement(profile, 'ObjectLayers'), 'ObjectLayer', GUID=identity('layer'), DebugPath='Main', Exported='1')
    ET.SubElement(profile.find('ObjectLayers'), 'ObjectLayer', GUID=showroom.get('GUID'), DebugPath='showroom', Exported='1')
    (level / 'layerexportprofiles').mkdir()
    (level / 'layerexportprofiles/game.xml').write_bytes(xml(profile))
    root = ET.parse(level / 'level.editor_xml').getroot()
    native_level = ET.parse(editor / 'Data/Levels/trosecko/level.editor_xml').getroot()
    native_player = next(s for s in native_level.findall('WHData0/SoulList/Souls/Soul') if s.findtext('Player') == '1')
    player_souls = root.find('WHData0/SoulList/Souls')
    for soul in list(player_souls):
        if soul.findtext('Player') == '1': player_souls.remove(soul)
    player_souls.append(copy.deepcopy(native_player))
    root.find('WHData0/AI/LevelPath').text = 'Data/Levels/' + LEVEL
    concept_manager = root.find('WHData0/ConceptManager')
    if concept_manager is None: concept_manager = ET.SubElement(root.find('WHData0'), 'ConceptManager')
    modules = ET.SubElement(concept_manager, 'ConceptModules')
    ET.SubElement(modules, 'Module').text = LEVEL
    root.find('View').attrib.update(ViewerPos='512,500,33.7', ViewerAngles='0,0,0')
    root.find('Missions/Mission/ObjectLayers').set('DefaultStreamingProfile', 'game')
    (level / 'level.editor_xml').write_bytes(xml(root))
    graph_dir = output / 'resources/Quests/GlueControl';graph_dir.mkdir(parents=True)
    project_path = output / 'resources' / GRAPH
    project_path.parent.mkdir(parents=True, exist_ok=True)
    project_path.write_bytes(xml(project))
    level_graph = ET.Element('Database', Name='brambora')
    h = ET.SubElement(ET.SubElement(level_graph, 'Skald'), 'Level', Name=LEVEL, HibernateMode='Auto')
    ET.SubElement(ET.SubElement(h, 'Ports'), 'Port', Name='control_entered', Direction='Out', Type='trigger')
    output_node = ET.SubElement(ET.SubElement(h, 'Nodes'), 'Output', Name='Output')
    for event in ('OnWake', 'OnLevelSwitched'):
        ET.SubElement(output_node, 'Edge', From=event, To='control_entered')
    (graph_dir / (LEVEL + '.xml')).write_bytes(xml(level_graph))
    report = dict(level=LEVEL, level_id=LEVEL_ID, source=str(level), actor=ACTOR,
        native_graphs=graph_hashes, system_count=50, native_input_ports=native_ports,
        campaign_input_policy='Native Barbora project and saved paths retained; new Level signals current region Trosecko; native Trosky Level is not activated in this map',
        fixtures=layout, private_area_owners=private_homes, port_rebindings=rebindings, excluded_story_activities=policy,
        locations_are_test_fixtures=True, runtime_verified=False, exported=False)
    (output / 'control-source.json').write_text(json.dumps(report, indent=2))
    return report


def local_home(objects, obj, land_id):
    links = obj.find('EntityLinks')
    if links is not None: obj.remove(links)
    links = ET.SubElement(obj, 'EntityLinks')
    home_id, idle_id = identity(obj.get('Name') + '/home'), identity(obj.get('Name') + '/idle')
    area_id = identity(obj.get('Name') + '/home-area')
    area = ET.SubElement(objects, 'Object', Id=area_id, Name=obj.get('Name') + '_control_home_area',
                         EntityClass='TriggerArea', Type='WH_TriggerArea', Pos=obj.get('Pos'), Height='8')
    ET.SubElement(area, 'Properties', Label='')
    points = ET.SubElement(area, 'Points')
    for pos in ('-3,-3,0', '-3,3,0', '3,3,0', '3,-3,0'):
        ET.SubElement(points, 'Point', Pos=pos)
    home = ET.SubElement(objects, 'Object', Id=home_id, Name=obj.get('Name') + '_control_home', EntityClass='SchedulerHub', Type='Entity', Pos=obj.get('Pos'))
    ET.SubElement(ET.SubElement(home, 'EntityLinks'), 'Link', Name='home_area', TargetId=area_id)
    idle = ET.SubElement(objects, 'Object', Id=idle_id, Name=obj.get('Name') + '_control_idle', EntityClass='TagPoint', Type='TagPoint', Pos=obj.get('Pos'))
    ET.SubElement(ET.SubElement(idle, 'EntityLinks'), 'Link', Name='^delegate', TargetId=land_id)
    ET.SubElement(links, 'Link', Name='home', TargetId=home_id)
    ET.SubElement(links, 'Link', Name='_,schedulerWait', TargetId=idle_id)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    for arg in ('editor', 'reference', 'output'): parser.add_argument('--' + arg, type=Path, required=True)
    args = parser.parse_args()
    result = prepare(args.editor, args.reference, args.output)
    print(json.dumps(dict(level=result['level'], fixtures=len(result['fixtures']), graphs=len(result['native_graphs']))))
