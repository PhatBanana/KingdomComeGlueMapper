"""Resolve and stage source work-speech roles without enabling unresolved jobs."""
import copy
import re
import xml.etree.ElementTree as E

from campaign_actor_dialogues import register_roles
from campaign_quest_graph import identifier, xml


def resolve(tables, soul_names, requested):
    """Select memberships by source identities, never voice/name proximity."""
    roles = {r['role_id']: r for r in tables['role']}
    metas = {r['metarole_id']: r['metarole_name'] for r in tables['metarole']}
    unknown = set(requested) - set(metas.values())
    if unknown:
        raise ValueError('Unknown source speech metaroles: ' + ', '.join(sorted(unknown)))
    bindings = {}
    for member in tables['soul2role']:
        if member['soul_id'] not in soul_names:
            continue
        role = roles[member['role_id']]
        meta = metas[role['metarole_id']]
        if meta in requested:
            bindings.setdefault(member['soul_id'], {})[role['role_id']] = dict(role, metarole_name=meta)
    bindings = {s: list(rs.values()) for s, rs in bindings.items()}
    selected = {r['role_id'] for rs in bindings.values() for r in rs}
    topics = {r['topic_id'] for r in tables['topictorole'] if r['role_id'] in selected}
    branches = [dict(r) for r in tables['v_branch'] if r['start_topic'] in topics
                and r.get('is_test', '').lower() == 'false']
    return bindings, sorted(branches, key=lambda r: int(r['start_topic']))


def register(resources, bindings, soul_names, native_roles, namespace):
    """Isolate imported work metaroles from native automatic speech consumers.

    Registration alone never enables requests: only the converted source job may
    request the returned namespaced metarole after its policy validates.
    """
    identifier(namespace)
    original = {r['role_id']: r for rs in bindings.values() for r in rs}
    if any(r['metarole_name'] == 'NPC' for r in original.values()):
        raise ValueError('Ordinary NPC roles do not belong in work speech')
    # Reuse the verified Storm membership emitter, then explicitly replace its
    # NPC classification with isolated source metaroles before returning bytes.
    ordinary = {s: [dict(r, metarole_name='NPC') for r in rs] for s, rs in bindings.items()}
    files, mapping = register_roles(resources, ordinary, soul_names, native_roles, namespace)
    names = {r['metarole_name']: namespace + '_' + r['metarole_name'] for r in original.values()}
    for name in names.values():
        identifier(name)
    path = 'Libs/Tables/rpg/metarole__' + namespace + '.xml'
    if path in files:
        raise ValueError('Work metarole namespace already registered')
    root = E.Element('database', name='barbora')
    rows = E.SubElement(root, 'metaroles', version='1')
    for name in sorted(names.values()):
        E.SubElement(rows, 'metarole', metarole_name=name)
    files[path] = xml(root)
    role_path = 'Libs/Tables/rpg/role__' + namespace + '.xml'
    root = E.fromstring(files[role_path])
    for row in root.iter('role'):
        rid = row.get('role_name').removeprefix(namespace + '_')
        row.set('metarole_name', names[original[rid]['metarole_name']])
    files[role_path] = xml(root)
    return files, mapping, names


def partition(models):
    """Keep entire branches dormant if any connected sequence policy is unknown."""
    from campaign_work_speech import assess
    ready, pending = {}, {}
    for topic, model in models.items():
        report = assess(dict(alias=model['alias'], blockers=[], repeat=True,
                             source_path='metarole/topic/' + topic), model)
        if report['speech_contract_supported']:
            ready[topic] = copy.deepcopy(model)
        else:
            pending[topic] = report
    return ready, pending


def dispatch_proof(model, bindings, metarole, source_request, native_dialog):
    """Prove a non-player branch is selected by a source work monologue."""
    if (source_request.get('type') != 'dialog:monologRequest'
            or source_request.get('target') not in ('this.id', '$this.id')
            or not re.search(r"(?:^|,\s*)metarole\('" + re.escape(metarole) + r"'\)(?:,|$)",
                             source_request.get('values', ''))):
        raise ValueError('Source work request does not select this metarole')
    if native_dialog.find(".//Dialog/Dialogue[@Type='ingame monolog']") is None:
        raise ValueError('Native in-game monologue mode is unverified')
    proof = dict(start_topic=model['start_topic'], metarole=metarole,
                 source_request=dict(source_request),
                 memberships={s:[dict(r) for r in rs if r['metarole_name']==metarole]
                              for s,rs in bindings.items()}, native_mode='ingame monolog')
    validate_dispatch(model, proof)
    return proof


def validate_dispatch(model, proof):
    if proof.get('start_topic') != model['start_topic'] or proof.get('native_mode') != 'ingame monolog':
        raise ValueError('Work dispatch proof does not match dialogue')
    request = proof.get('source_request', {})
    if (request.get('type') != 'dialog:monologRequest'
            or request.get('target') not in ('this.id', '$this.id')
            or not re.search(r"(?:^|,\s*)metarole\('" + re.escape(proof['metarole']) + r"'\)(?:,|$)",
                             request.get('values', ''))):
        raise ValueError('Work dispatch proof lacks matching source invocation')
    members = {r['role_id']: r for rs in proof['memberships'].values() for r in rs}
    participants = {p['role_id'] for p in model['participants'] if p['topic_id']==model['start_topic']}
    if not participants or not participants <= members.keys():
        raise ValueError('Work dialogue participants lack source actor memberships')
    for rid in participants:
        if (members[rid]['metarole_name'] != proof['metarole']
                or members[rid]['metarole_id'] != model['roles'][rid]['metarole_id']):
            raise ValueError('Work dialogue metarole membership changed')


def select_recordings(model, soul_id, character_rows, memberships):
    """Resolve a shared bark role to its source actor's recorded voice."""
    characters = [r for r in character_rows if r['soul_id'] == soul_id]
    if len(characters) != 1 or characters[0]['voice_id'] in ('', '0'):
        raise ValueError('Missing or ambiguous source work speaker voice')
    voice = characters[0]['voice_id']
    owned = {r['role_id'] for r in memberships if r['soul_id']==soul_id}
    result = copy.deepcopy(model)
    for topic in result['topics'].values():
        for sequence in topic['sequences']:
            for line in sequence['lines']:
                if not line['response']:
                    continue
                if line['response']['role_id'] not in owned:
                    raise ValueError('Work response belongs to another source speaker')
                recordings = [r for r in line['voices'] if r['voice_id']==voice]
                if len(recordings) != 1:
                    raise ValueError('Source actor has no unique recorded work response')
                line['voices'] = recordings
    return result


def stage_dialogue(model, proof, source, native_voices, source_voices, resources,
                   role_mapping, name, parent_namespace=()):
    """Stage source decisions and audio; invocation stays with the work adapter."""
    from campaign_actor_dialogues import remap_roles
    from campaign_dialogue import emit, voices
    from campaign_dialogue_runtime import bind_recordings
    from dialogue_dubbing import import_source_voices
    from campaign_work_speech import require_supported
    require_supported(dict(alias=model['alias'], blockers=[], repeat=True,
                           source_path='metarole/topic/' + model['start_topic']), model)
    selected = remap_roles(model, role_mapping)
    prefixes = set()
    for topic in selected['topics'].values():
        for sequence in topic['sequences']:
            for line in sequence['lines']:
                if line['response']:
                    if len(line['voices']) != 1:
                        raise ValueError('Select source actor recordings before staging work dialogue')
                    prefixes.add(line['voices'][0]['wave_file'].removesuffix('_' + line['response']['string_name']))
    files, native_voices = import_source_voices(resources, native_voices, source_voices, prefixes)
    blob, conversion = emit(selected, name, [], kind='Dialog', metarole_dispatch=proof)
    audio, provenance = voices(source, selected, name)
    blob, audio, binding = bind_recordings(blob, selected, audio, native_voices,
                                         parent_namespace=parent_namespace)
    return files, blob, audio, dict(conversion=conversion, binding=binding,
        recordings=provenance, source_topic=model['start_topic'],
        requests_enabled=False, runtime_verified=False,
        pending=['Source work selection, approach, animation and cancellation dispatch'] +
                (['Source dialogue presentation commands'] if conversion.get('presentation_pending') else []))


def adapt_hearing(blob, model, hearing_rows, native_example):
    """Convert source CommandHearing to native response hearing overrides.

    Retail command factory enum 8 constructs C_CommandHearing (see proof doc).
    Require a same-range native example rather than guessing supported enums.
    """
    root = E.fromstring(blob)
    ranges = {r['dialogue_hearing_id']:r['dialogue_hearing_name'] for r in hearing_rows}
    supported = {n.get(k) for n in native_example.iter() for k in ('Hearing','HearingOverride') if n.get(k)}
    receipt=[]
    for topic in model['topics'].values():
        for seq in topic['sequences']:
            active={}
            for line in seq['lines']:
                for command in line['commands']:
                    if command['dialogue_command_type']!='8':continue
                    if command.get('char_param') or command.get('target','0')!='0' or command.get('delay'):
                        raise ValueError('Unsupported delayed or targeted source hearing command')
                    name=ranges.get(command['int_param'],'')
                    match=re.fullmatch(r'bark([1-9][0-9]*)',name)
                    if not match or match[1] not in supported:
                        raise ValueError('Source hearing range lacks native contract')
                    active[command['who']]=match[1]
                response=line['response']
                if not response:continue
                if response['role_id'] not in active:
                    raise ValueError('Work response has no explicit source hearing command')
                matches=[n for n in root.iter('Response') if n.find("Text[@StringName='"+response['string_name']+"']") is not None]
                if len(matches)!=1:raise ValueError('Ambiguous native work response')
                matches[0].set('HearingOverride',active[response['role_id']])
                receipt.append(dict(response=response['string_name'],hearing=active[response['role_id']]))
    return xml(root),receipt

def bind_entry_speaker(blob, native_example):
    """Mirror native metarole discovery on a command-only entry sequence."""
    native=native_example.find('.//Dialogue/Decision/Sequences/Sequence/Elements/Response')
    if native is None or not native.get('Role') or native.find('Text') is not None:
        raise ValueError('Native empty speaker-selection contract is unavailable')
    root=E.fromstring(blob);dialogue=root.find('.//Dialogue')
    roles={n.get('Role') for n in dialogue.findall('SelectedSouls/SelectedSoul')}
    if len(roles)!=1:raise ValueError('Ambient work entry requires a single source-bound speaker')
    for sequence in dialogue.findall('Decision/Sequences/Sequence'):
        elements=sequence.find('Elements')
        if elements is None or len(elements) or sequence.get('EndType') not in (None,'Decision','EndDialogue'):
            raise ValueError('Unsupported source work entry: expected command-only decision')
        E.SubElement(elements,'Response',Role=next(iter(roles)))
    return xml(root)
