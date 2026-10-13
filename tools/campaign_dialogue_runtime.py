"""Bind imported dialogue audio and objective ports to native registrations.

No scene is selected or launched here. Actor placement, invocation and animation
dependencies remain owned by the campaign/world importers.
"""
import argparse
import hashlib
import json
from pathlib import Path
import xml.etree.ElementTree as ET
import zipfile

from campaign_quest_graph import identifier, xml
from dialogue_dubbing import ogg_duration, dubbing_index, DEPOT
from upgrade_map import read


def bind_recordings(blob, model, media, native_voices, language='ENG'):
    """Use original recorded speakers and native VoiceNamespace lookup paths."""
    root = ET.fromstring(blob)
    host = list(root.find('Skald'))[0]
    name = host.get('Name')
    identifier(name)
    if host.tag not in ('ForcedDialog', 'FaderDialog'):
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
                              path='dialog/' + name.lower() + '/' + stem + '.ogg')
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
    return xml(root), output, dict(roles=roles, responses=list(recordings.values()),
                                   runtime_verified=False)


def attach_dialogue(files, project, dialogue_blob, report, activation):
    """Wire source objective effects, validating the actual destination ports.

    activation is a declared bool output on an existing project node. This
    function cannot synthesize a startup event or substitute a constant true.
    """
    identifier(project)
    result = dict(files)
    root = ET.fromstring(files[project + '.xml'])
    host = root.find('./Skald/Project')
    definitions, nodes = host.find('Definitions'), host.find('Nodes')
    definition_paths = {ET.fromstring(files[d.get('File')]).find('Skald')[0].get('Name'): d.get('File')
                        for d in definitions}
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
        node_port(binding['quest'], binding['output'], 'Out', 'bool')
    declared = {p.get('Name') for p in native.findall('Ports/Port') if p.get('Direction') == 'Out'}
    if declared != report['actions'].keys():
        raise ValueError('Dialogue objective report does not match its output ports')
    for output, action in report['actions'].items():
        dest = node_port(action['quest'], action['input'], 'In', 'trigger')
        ET.SubElement(dest, 'Edge', From=name + '.' + output, To=action['input'])
    path = project + '/' + name + '.xml'
    ET.SubElement(definitions, 'Definition', File=path)
    instance = ET.SubElement(nodes, name, Name=name)
    ET.SubElement(instance, 'Edge', From=activation, To=active)
    for port, binding in conditions.items():
        ET.SubElement(instance, 'Edge', From=binding['quest'] + '.' + binding['output'], To=port)
    result[path] = dialogue_blob
    result[project + '.xml'] = xml(root)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dialogue-package', type=Path, required=True)
    parser.add_argument('--quest-files', type=Path, required=True)
    parser.add_argument('--project', required=True)
    parser.add_argument('--activation', required=True)
    parser.add_argument('--target', type=Path, required=True)
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
    strings = ET.Element('Table')
    for key, text in sorted(model['strings'].items()):
        row = ET.SubElement(strings, 'Row')
        for value in (key, text, text):
            ET.SubElement(row, 'Cell').text = value
    outputs = {'Data/Quests/' + path: payload for path, payload in files.items()}
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
