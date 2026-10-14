"""Bind imported dialogue audio and objective ports to native registrations.

No scene is selected or launched here. Actor placement, invocation and animation
dependencies remain owned by the campaign/world importers.
"""
import argparse
import hashlib
import json
import posixpath
import uuid
from pathlib import Path
import xml.etree.ElementTree as ET
import zipfile

from campaign_quest_graph import identifier, xml
from dialogue_dubbing import ogg_duration, dubbing_index, DEPOT
from upgrade_map import read
from campaign_dialogue_conditions import ENGINE_PREDICATES
from campaign_dialogue_effects import wire_program


def inventory_predicate(nodes, stem, binding):
    """Translate count comparisons through native inventory descriptors."""
    identifier(binding['asset']); uuid.UUID(binding['item'])
    amount, operator = binding['amount'], binding['operator']
    if type(amount) is not int or not 0 <= amount <= 2147483646 or operator not in ('>', '>=', '<', '<=', '==', '!='):
        raise ValueError('Invalid inventory predicate comparison')
    soul = ET.SubElement(nodes, 'ObjectProperties', Name=stem + '_soul', DeclaringType='wh::rpgmodule::I_Soul')
    ET.SubElement(soul, 'Asset', Name='I_Soul', Alias=binding['asset'])
    inv = ET.SubElement(nodes, 'MemberFunction', Name=stem + '_items', MethodName='Items', DeclaringType='wh::entitymodule::Inventory')
    ET.SubElement(inv, 'Edge', From=stem + '_soul.Inventory', To='Inventory')
    def at_least(count):
        name = stem + '_atleast_' + str(count)
        if count == 0:
            present = at_least(1)
            absent = invert(present, '_absent')
            n = ET.SubElement(nodes, 'Function', Name=name, MethodName='math::boolean::Or', DeclaringType='math::boolean')
            ET.SubElement(n, 'Edge', From=present, To='A'); ET.SubElement(n, 'Edge', From=absent, To='B')
            return name + '.bool'
        desc = ET.SubElement(nodes, 'Function', Name=name + '_descriptor',
            MethodName='wh::entitymodule::CreateItemClassDescriptor', DeclaringType='wh::entitymodule')
        ET.SubElement(desc, 'Constant', Name='ItemClass', Value=binding['item'])
        ET.SubElement(desc, 'Constant', Name='Amount', Value=str(count))
        n = ET.SubElement(nodes, 'MemberFunction', Name=name, MethodName='FullyMatchesItems', DeclaringType='wh::entitymodule::ItemDescriptor')
        ET.SubElement(n, 'Edge', From=name + '_descriptor.ItemDescriptor', To='ItemDescriptor')
        ET.SubElement(n, 'Edge', From=stem + '_items.Items', To='InputItems')
        return name + '.bool'
    def invert(value, suffix):
        name = stem + suffix
        n = ET.SubElement(nodes, 'Function', Name=name, MethodName='math::boolean::Not', DeclaringType='math::boolean')
        ET.SubElement(n, 'Edge', From=value, To='Value')
        return name + '.bool'
    if operator in ('>', '>='): return at_least(amount + (operator == '>'))
    if operator in ('<', '<='): return invert(at_least(amount + (operator == '<=')), '_not')
    upper = invert(at_least(amount + 1), '_upper')
    if amount == 0:
        equal = upper
    else:
        lower = at_least(amount)
        n = ET.SubElement(nodes, 'Function', Name=stem + '_equal', MethodName='math::boolean::And', DeclaringType='math::boolean')
        ET.SubElement(n, 'Edge', From=lower, To='A'); ET.SubElement(n, 'Edge', From=upper, To='B')
        equal = stem + '_equal.bool'
    return equal if operator == '==' else invert(equal, '_not_equal')


def imported_resources(package, report):
    """Carry converted database dependencies alongside their dialogue."""
    data = (Path(package) / 'Data').resolve()
    result = {}
    for name, digest in report.get('resources', {}).items():
        path = (data / name).resolve()
        if not name.startswith('Libs/Tables/') or not path.is_relative_to(data):
            raise ValueError('Dialogue resource escapes its database package')
        payload = path.read_bytes()
        if hashlib.sha256(payload).hexdigest() != digest:
            raise ValueError('Dialogue resource differs from conversion receipt: ' + name)
        result['Data/' + name] = payload
    return result


def voice_namespace(files, container_file):
    """Resolve native audio scope through instantiated quest definitions.

    Native Level/Quest scopes contribute a folder by default; other containers
    contribute only when VoiceNamespace is enabled. Do not infer this from the
    XML file's directory: definitions and runtime scopes need not match.
    """
    hosts = {}
    for path, blob in files.items():
        root = ET.fromstring(blob)
        skald = root.find('Skald')
        if skald is not None and len(skald) == 1:
            hosts[path] = skald[0]
    if container_file not in hosts:
        raise ValueError('Missing dialogue container')
    parents = {}
    for parent_path, host in hosts.items():
        for declaration in host.findall('./Definitions/Definition'):
            child_path = posixpath.normpath(posixpath.join(posixpath.dirname(parent_path), declaration.get('File')))
            child = hosts.get(child_path)
            if child is None: continue
            for instance in host.findall('./Nodes/' + child.get('Name', '__missing')):
                parents.setdefault(child_path, set()).add((parent_path, instance.get('Name')))
    chain, visited = [], set()
    current = container_file
    while True:
        if current in visited: raise ValueError('Cyclic dialogue container hierarchy')
        visited.add(current)
        host = hosts[current]
        enabled = host.get('VoiceNamespace', 'true' if host.tag in ('Level', 'Quest') else 'false')
        if enabled == 'true':
            name = host.get('Name'); identifier(name); chain.append(name)
        candidates = parents.get(current, set())
        if not candidates:
            if host.tag != 'Project': raise ValueError('Unrooted dialogue audio container')
            break
        if len(candidates) != 1: raise ValueError('Ambiguous dialogue audio container')
        parent_path, instance_name = next(iter(candidates))
        if instance_name != host.get('Name'):
            raise ValueError('Audio namespace for renamed instances requires validation')
        current = parent_path
    return tuple(reversed(chain))


def bind_recordings(blob, model, media, native_voices, language='ENG', *, parent_namespace=()):
    """Use original recorded speakers and native VoiceNamespace lookup paths."""
    root = ET.fromstring(blob)
    host = list(root.find('Skald'))[0]
    name = host.get('Name')
    identifier(name)
    for segment in parent_namespace: identifier(segment)
    audio_folder = '/'.join((*parent_namespace, name)).lower()
    if host.tag not in ('ForcedDialog', 'FaderDialog', 'Dialog'):
        raise ValueError('Expected a native dialogue definition')
    by_stem = {}
    for path, payload in media.items():
        stem = Path(path).stem
        if stem in by_stem:
            raise ValueError('Ambiguous imported recording: ' + stem)
        by_stem[stem] = payload
    catalog = {}
    for voice in ET.fromstring(native_voices).iter('voice'):
        abbreviation = voice.get('abbreviation')
        if not abbreviation:
            continue
        catalog.setdefault(abbreviation, []).append(dict(voice.attrib))
    recordings, roles = {}, {}
    for topic in model['topics'].values():
        for sequence in topic['sequences']:
            for line in sequence['lines']:
                response = line['response']
                if response is None:
                    continue
                if len(line['voices']) != 1:
                    raise ValueError('Select one source recording per response before binding')
                wave = line['voices'][0]
                stem, key = wave['wave_file'], response['string_name']
                prefix = stem.removesuffix('_' + key)
                if stem != prefix + '_' + key or len(catalog.get(prefix, [])) != 1:
                    raise ValueError('Missing or ambiguous native voice for recording: ' + stem)
                voice = catalog[prefix][0]
                role = model['roles'][response['role_id']]['role_name']
                if role in roles and roles[role] != voice:
                    raise ValueError('Multiple source voices for dialogue role: ' + role)
                roles[role] = voice
                if stem not in by_stem:
                    raise ValueError('Missing imported recording: ' + stem)
                duration = ogg_duration(by_stem[stem])
                record = dict(role=role, stem=stem, duration=duration,
                              path='dialog/' + audio_folder + '/' + stem + '.ogg')
                if key in recordings and recordings[key] != record:
                    raise ValueError('Conflicting source response identity: ' + key)
                recordings[key] = record
    body = host.find('Dialogue')
    if body.find('SelectedSouls') is not None:
        raise ValueError('Dialogue already has voice bindings')
    selected = ET.Element('SelectedSouls')
    for role, voice in sorted(roles.items()):
        ET.SubElement(selected, 'SelectedSoul', Role=role,
                      Voice=voice['voice_technical_name'], Type='Wave', Language=language)
    body.insert(0, selected)
    host.set('VoiceNamespace', 'true')
    used = set()
    for response in body.iter('Response'):
        key = response.find('Text').get('StringName')
        record = recordings.get(key)
        if record is None or record['role'] != response.get('Role'):
            raise ValueError('Emitted response does not match the source recording')
        response.set('ReferenceLength', f"{record['duration']:.6f}")
        used.add(key)
    if used != recordings.keys():
        raise ValueError('Source recordings were omitted from dialogue')
    output = {r['path']: by_stem[r['stem']] for r in recordings.values()}
    return xml(root), output, dict(roles=roles, responses=list(recordings.values()), parent_namespace=list(parent_namespace),
                                   runtime_verified=False)


def attach_dialogue(files, project, dialogue_blob, report, activation, container_file=None):
    """Wire source objective effects, validating the actual destination ports.

    activation is a declared bool output on an existing project node. This
    function cannot synthesize a startup event or substitute a constant true.
    """
    identifier(project)
    result = dict(files)
    container_file = container_file or project + '.xml'
    root = ET.fromstring(files[container_file])
    hosts = list(root.find('Skald'))
    if len(hosts) != 1 or hosts[0].tag not in ('Project', 'Level'):
        raise ValueError('Expected a project or level dialogue container')
    host = hosts[0]
    def resolve_file(relative, base=None):
        resolved = posixpath.normpath(posixpath.join(posixpath.dirname(base or container_file), relative))
        if resolved.startswith(('../', '/')) or ':' in resolved or '\\' in resolved:
            raise ValueError('Dialogue definition escapes the quest package')
        return resolved
    definitions, nodes = host.find('Definitions'), host.find('Nodes')
    definition_paths = {ET.fromstring(files[resolve_file(d.get('File'))]).find('Skald')[0].get('Name'): resolve_file(d.get('File'))
                        for d in definitions}
    # Level instances can use definitions declared by their containing project.
    # Follow actual definition edges, rather than accepting any same-named file.
    visited = set()
    def inherit(child):
        if child in visited: return
        visited.add(child)
        for parent_path, payload in files.items():
            parent = ET.fromstring(payload).find('Skald')
            if parent is None or len(parent) != 1 or parent[0].tag not in ('Project', 'Level'):
                continue
            references = [resolve_file(d.get('File'), parent_path) for d in parent[0].findall('Definitions/Definition')]
            if child not in references: continue
            for path in references:
                declared = ET.fromstring(files[path]).find('Skald')[0].get('Name')
                # A local declaration shadows its containing project's name
                # (native projects use this for module/journal counterparts).
                definition_paths.setdefault(declared, path)
            inherit(parent_path)
    inherit(container_file)
    native = ET.fromstring(dialogue_blob).find('Skald')[0]
    name = native.get('Name'); identifier(name)
    if name in definition_paths or any(n.get('Name') == name for n in nodes):
        raise ValueError('Dialogue is already registered')
    def node_port(instance, port, direction, typ):
        found = [n for n in nodes if n.get('Name') == instance]
        if len(found) != 1 or found[0].tag not in definition_paths:
            raise ValueError('Missing declared project instance: ' + instance)
        tree = ET.fromstring(files[definition_paths[found[0].tag]])
        ports = [p for p in tree.findall('./Skald/*/Ports/Port') if p.get('Name') == port]
        if len(ports) != 1 or ports[0].get('Direction') != direction or ports[0].get('Type') != typ:
            raise ValueError('Incompatible project port: ' + instance + '.' + port)
        return found[0]
    source, separator, port = activation.partition('.')
    if not separator:
        raise ValueError('Activation must name a declared instance output')
    node_port(source, port, 'Out', 'bool')
    inputs = [p.get('Name') for p in native.findall('Ports/Port')
              if p.get('Direction') == 'In' and p.get('Type') == 'bool']
    conditions = report.get('conditions', {})
    active = report.get('active_port', inputs[0] if len(inputs) == 1 else None)
    if active in conditions or set(inputs) != set(conditions) | {active}:
        raise ValueError('Dialogue condition report does not match its input ports')
    for binding in conditions.values():
        if binding.get('kind') == 'engine_function':
            if {k:v for k,v in binding.items() if k != 'kind'} not in ENGINE_PREDICATES.values():
                raise ValueError('Unrecognized native dialogue engine predicate')
        elif binding.get('kind') == 'area_check':
            assets = {n.get('Name'): n.get('Target') or
                      {'SoulAsset': 'Soul', 'TriggerAreaAsset': 'Area'}.get(n.tag)
                      for n in host.findall('Assets/*')}
            if assets.get(binding.get('asset')) != 'Soul' or assets.get(binding.get('area')) != 'Area':
                raise ValueError('Missing or incompatible dialogue area/subject assets')
        elif binding.get('kind') == 'inventory_comparison':
            assets = {n.get('Name') for n in host.findall('Assets/*')}
            if binding.get('asset') not in assets:
                raise ValueError('Missing dialogue inventory subject asset: ' + str(binding.get('asset')))
        else:
            node_port(binding['quest'], binding['output'], 'Out', 'bool')
    declared = {p.get('Name') for p in native.findall('Ports/Port') if p.get('Direction') == 'Out'}
    programs = report.get('action_programs', {})
    if set(programs) & report['actions'].keys() or declared != report['actions'].keys() | programs.keys():
        raise ValueError('Dialogue objective report does not match its output ports')
    for output, action in report['actions'].items():
        dest = node_port(action['quest'], action['input'], 'In', 'trigger')
        ET.SubElement(dest, 'Edge', From=name + '.' + output, To=action['input'])
    relative_path = project + '/' + name + '.xml'
    path = resolve_file(relative_path)
    ET.SubElement(definitions, 'Definition', File=relative_path)
    instance = ET.SubElement(nodes, name, Name=name)
    ET.SubElement(instance, 'Edge', From=activation, To=active)
    condition_outputs = {}
    for port, binding in conditions.items():
        if binding.get('kind') == 'engine_function':
            predicate = name + '_' + port
            if any(n.get('Name') == predicate for n in nodes):
                raise ValueError('Dialogue predicate node collision: ' + predicate)
            ET.SubElement(nodes, 'Function', Name=predicate, MethodName=binding['method'],
                          DeclaringType=binding['declaring_type'])
            ET.SubElement(instance, 'Edge', From=predicate + '.' + binding['output'], To=port)
            condition_outputs[port] = predicate + '.' + binding['output']
        elif binding.get('kind') == 'area_check':
            stem = name + '_' + port
            if any(n.get('Name') == stem for n in nodes):
                raise ValueError('Dialogue area predicate collision')
            # Native fist_fights_common_library/fistfights__before_fight_without_payment.xml
            # evaluates AreaCheck continuously and exposes its IsInside output.
            check = ET.SubElement(nodes, 'Function', Name=stem,
                MethodName='wh::rpgmodule::AreaCheck', DeclaringType='wh::rpgmodule')
            ET.SubElement(check, 'Asset', Name='Souls', Alias=binding['asset'])
            ET.SubElement(check, 'Asset', Name='Areas', Alias=binding['area'])
            output = stem + '.IsInside'
            ET.SubElement(instance, 'Edge', From=output, To=port)
            condition_outputs[port] = output
        elif binding.get('kind') == 'inventory_comparison':
            stem = name + '_' + port
            if any(n.get('Name', '').startswith(stem) for n in nodes):
                raise ValueError('Dialogue inventory predicate collision')
            output = inventory_predicate(nodes, stem, binding)
            ET.SubElement(instance, 'Edge', From=output, To=port)
            condition_outputs[port] = output
        else:
            ET.SubElement(instance, 'Edge', From=binding['quest'] + '.' + binding['output'], To=port)
            condition_outputs[port] = binding['quest'] + '.' + binding['output']
    for port, actions in programs.items():
        stem = name + '_' + port
        if not actions or any(n.get('Name', '').startswith(stem + '_') for n in nodes):
            raise ValueError('Empty or conflicting dialogue effect program: ' + port)
        wire_program(nodes, stem, name + '.' + port, actions, condition_outputs, node_port)
    result[path] = dialogue_blob
    result[container_file] = xml(root)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dialogue-package', type=Path, required=True)
    parser.add_argument('--quest-files', type=Path, required=True)
    parser.add_argument('--project', required=True)
    parser.add_argument('--activation', required=True)
    parser.add_argument('--target', type=Path, required=True)
    parser.add_argument('--source-game', type=Path, required=True, help='Original installation supplying recording-linked facial tracks')
    parser.add_argument('--existing-dubbing', type=Path)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        parser.error('Choose a new staging directory')
    source = args.dialogue_package
    model = json.loads((source / 'dialogue-ir.json').read_text(encoding='utf-8'))
    if model['localization']['locale'] != 'English':
        parser.error('This dubbing adapter currently supports English only')
    report = json.loads((source / 'conversion.json').read_text(encoding='utf-8'))
    media = {}
    for voice in report['voices']:
        path = (source / 'Data' / voice['target']).resolve()
        if not path.is_relative_to((source / 'Data').resolve()):
            raise ValueError('Recording path escapes source package')
        payload = path.read_bytes()
        if hashlib.sha256(payload).hexdigest() != voice['sha256']:
            raise ValueError('Recording differs from its source receipt')
        media[voice['target']] = payload
    with zipfile.ZipFile(args.target / 'Data/Tables.pak') as archive:
        voices = read(archive, 'Libs/Tables/skald/voice.xml')
    dialogue, recordings, receipt = bind_recordings((source / 'dialogue.xml').read_bytes(), model, media, voices)
    files = {p.relative_to(args.quest_files).as_posix(): p.read_bytes() for p in args.quest_files.rglob('*.xml')}
    files = attach_dialogue(files, args.project, dialogue, report, args.activation)
    existing = args.existing_dubbing.read_bytes() if args.existing_dubbing else None
    depot, receipt['dubbing'] = dubbing_index(args.target, recordings, existing)
    from dialogue_facials import FacialImporter
    facial = FacialImporter(args.source_game, args.target)
    try:
        facial.add(recordings)
        facial_resources = facial.resources()
        receipt['facials'] = facial.report()
    finally:
        facial.close()
    strings = ET.Element('Table')
    for key, text in sorted(model['strings'].items()):
        row = ET.SubElement(strings, 'Row')
        for value in (key, text, text):
            ET.SubElement(row, 'Cell').text = value
    outputs = {'Data/Quests/' + path: payload for path, payload in files.items()}
    outputs.update(imported_resources(source, report))
    outputs.update({'Data/' + path: payload for path, payload in facial_resources.items()})
    outputs.update({'Localization/English/' + path: payload for path, payload in recordings.items()})
    outputs['Localization/English/' + DEPOT] = depot
    outputs['Localization/English_xml/text_ui_dialog.xml'] = xml(strings)
    camera = source / 'camera-entities.xml'
    if camera.exists():
        outputs['camera-entities.xml'] = camera.read_bytes()
    for path, payload in outputs.items():
        destination = args.output / path
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(payload)
    receipt.update(source_alias=model['alias'], objective_wiring=report['actions'],
                   activation=args.activation, installed=False, campaign_ready=False,
                   pending=['Actor role and world registration', 'Native dialogue invocation from source behavior',
                            'Animation fragment and facial dependencies', 'Objective reward execution',
                            'Completion, skipping and save/load runtime verification'],
                   files={p: hashlib.sha256(b).hexdigest() for p, b in outputs.items()})
    (args.output / 'runtime-binding.json').write_text(json.dumps(receipt, indent=2), encoding='utf-8')
    print(json.dumps(dict(recordings=len(recordings), objective_ports=len(report['actions']), installed=False)))


if __name__ == '__main__':
    main()
