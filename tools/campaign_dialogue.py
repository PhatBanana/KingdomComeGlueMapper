"""Import connected retail dialogue decisions, voices and objective callbacks.

The source is the installed game database, never a rewritten conversation.
Native presentation differences remain in the report. Unsupported gameplay
conditions/actions fail emission instead of turning into successful no-ops.
"""
import argparse
import copy
from collections import defaultdict, deque
import hashlib
import json
import math
from pathlib import Path, PurePosixPath
import re
import xml.etree.ElementTree as ET
import zipfile

from campaign_sources import retail_sources
from campaign_quest_graph import definition, identifier, xml
from upgrade_map import read
from campaign_entity_links import native_guid
from campaign_dialogue_conditions import QuestConditions


TABLES = ('topic', 'topic2sequence', 'sequence', 'sequence_line', 'response',
          'v_dialogue_commands', 'v_response_wave_file_recorded',
          'sequence2quest_objective', 'sequence_flowchart', 'topictorole',
          'v_branch', 'v_topic2subchapter_id', 'dialogue_mood')


def unique_index(rows, key):
    result = {}
    for row in rows:
        identity = row[key]
        if identity in result: raise ValueError('Duplicate ' + key + ': ' + identity)
        result[identity] = row
    return result


def group(rows, key):
    result = defaultdict(list)
    for row in rows: result[row[key]].append(row)
    return result


def resolve(tables, alias=None, *, start_topic=None):
    topics = unique_index(tables['topic'], 'topic_id')
    sequences = unique_index(tables['sequence'], 'sequence_id')
    membership = group(tables['topic2sequence'], 'topic_id')
    if (alias is None) == (start_topic is None):
        raise ValueError('Select exactly one dialogue alias or source start topic')
    if start_topic is not None:
        start = str(start_topic)
        if start not in topics or not any(r['start_topic'] == start for r in tables['v_branch']):
            raise ValueError('Source start topic is not a registered dialogue branch: ' + start)
        alias = topics[start]['label']
    else:
        if not alias: raise ValueError('Empty dialogue alias; use its source start topic')
        starts = [r for r in topics.values() if r['label'] == alias]
        if len(starts) != 1: raise ValueError('Dialogue alias is missing or ambiguous: ' + alias)
        start = starts[0]['topic_id']
    queue, selected, seq_ids = deque([start]), {}, set()
    while queue:
        tid = queue.popleft()
        if tid in selected: continue
        if tid not in topics or tid not in membership: raise ValueError('Missing dialogue decision: ' + tid)
        entries = sorted(membership[tid], key=lambda r: (int(sequences[r['sequence_id']]['priority']), int(r['sequence_id'])))
        selected[tid] = dict(source=topics[tid], sequences=[])
        for entry in entries:
            sid = entry['sequence_id']; row = sequences[sid]; seq_ids.add(sid)
            selected[tid]['sequences'].append(dict(source=row, entry=entry))
            if row['next'] != '0': queue.append(row['next'])
    lines = group(tables['sequence_line'], 'sequence_id')
    responses = unique_index(tables['response'], 'sequence_line_id')
    commands = group(tables['v_dialogue_commands'], 'sequence_line_id')
    waves = group(tables['v_response_wave_file_recorded'], 'sequence_line_id')
    effects = group(tables['sequence2quest_objective'], 'sequence_id')
    charts = group(tables['sequence_flowchart'], 'sequence_line_id')
    for topic in selected.values():
        for sequence in topic['sequences']:
            sid = sequence['source']['sequence_id']
            sequence['effects'] = sorted(effects[sid], key=lambda r: int(r['order_by']))
            sequence['lines'] = []
            seen_orders = set()
            for line in sorted(lines[sid], key=lambda r: int(r['order_by'])):
                if line['order_by'] in seen_orders: raise ValueError('Ambiguous dialogue line order')
                seen_orders.add(line['order_by'])
                lid = line['sequence_line_id']
                sequence['lines'].append(dict(source=line, response=responses.get(lid),
                                               commands=commands[lid], voices=waves[lid], flowcharts=charts[lid]))
    return dict(schema=1, alias=alias, start_topic=start, topics=selected,
                participants=tables['topictorole'],
                branch=[r for r in tables['v_branch'] if r['start_topic'] == start],
                subchapter=[r for r in tables['v_topic2subchapter_id'] if r['start_topic'] == start],
                moods=tables['dialogue_mood'], executable=False)


def load(game, alias=None, locale='English', *, start_topic=None):
    if not re.fullmatch(r'[A-Za-z]+', locale): raise ValueError('Invalid locale')
    paths = {n: ('Tables.pak', 'Libs/Tables/text/' + n + '.xml') for n in TABLES}
    paths['role'] = ('Tables.pak', 'Libs/Tables/rpg/role.xml')
    sources = retail_sources(game, paths)
    tables = {n: [dict(r.attrib) for r in ET.fromstring(s['data']).findall('./table/rows/row')]
              for n, s in sources.items()}
    model = resolve(tables, alias, start_topic=start_topic)
    model['roles'] = {r['role_id']: r for r in tables['role']}
    with zipfile.ZipFile(Path(game) / 'Localization' / (locale + '_xml.pak')) as z:
        data = read(z, 'text_ui_dialog.xml')
    keys = set()
    for topic in model['topics'].values():
        for seq in topic['sequences']:
            keys.add(seq['source']['ui_prompt'])
            keys.update(line['response']['string_name'] for line in seq['lines'] if line['response'])
    keys.discard('')
    strings = {}
    for row in ET.fromstring(data).findall('Row'):
        cells = row.findall('Cell')
        if len(cells) < 3: raise ValueError('Unsupported localization row')
        key = cells[0].text
        if key in keys:
            if key in strings: raise ValueError('Duplicate localized dialogue: ' + key)
            strings[key] = ''.join(cells[2].itertext())
    if keys - strings.keys(): raise ValueError('Missing dialogue text: ' + ', '.join(sorted(keys - strings.keys())))
    model['strings'] = strings
    model['provenance'] = {n: s['candidates'] for n, s in sources.items()}
    model['localization'] = dict(locale=locale, entry='text_ui_dialog.xml', sha256=hashlib.sha256(data).hexdigest())
    return model


def presentation_command(command, model):
    """Translate authored dialogue commands into native KCD2 command records.

    Preserve camera identities and fragment/variant requests. Their assets must
    be packaged separately; matching command syntax does not validate the rig.
    """
    role = model['roles'].get(command['who'])
    if role is None:
        raise ValueError('Unresolved presentation role: ' + command['who'])
    attrs = {'Role': role['role_name']}
    delay = command.get('delay', '')
    if delay:
        if not math.isfinite(float(delay)):
            raise ValueError('Non-finite presentation delay')
        attrs['Delay'] = delay
    typ = command['dialogue_command_type']
    if command.get('target', '0') != '0':
        raise ValueError('Unconverted presentation target: ' + command['target'])
    if typ == '1':
        moods = {r['dialogue_mood_id']: r['dialogue_mood_name'] for r in model['moods']}
        if command['int_param'] not in moods:
            raise ValueError('Unknown source facial mood')
        return ET.Element('FacialMoodCommand', attrs, FacialMood=moods[command['int_param']])
    if typ == '2':
        if command['int_param'] != '5' or not command['char_param']:
            raise ValueError('Unconverted non-custom camera command')
        return ET.Element('CameraCommand', attrs, CustomCamera=command['char_param'])
    if typ == '3':
        if not command['char_param'] or int(command['int_param']) < 0:
            raise ValueError('Invalid source animation fragment/variant')
        return ET.Element('AnimationCommand', attrs, FragmentId=command['char_param'],
                          Variant=command['int_param'])
    raise ValueError('Unconverted presentation command type: ' + typ)


def camera_assets(model, level_archive):
    """Resolve dialogue camera references from the supplied source level/layers."""
    names = {c['char_param'] for topic in model['topics'].values()
             for sequence in topic['sequences'] for line in sequence['lines']
             for c in line['commands'] if c['dialogue_command_type'] == '2' and c['int_param'] == '5'}
    found, provenance = {}, {}
    with zipfile.ZipFile(level_archive) as archive:
        for path in archive.namelist():
            normalized = path.replace('\\', '/').lower()
            if normalized != 'objects_mission0.xml' and not (normalized.startswith('layers/') and normalized.endswith('.xml')):
                continue
            data = read(archive, path)
            if not any(name.encode() in data for name in names):
                continue
            for source in ET.fromstring(data).iter('Entity'):
                name = source.get('Name')
                if name not in names:
                    continue
                if source.get('EntityClass') != 'CameraSource' or source.find('CameraProxy') is None:
                    raise ValueError('Referenced camera is not a CameraSource: ' + name)
                if name in found:
                    raise ValueError('Ambiguous source camera: ' + name)
                entity = copy.deepcopy(source)
                entity.attrib.pop('EntityId', None)
                layer = entity.attrib.pop('Layer', '')
                entity.set('EditorLayer', layer)
                guid = source.get('EntityGuid', '')
                if len(guid) != 16:
                    raise ValueError('Unexpected source camera identity: ' + guid)
                entity.set('EntityGuid', native_guid(int(guid, 16)))
                found[name] = entity
                provenance[name] = dict(entry=path, source_guid=guid, target_guid=entity.get('EntityGuid'),
                                        source_sha256=hashlib.sha256(data).hexdigest())
    if names - found.keys():
        raise ValueError('Missing source dialogue cameras: ' + ', '.join(sorted(names - found.keys())))
    root = ET.Element('Objects')
    root.extend(found[name] for name in sorted(found))
    return xml(root), provenance


def emit(model, name, quest_models, active_port='active', kind='FaderDialog', convert_presentation=False):
    identifier(name); identifier(active_port)
    if kind not in ('FaderDialog', 'ForcedDialog'): raise ValueError('Unsupported dialogue mode')
    root, host = definition(kind, name)
    ports = ET.SubElement(host, 'Ports')
    ET.SubElement(ports, 'Port', Name=active_port, Direction='In', Type='bool')
    dialogue = ET.SubElement(host, 'Dialogue', TechnicalStatus='Enabled', AllowGreeting='false',
                             Initiator='Player' if kind == 'FaderDialog' else 'NonPlayer')
    quest_ids = {m['quest_id']: m for m in quest_models}
    actions = {}
    presentation = []
    scripts = []
    visited = set()
    converted_commands = []
    conditions = QuestConditions(quest_models)

    def decision(parent, tid):
        visited.add(tid)
        topic = model['topics'][tid]
        attrs = dict(Name='topic_' + tid)
        if topic['source']['label']: attrs['Alias'] = topic['source']['label']
        d = ET.SubElement(parent, 'Decision', attrs)
        sequences = ET.SubElement(d, 'Sequences')
        for record in topic['sequences']:
            source, entry = record['source'], record['entry']; sid = source['sequence_id']
            if source['type'] != '0' or source['group'] != '0' or source['skill_check_difficulty_id'] or source['reputation'] != '0':
                raise ValueError('Unconverted dialogue selection semantics for sequence ' + sid)
            condition = conditions.compile(entry['entry_condition'])
            if entry['npc_entry_condition']: raise ValueError('Unconverted NPC dialogue condition')
            if tid == model['start_topic']:
                condition = "Port('" + active_port + "')" + (' AND (' + condition + ')' if condition else '')
            attrs = dict(Name='seq_' + sid, EndType='EndDialogue')
            if condition: attrs['EntryCondition'] = condition
            if source['script']:
                # Preserve the actual exit script. This is not evidence that its
                # APIs survived the engine migration; require a live API audit.
                attrs['ExitScript'] = source['script']
                scripts.append(dict(sequence=sid, source=source['script'], runtime_verified=False))
            if source['flags'] != '0':
                presentation.append(dict(kind='sequence_flags', sequence=sid, value=source['flags']))
            s = ET.SubElement(sequences, 'Sequence', attrs)
            if source['ui_prompt']:
                ET.SubElement(s, 'UiPrompt', StringName=source['ui_prompt'], Text=model['strings'][source['ui_prompt']])
            for effect in record['effects']:
                if effect['condition']: raise ValueError('Unconverted conditional dialogue objective action')
                q = quest_ids.get(effect['quest_id'])
                if q is None: raise ValueError('Unregistered dialogue quest ' + effect['quest_id'])
                candidates = [r for r in q['tables']['quest_objective']['rows'] if r['objective_id'] == effect['objective_id']]
                if len(candidates) != 1: raise ValueError('Unresolved dialogue objective')
                verb = {'1': 'start', '2': 'complete', '3': 'cancel'}.get(effect['action'])
                if verb is None: raise ValueError('Unsupported dialogue objective action')
                pname = 'action_' + effect['quest_id'] + '_' + verb + '_' + effect['objective_id']
                if pname not in actions:
                    actions[pname] = dict(quest=q['quest'], input=verb + '_' + candidates[0]['objective_name'], source=effect)
                    ET.SubElement(ports, 'Port', Name=pname, Direction='Out', Type='trigger')
                triggers = s.find('Triggers')
                if triggers is None: triggers = ET.SubElement(s, 'Triggers')
                ET.SubElement(triggers, 'Port', Name=pname)
            elements = ET.SubElement(s, 'Elements')
            pending_commands = []
            for line in record['lines']:
                row = line['source']; typ = row['sequence_line_type']
                if typ == '1':
                    response = line['response']
                    if not response: raise ValueError('Missing source response')
                    role = model['roles'][response['role_id']]['role_name']
                    current_response = ET.SubElement(elements, 'Response', Role=role)
                    ET.SubElement(current_response, 'Text', StringName=response['string_name'], Text=model['strings'][response['string_name']])
                    if pending_commands:
                        commands = ET.SubElement(current_response, 'Commands')
                        for command in pending_commands:
                            converted = presentation_command(command, model)
                            commands.append(converted)
                            converted_commands.append(dict(sequence=sid, response=row['sequence_line_id'],
                                                           source=command, target=dict(tag=converted.tag, **converted.attrib)))
                        pending_commands = []
                elif typ == '5':
                    if not line['commands']: raise ValueError('Missing source dialogue command')
                    # Source camera entities and old gesture variants require
                    # independent conversion; keep the exact commands visible.
                    if convert_presentation:
                        # KCD1 stores commands BEFORE the response they affect.
                        # Attaching to the preceding spoken line shifts every shot.
                        pending_commands.extend(line['commands'])
                    else:
                        presentation.append(dict(kind='response_commands', sequence=sid, line=row, commands=line['commands']))
                elif typ in ('2', '4'):
                    presentation.append(dict(kind='authoring_direction', sequence=sid, line=row))
                else:
                    raise ValueError('Unconverted executable dialogue line type: ' + typ)
            if pending_commands:
                raise ValueError('Presentation commands have no following response in sequence ' + sid)
            nxt = source['next']
            if nxt != '0':
                if nxt in visited:
                    s.set('EndType', 'GoTo'); s.set('GoToDecision', 'topic_' + nxt)
                else:
                    s.set('EndType', 'Decision'); decision(s, nxt)
    decision(dialogue, model['start_topic'])
    for port in conditions.bindings:
        ET.SubElement(ports, 'Port', Name=port, Direction='In', Type='bool')
    return xml(root), dict(actions=actions, conditions=conditions.bindings, active_port=active_port,
                           exit_scripts=scripts, presentation_pending=presentation,
                           converted_commands=converted_commands, presentation_runtime_verified=False,
                           source_alias=model['alias'], native_name=name, kind=kind,
                           topic_count=len(model['topics']), campaign_ready=False)


def voices(game, model, directory):
    directory = PurePosixPath(directory)
    if directory.is_absolute() or '..' in directory.parts or ':' in str(directory): raise ValueError('Invalid voice directory')
    requested = {}
    for topic in model['topics'].values():
        for seq in topic['sequences']:
            for line in seq['lines']:
                if not line['response']: continue
                if not line['voices']: raise ValueError('No recorded voice for ' + line['response']['string_name'])
                for voice in line['voices']:
                    source = 'Dialog/' + voice['path'].zfill(6) + '/' + voice['wave_file'] + '.ogg'
                    target = 'dialog/' + directory.as_posix().lower() + '/' + voice['wave_file'] + '.ogg'
                    if target in requested and requested[target] != source: raise ValueError('Conflicting voice mapping')
                    requested[target] = source
    locale = re.escape(model['localization']['locale'])
    archives = sorted(p for p in (Path(game) / 'Localization').glob('*.pak')
                      if re.fullmatch(r'(?:IPL_)?' + locale + r'(?:-part\d+)?\.pak', p.name, re.I))
    if not archives: raise ValueError('Source language voice packages are unavailable')
    result = {}; report = []
    for archive in archives:
        with zipfile.ZipFile(archive) as z:
            names = {n.lower(): n for n in z.namelist()}
            for target, source in requested.items():
                if source.lower() not in names: continue
                data = read(z, names[source.lower()])
                if not data.startswith(b'OggS'): raise ValueError('Unsupported recorded voice format')
                if target in result and result[target] != data:
                    raise ValueError('Ambiguous voice package precedence: ' + source)
                result[target] = data
                report.append(dict(archive=archive.name, source=names[source.lower()], target=target,
                                   sha256=hashlib.sha256(data).hexdigest()))
    if requested.keys() - result.keys():
        raise ValueError('Missing recorded voices: ' + ', '.join(requested[n] for n in sorted(requested.keys() - result.keys())))
    return result, report


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--kcd1', type=Path, required=True)
    selection = p.add_mutually_exclusive_group(required=True)
    selection.add_argument('--alias')
    selection.add_argument('--start-topic', help='Original database branch start topic, including unnamed branches')
    p.add_argument('--name', required=True)
    p.add_argument('--quest-ir', type=Path, action='append', required=True)
    p.add_argument('--voice-directory', required=True)
    p.add_argument('--locale', default='English')
    p.add_argument('--kind', choices=['FaderDialog', 'ForcedDialog'], default='FaderDialog')
    p.add_argument('--convert-presentation', action='store_true', help='Emit original camera, gesture and facial-mood commands; requires matching assets and runtime testing')
    p.add_argument('--camera-level', type=Path, help='Source level.pak from which referenced custom cameras are converted')
    p.add_argument('--output', type=Path, required=True)
    a = p.parse_args()
    if a.output.exists(): raise FileExistsError('Choose a new staging directory')
    model = load(a.kcd1, a.alias, a.locale, start_topic=a.start_topic)
    data, report = emit(model, a.name, [json.loads(p.read_text(encoding='utf-8')) for p in a.quest_ir], kind=a.kind,
                        convert_presentation=a.convert_presentation)
    audio, report['voices'] = voices(a.kcd1, model, a.voice_directory)
    a.output.mkdir(parents=True)
    (a.output / 'dialogue.xml').write_bytes(data)
    if a.camera_level:
        cameras, report['cameras'] = camera_assets(model, a.camera_level)
        (a.output / 'camera-entities.xml').write_bytes(cameras)
    for name, payload in audio.items():
        path = a.output / 'Data' / name; path.parent.mkdir(parents=True, exist_ok=True); path.write_bytes(payload)
    (a.output / 'dialogue-ir.json').write_text(json.dumps(model, indent=2), encoding='utf-8')
    (a.output / 'conversion.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    print(json.dumps(dict(topics=len(model['topics']), voices=len(audio), objective_callbacks=len(report['actions']), campaign_ready=False)))


if __name__ == '__main__': main()
