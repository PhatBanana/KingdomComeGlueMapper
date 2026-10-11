"""Attach native room-rental state/payment logic to the imported innkeeper menu."""
import copy
import hashlib
import posixpath
import xml.etree.ElementTree as ET

from region_travel_merchant import ROLE, DIALOG
from upgrade_map import read, xml

BASE = 'Quests/Final/Barbora/utils/'
MODULE = 'gm_room_rental'
DIRECTORY = 'Quests/GlueTravel/rental'
PROJECT = 'Quests/GlueTravel/GlueTravel_kcd1.xml'
DIALOG_PATH = 'Quests/GlueTravel/rattay_innkeeper.xml'


def prepare_service_menu(decision):
    """Keep native choices/actions without unresolved cinematic responses.

    Imported service actors do not have the original campaign voice/timing
    context. An empty response is the same immediate transition used by our
    working Trade and horse-payment menus. Never remove sequence scripts,
    payment types, conditions or output triggers.
    """
    for elements in decision.iter('Elements'):
        for response in list(elements):
            if response.tag == 'Response':
                response.clear()
                response.set('Role', 'HENRY')
    for sequence in decision.iter('Sequence'):
        if sequence.get('Type') == 'Payment' or sequence.find('Triggers') is not None:
            script = sequence.get('ExitScript', '')
            sequence.set('ExitScript', (script + '; ' if script else '') + "System.LogAlways('GLUE_ROOM_RENTAL sequence=" + sequence.get('Name') + "');")
    return decision


class NativeModules:
    """Localize the exact dependency closure, without starting native quests."""
    def __init__(self, scripts):
        self.scripts = scripts
        self.names = {n.lower(): n for n in scripts.namelist()}
        self.files, self.loaded = {}, {}

    def load(self, path):
        path = posixpath.normpath(path).lower()
        if path in self.loaded: return self.loaded[path]
        root = ET.fromstring(read(self.scripts, self.names[path]))
        module = list(root.find('Skald'))[0]
        name = 'gm_rent_' + hashlib.sha256(path.encode()).hexdigest()[:12]
        self.loaded[path] = name
        module.set('Name', name)
        definitions = module.find('Definitions')
        if definitions is None: definitions = ET.SubElement(module, 'Definitions')
        mapping = {}
        for definition in list(definitions):
            child_path = posixpath.normpath(posixpath.join(posixpath.dirname(path), definition.get('File')))
            original = list(ET.fromstring(read(self.scripts, self.names[child_path.lower()])).find('Skald'))[0].get('Name')
            child = self.load(child_path)
            mapping[('', original)] = child
            definition.set('File', child+'.xml')
        for node in module.findall('Nodes/*'):
            namespace = node.get('Namespace', '')
            sibling = posixpath.join(posixpath.dirname(path), node.tag+'.xml').lower()
            if not namespace and ('', node.tag) not in mapping and sibling in self.names:
                child = self.load(sibling)
                mapping[('', node.tag)] = child
                ET.SubElement(definitions, 'Definition', File=child+'.xml')
            if namespace:
                key = (namespace, node.tag)
                if key not in mapping:
                    child = self.load(BASE + namespace.replace('.', '/') + '/' + node.tag + '.xml')
                    mapping[key] = child
                    ET.SubElement(definitions, 'Definition', File=child+'.xml')
            key = (namespace, node.tag)
            if key in mapping:
                node.tag = mapping[key]; node.attrib.pop('Namespace', None)
        self.files[DIRECTORY+'/'+name+'.xml'] = xml(root)
        return name


def attach(resources, scripts, keeper_soul):
    result = dict(resources)
    native_path = BASE+'roomrenting/roomrent.xml'
    library = NativeModules(scripts)
    root_name = library.load(native_path)
    rental = ET.fromstring(library.files.pop(DIRECTORY+'/'+root_name+'.xml'))
    module = rental.find('Skald/Module'); module.set('Name', MODULE)
    native_dialog = ET.fromstring(read(scripts, BASE+'roomrenting/roomrent/muz_v_hostinci_pronajem.xml')).find('Skald/FaderDialog')
    dialog_root = ET.fromstring(result[DIALOG_PATH]); dialog = dialog_root.find('Skald/FaderDialog')
    if dialog.find("Ports/Port[@Name='spravna_soula']") is not None: raise ValueError('Rental dialogue already attached')
    for port in native_dialog.find('Ports'): dialog.find('Ports').append(copy.deepcopy(port))
    choices = dialog.find(".//Decision[@Name='services']/Sequences")
    if choices is None: raise ValueError('Innkeeper service menu missing')
    native_decision = prepare_service_menu(copy.deepcopy(native_dialog.find('Dialogue/Decision')))
    for node in native_decision.iter():
        for key, value in list(node.attrib.items()): node.set(key, value.replace('HOSPODSKY_PRONAJEM', ROLE))
    for sequence in reversed(list(native_decision.find('Sequences'))): choices.insert(1, sequence)
    result[DIALOG_PATH] = xml(dialog_root)
    male_name = library.loaded[(BASE+'roomrenting/roomrent/muz_v_hostinci_pronajem.xml').lower()]
    definitions = module.find('Definitions')
    for definition in definitions:
        if definition.get('File') == male_name+'.xml': definition.set('File', '../rattay_innkeeper.xml')
    library.files.pop(DIRECTORY+'/'+male_name+'.xml')
    for node in module.findall('Nodes/*'):
        if node.get('Name') == 'muz_v_hostinci_pronajem': node.tag = DIALOG
        for child in node.iter():
            for attr, value in list(child.attrib.items()):
                child.set(attr, value.replace('HOSPODSKY_PRONAJEM', ROLE))
    # Keep its native instance name: all native rental edges remain valid.
    ports = module.find('Ports')
    # This room has no authored meal entitlement. Do not leave the native
    # optional cooking-pot asset pointing at an unresolved object.
    ports.remove(ports.find("Port[@Name='kotlik']"))
    module.find('Nodes').remove(module.find("Nodes/SetOwner[@Name='setowner3']"))
    module.find('Assets').remove(module.find("Assets/SmartObjectAsset[@Name='kotlik']"))
    ET.SubElement(ports, 'Port', Name='dialog_started', Direction='Out', Type='trigger')
    output = module.find("Nodes/Output")
    if output is None: output = ET.SubElement(module.find('Nodes'), 'Output', Name='Output')
    ET.SubElement(output, 'Edge', From='muz_v_hostinci_pronajem.dialog_started', To='dialog_started')
    assets = module.find('Assets')
    if assets is None: assets = ET.SubElement(module, 'Assets')
    barbora = ET.fromstring(read(scripts, 'Quests/Final/Barbora.xml'))
    for alias in ('player', 'player_any'):
        assets.append(copy.deepcopy(barbora.find(f".//Assets/SoulAsset[@Name='{alias}']")))
    # Shared utilities must be defined once in the common parent scope.
    # Re-importing the same file under sibling modules makes the engine cache
    # it in the first scope, leaving later siblings with an undefined type.
    definitions.clear()
    for path, blob in list(library.files.items()):
        child_root = ET.fromstring(blob)
        child_module = list(child_root.find('Skald'))[0]
        child_defs = child_module.find('Definitions')
        if child_defs is not None: child_module.remove(child_defs)
        library.files[path] = xml(child_root)
        ET.SubElement(definitions, 'Definition', File=posixpath.basename(path))
    ET.SubElement(definitions, 'Definition', File='../rattay_innkeeper.xml')
    referenced = {value for blob in [*library.files.values(), xml(rental)]
                  for element in ET.fromstring(blob).iter() for value in element.attrib.values()}
    types = module.find('Types')
    if types is None: types = ET.SubElement(module, 'Types')
    existing = {element.get('TypeName') for element in types}
    for definition in barbora.findall('Skald/Project/Types/Type'):
        if definition.get('TypeName') in referenced - existing:
            types.append(copy.deepcopy(definition))
    # Parent binds the chest through an input, since asset lookup is host-local.
    ET.SubElement(ports, 'Port', Name='chest', Direction='In', Type='wh::entitymodule::Stash*')
    nodes = module.find('Nodes')
    for name, method, events in [('chest_unlock', 'Unlock', ('state24.OnoneNight','state24.Oninfinite','if34_1.True')),
                                  ('chest_lock', 'LockUp', ('state24.Onnone',))]:
        fn = ET.SubElement(nodes, 'Function', Name=name, MethodName='wh::entitymodule::'+method, DeclaringType='wh::entitymodule')
        ET.SubElement(fn, 'Edge', From='chest', To='LockBase')
        for event in events: ET.SubElement(fn, 'Edge', From=event, To='Exec')
    owner = ET.SubElement(nodes, 'SetOwner', Name='rental_chest_owner')
    ET.SubElement(owner, 'Asset', Name='Who', Alias='player')
    ET.SubElement(owner, 'Edge', From='chest', To='What')
    ET.SubElement(owner, 'Edge', From='or32.bool', To='IsActive')
    result.update(library.files)
    result[DIRECTORY+'/'+MODULE+'.xml'] = xml(rental)
    project_root = ET.fromstring(result[PROJECT]); project = project_root.find('Skald/Project')
    for definition in project.find('Definitions'):
        if definition.get('File') == 'rattay_innkeeper.xml': definition.set('File', 'rental/'+MODULE+'.xml')
    node = project.find(f"Nodes/{DIALOG}")
    if node is None: raise ValueError('Expected exactly one existing innkeeper conversation')
    node.tag = MODULE; node.set('Name', MODULE)
    for role, alias in [('souls','rattay_innkeeper'),('dvere','rental_door'),('so','rental_service'),('postel','rental_bed'),('chest','rental_chest')]:
        ET.SubElement(node, 'Asset', Name=role, Alias=alias)
    ET.SubElement(node, 'Edge', From='kcd1_travel.arrived', To='levelswitched')
    for edge in project.iter('Edge'):
        if edge.get('From') == DIALOG+'.dialog_started': edge.set('From', MODULE+'.dialog_started')
    assets = project.find('Assets')
    for tag, alias in [('AnimDoorAsset','rental_door'),('SmartObjectAsset','rental_service'),('SmartObjectAsset','rental_bed'),('StashAsset','rental_chest')]:
        ET.SubElement(assets, tag, Name=alias)
    result[PROJECT] = xml(project_root)
    return result, {'native_module': native_path, 'dependency_modules': len(library.files),
                    'duration': 'Native overnight expiry at 08:00; permanent option retained',
                    'keeper_soul': keeper_soul}
