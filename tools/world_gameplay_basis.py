"""Register native open-world gameplay and its destination-owned bindings.

Keep shipped graph implementations in Scripts.pak. Only generate the host and
world links; never override Barbora.xml or enable Trosky story quests globally.
"""
import copy
import hashlib
import posixpath
import xml.etree.ElementTree as ET

from campaign_entity_links import append_links
from upgrade_map import read, xml

NATIVE = 'quests/final/barbora/open_world.xml'
# These have no campaign input ports or inherited regional asset dependencies.
# Expansion is deliberate: a dependency audit is not proof of runtime parity.
SYSTEMS = (
    'combat', 'boj_a_zraneni', 'reakce_na_stav_hrace', 'reputace',
    'spanek_npc', 'pozdravy_a_rozlouceni_mezi_npc',
    'pozdravy_na_zacatku_dialogu', 'rozlouceni_na_konci_dialogu',
    'reakce_pratelskych_nepratel', 'statistical_perks', 'perky',
    'requestplayerholsterweapon', 'generic_action_prompts',
    'battle_barks', 'punishment_barks', 'shop', 'repair', 'sharpening',
)


class NativeGraphs:
    def __init__(self, archive):
        self.archive = archive
        self.names = {n.lower(): n for n in archive.namelist()}
        self.cache = {}

    def get(self, path):
        path = path.lower()
        if path not in self.cache:
            if path not in self.names:
                raise ValueError('Missing native gameplay dependency: ' + path)
            payload = read(self.archive, self.names[path])
            root = ET.fromstring(payload)
            modules = list(root.find('Skald'))
            if len(modules) != 1:
                raise ValueError('Expected one Skald module: ' + path)
            self.cache[path] = (modules[0], hashlib.sha256(payload).hexdigest())
        return self.cache[path][0]

    def audit(self, path, inherited, stack=()):
        path = path.lower()
        if path in stack:
            raise ValueError('Cyclic native Definition dependency: ' + path)
        module = self.get(path)
        scope = set(inherited) | {a.get('Name') for a in module.findall('Assets/*')}
        missing = {a.get('Alias') for a in module.iter('Asset')} - scope
        paths = {path}
        for definition in module.findall('Definitions/Definition'):
            child = posixpath.normpath(posixpath.join(posixpath.dirname(path), definition.get('File'))).lower()
            child_paths, child_missing = self.audit(child, scope, (*stack, path))
            paths |= child_paths
            missing |= child_missing
        return paths, missing


def apply(files, graphs, graph_path, level, native_level, scripts, identity):
    files, graphs = dict(files), dict(graphs)
    native = NativeGraphs(scripts)
    original = native.get(NATIVE)
    project = native.get('quests/final/barbora.xml')
    parent = graph_path.rsplit('/', 1)[0]
    entry_path = parent + '/entry/' + level + '.xml'
    wrapper_path = parent + '/world/open_world.xml'
    entry = ET.fromstring(graphs[entry_path])
    host = entry.find('Skald/Level')
    if host is None or host.find("Nodes/*[@Name='open_world']") is not None:
        raise ValueError('Expected destination Level without gameplay basis')
    wrapper = ET.Element('Database', Name='brambora')
    gameplay = ET.SubElement(ET.SubElement(wrapper, 'Skald'), 'Gameplay',
                            Name='open_world', VoiceNamespace='true', HasteNamespace='true')
    assets = ET.SubElement(gameplay, 'Assets')
    for alias in ('player', 'player_any'):
        template = project.find("Assets/SoulAsset[@Name='" + alias + "']")
        if template is None or not template.get('SharedSoulGuids'):
            raise ValueError('Native player alias missing: ' + alias)
        assets.append(copy.deepcopy(template))
    assets.append(copy.deepcopy(original.find("Assets/SmartObjectAsset[@Name='openworld']")))
    definitions = ET.SubElement(gameplay, 'Definitions')
    nodes = ET.SubElement(gameplay, 'Nodes')
    inventory, selected_paths = [], set()
    for definition in original.findall('Definitions/Definition'):
        path = posixpath.normpath(posixpath.join(posixpath.dirname(NATIVE), definition.get('File'))).lower()
        module = native.get(path)
        name = module.get('Name')
        paths, missing = native.audit(path, {'player', 'player_any', 'openworld'})
        ports = [p.get('Name') for p in module.findall('Ports/Port') if p.get('Direction') == 'In']
        selected = name in SYSTEMS
        if selected:
            if missing or ports:
                raise ValueError(f'Unadapted native dependencies for {name}: assets={sorted(missing)}, ports={ports}')
            instances = [n for n in original.findall('Nodes/*') if n.tag == name]
            if len(instances) != 1 or list(instances[0]):
                raise ValueError('Native system requires parent wiring: ' + name)
            ET.SubElement(definitions, 'Definition', File=posixpath.relpath(path, posixpath.dirname(wrapper_path)))
            nodes.append(copy.deepcopy(instances[0]))
            selected_paths |= paths
        inventory.append(dict(name=name, registered=selected, input_ports=ports,
                              inherited_assets=sorted(missing), graph_count=len(paths), runtime_verified=False))
    if {r['name'] for r in inventory if r['registered']} != set(SYSTEMS):
        raise ValueError('Native baseline system set changed')
    # Copy only inherited type declarations actually used by selected graphs.
    used_types = {v for p in selected_paths for e in native.get(p).iter()
                  for k, v in e.attrib.items() if k in ('Type', 'TypeT')}
    types = [t for t in project.findall('Types/Type') if t.get('TypeName') in used_types]
    if types:
        section = ET.SubElement(gameplay, 'Types')
        section.extend(copy.deepcopy(types))
    section = host.find('Definitions')
    if section is None: section = ET.SubElement(host, 'Definitions')
    ET.SubElement(section, 'Definition', File='../world/open_world.xml')
    ET.SubElement(host.find('Nodes'), 'open_world', Name='open_world')

    mission = ET.fromstring(files['objects_mission0.xml'])
    source = ET.fromstring(read(native_level, 'objects_mission0.xml'))
    def one(root, name):
        matches = [e for e in root if e.get('Name') == name]
        if len(matches) != 1: raise ValueError('Expected one world entity: ' + name)
        return matches[0]
    holder, land = one(mission, level), one(mission, 'sa_land')
    def place(name):
        if any(e.get('Name') == name for e in mission):
            raise ValueError('Gameplay service already present: ' + name)
        entity = copy.deepcopy(one(source, name))
        for child in list(entity):
            if child.tag != 'Properties': entity.remove(child)
        for key in ('Layer', 'EditorLayer', 'ParentId'): entity.attrib.pop(key, None)
        entity.set('EntityGuid', identity('world-gameplay/' + name))
        if any(e.get('EntityGuid') == entity.get('EntityGuid') for e in mission):
            raise ValueError('Gameplay service identity collision: ' + name)
        entity.set('EntityId', str(max(int(e.get('EntityId', '0')) for e in mission) + 1))
        entity.set('Pos', holder.get('Pos'))
        mission.append(entity)
        return entity
    world, surrender = place('open_world'), place('surrenderHolder')
    links = [(holder, world, 'module'), (world, world, "asset['openworld']"),
             (world, surrender, "asset['surrenderDH']"), (land, world, 'punishment_openworldQSO')]
    for a, b, label in links:
        section = a.find('EntityLinks')
        if section is None: section = ET.SubElement(a, 'EntityLinks')
        ET.SubElement(section, 'Link', Name=label, TargetId=b.get('EntityId'), TargetGuid=b.get('EntityGuid'))
    files['objects_mission0.xml'] = xml(mission)
    files['waitinglinks.xml'] = append_links(files['waitinglinks.xml'],
        [(a.get('EntityGuid'), b.get('EntityGuid'), label) for a, b, label in links])
    graphs[entry_path], graphs[wrapper_path] = xml(entry), xml(wrapper)
    return files, graphs, dict(systems=inventory, native_dependencies={p: native.cache[p][1] for p in sorted(selected_paths)},
        service_bindings=[dict(source=a.get('Name'), target=b.get('Name'), label=l) for a,b,l in links],
        runtime_verified=False, full_trosky_parity=False)
