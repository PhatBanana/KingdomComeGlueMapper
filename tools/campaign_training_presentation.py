"""Transplant native lesson presentation by graph identity, not phase guesses.

Keeps the engine's alias dispatch, authored instruction cues, feedback, tracker
and tutorial windows. The receiving quest still owns arrival and equipment.
"""
import copy
import hashlib
import posixpath
import xml.etree.ElementTree as E
import zlib

from campaign_quest_graph import definition, identifier, xml, edge, constant, all_of, any_of
from campaign_training_curriculum import resolve, _one, _path


def build(archive, source, domain, namespace, role_bindings, *, optional_roles=(), asset_ports=None):
    """Return a relocatable presentation and explicit quest-scope additions.

    A None binding retains a native role (normally the player). Optional roles
    may only remove passive, unreferenced crowd barks. A missing tutor or a bark
    used by the lesson's control flow is always an error.
    """
    identifier(namespace)
    for role, soul in role_bindings.items():
        identifier(role)
        if soul is not None: identifier(soul)
    optional_roles = set(optional_roles)
    asset_ports = asset_ports or {}
    for alias, port in asset_ports.items(): identifier(alias); identifier(port)
    if optional_roles & set(role_bindings):
        raise ValueError('A participant cannot be both bound and omitted')
    curriculum = resolve(archive, source, domain)
    original = E.fromstring(archive.read(source)).find('./Skald/*')
    original_nodes = original.find('Nodes')
    native = _one(original_nodes.findall('CombatTutorialNode'), 'native tutorial')
    native_name = native.get('Name')
    native_active = _one(native.findall("Edge[@To='IsActive']"), 'native tutorial activation').get('From')
    root, host = definition('Module', namespace)
    ports = E.SubElement(host, 'Ports')
    inputs = dict(active='bool', reset='trigger', stop='trigger', phase='int',
                  phase_started='trigger', phase_skipped='trigger', success='trigger',
                  failure='trigger', finished='trigger', tracker='wh::questmodule::nodes::Tracker')
    for name, typ in inputs.items(): E.SubElement(ports, 'Port', Name=name, Direction='In', Type=typ)
    E.SubElement(ports, 'Port', Name='continue', Direction='Out', Type='trigger')
    E.SubElement(ports, 'Port', Name='dialogue_busy', Direction='Out', Type='bool')
    E.SubElement(ports, 'Port', Name='dialogue_released', Direction='Out', Type='trigger')
    defs = E.SubElement(host, 'Definitions'); nodes = E.SubElement(host, 'Nodes')
    output = E.SubElement(nodes, 'Output', Name='Output')
    native_ports = dict(Phase='phase', OnPhaseStart='phase_started', OnPhaseSkipped='phase_skipped',
                        OnSuccessEvent='success', OnFailEvent='failure', OnTutorialEnd='finished', Tracker='tracker')
    by_name = {n.get('Name'): n for n in original_nodes}
    selected = {p['module_instance'] for p in curriculum['phases']}
    def local_dependencies(node):
        pending, visited, anchored = [node], set(), False
        while pending:
            current = pending.pop()
            if current.get('Name') in visited: continue
            visited.add(current.get('Name'))
            for e in current.findall('Edge'):
                value = e.get('From', ''); ref = value.split('.', 1)[0]
                if value == native_active or ref == native_name:
                    anchored = True
                elif ref in by_name:
                    pending.append(by_name[ref])
                else:
                    return False
        # A constant-only effect or unrelated local cycle is not evidence of
        # tutorial ownership, even though it has no external input ports.
        return anchored
    # Phase-dependent skill adjustments and tutorial combat contexts are part
    # of the native exercises. Story/arena effects with external input gates
    # remain the caller's responsibility, rather than being enabled globally.
    selected.update(n.get('Name') for n in original_nodes
                    if n.tag in ('BuffEffect', 'SetEntityContext') and local_dependencies(n))
    pending = list(selected)
    while pending:
        node = by_name[pending.pop()]
        for e in node.findall('Edge'):
            if e.get('From') == native_active: continue
            ref = e.get('From', '').split('.', 1)[0]
            if ref == native_name: continue
            if ref not in by_name:
                raise ValueError('Native presentation depends on an external story input: ' + ref)
            if ref not in selected: selected.add(ref); pending.append(ref)
    # The closure deliberately excludes the surrounding wager, duel and camp
    # schedules. It follows every input of every selected exercise module.
    for n in original_nodes:
        if n.get('Name') not in selected: continue
        clone = copy.deepcopy(n)
        for e in clone.findall('Edge'):
            if e.get('From') == native_active:
                e.set('From', 'active'); continue
            ref, sep, port = e.get('From', '').partition('.')
            if ref == native_name:
                if not sep or port not in native_ports: raise ValueError('Unknown native tutorial output')
                e.set('From', native_ports[port])
        for asset in list(clone.findall('Asset')):
            if clone.tag not in ('BuffEffect', 'SetEntityContext') or asset.get('Name') != 'Souls':
                raise ValueError('Native presentation needs an explicit asset type conversion')
            alias = asset.get('Alias')
            if alias not in asset_ports: raise ValueError('Unbound native lesson effect asset: ' + str(alias))
            port = asset_ports[alias]
            declared = ports.find("Port[@Name='" + port + "']")
            if declared is None: E.SubElement(ports, 'Port', Name=port, Direction='In', Type='wh::rpgmodule::Souls')
            elif declared.get('Type') != 'wh::rpgmodule::Souls': raise ValueError('Native effect port collision')
            clone.remove(asset); edge(clone, port, 'Souls')
        if clone.tag in ('BuffEffect', 'SetEntityContext'):
            active = _one(clone.findall("Edge[@To='IsActive']"), 'native effect activation')
            if active.get('From') != 'active':
                active.set('From', all_of(nodes, 'gm_effect_' + clone.get('Name'), ['active', active.get('From')]))
        nodes.append(clone)

    # Native objectives and custom state enums belong to ancestor quest scopes,
    # not the phase files. Return only the definitions actually referenced.
    ancestors = []
    parent = posixpath.dirname(source)
    names = set(archive.namelist())
    while parent.startswith('Quests/Final/'):
        candidate = parent + '.xml'
        if candidate in names:
            ancestors.append((candidate, E.fromstring(archive.read(candidate)).find('./Skald/*')))
        parent = posixpath.dirname(parent)
    types, objectives, files, omitted, dialogue_sources = {}, {}, {}, [], {}

    def inherited(section, attr, name):
        for path, ancestor in ancestors:
            matches = ancestor.findall(section + '/*[@' + attr + "='" + name + "']")
            if matches: return path, copy.deepcopy(_one(matches, 'native inherited definition'))
        raise ValueError('Missing inherited native definition: ' + name)

    def inherit_type(name):
        if name in ('bool', 'int', 'Progress', 'ProgressFailable'): return
        if name not in types:
            path, item = inherited('Types', 'TypeName', name)
            item.set('TypeName', namespace + '_' + name)
            types[name] = item

    def rewrite_types(scope):
        for n in scope.iter():
            for attr in ('TypeT', 'ValueTypes'):
                typ = n.get(attr)
                if typ in ('Progress', 'ProgressFailable'): continue
                if typ and any(typ == t.get('TypeName') for _, a in ancestors for t in a.findall('Types/Type')):
                    inherit_type(typ); n.set(attr, namespace + '_' + typ)

    def lifecycle(scope):
        ps = scope.find('Ports')
        if ps is None: ps = E.SubElement(scope, 'Ports')
        for key in ('active', 'reset', 'stop'):
            if ps.find("Port[@Name='gm_" + key + "']") is not None: raise ValueError('Native lifecycle port collision')
            E.SubElement(ps, 'Port', Name='gm_' + key, Direction='In', Type=inputs[key])
        ns = scope.find('Nodes')
        for n in list(ns):
            if n.tag == 'DisplayTutorial': edge(n, 'gm_stop', 'Hide')
            if n.tag == 'State':
                typ = n.get('TypeT')
                if typ in ('Progress', 'ProgressFailable'):
                    edge(n, 'gm_reset', 'SetNone'); edge(n, 'gm_stop', 'SetNone')
                elif typ == 'int':
                    if n.find("Edge[@To='Value']") is not None or n.find("Constant[@Name='Value']") is not None:
                        raise ValueError('Native counter reset requires an explicit conversion')
                    constant(n, 'Value', '0'); edge(n, 'gm_reset', 'Exec')
            # A bark may finish after cancellation. Do not revive its objective
            # or show its tutorial window after the lesson has stopped.
            for i, e in enumerate(list(n.findall('Edge'))):
                if e.get('To') not in ('SetActive', 'Show'): continue
                gate = E.SubElement(ns, 'If', Name='gm_live_' + n.get('Name') + '_' + str(i))
                edge(gate, e.get('From'), 'Exec'); edge(gate, 'gm_active', 'Condition')
                e.set('From', gate.get('Name') + '.True')

    phase_occupancy = []
    for phase in curriculum['phases']:
        path = phase['module_file']; pr = E.fromstring(archive.read(path)); ph = pr.find('./Skald/*')
        old_name = ph.get('Name'); new_name = namespace + '_phase_' + str(phase['phase'])
        ph.set('Name', new_name)
        phase_nodes = ph.find('Nodes')
        phase_ports = ph.find('Ports')
        if phase_ports is None: phase_ports = E.SubElement(ph, 'Ports')
        for port, typ in (('gm_dialogue_busy', 'bool'), ('gm_dialogue_released', 'trigger')):
            if phase_ports.find("*[@Name='" + port + "']") is not None:
                raise ValueError('Native dialogue activity port collision')
            E.SubElement(phase_ports, 'Port', Name=port, Direction='Out', Type=typ)
        occupied = []
        used_refs = {e.get('From', '').split('.', 1)[0] for n in phase_nodes for e in n.findall('Edge')}
        declarations = ph.find('Definitions')
        for d in list(declarations):
            dp = _path(path, d.get('File'))
            dr = E.fromstring(archive.read(dp)); dh = dr.find('./Skald/*')
            if dh.tag not in ('Dialog', 'ForcedDialog', 'FaderDialog'):
                raise ValueError('Unsupported native phase dependency: ' + dp)
            roles = {r.get('Role') for r in dh.iter('Response')}
            roles.update(r.get('Role') for r in dh.findall('.//SelectedSoul'))
            instances = [n for n in phase_nodes if n.tag == dh.get('Name')]
            if not instances: raise ValueError('Unused native declaration needs explicit handling: ' + dp)
            missing = roles - set(role_bindings)
            if missing:
                if (not roles <= optional_roles or any(len(n) or n.get('Name') in used_refs for n in instances)):
                    raise ValueError('Unbound native lesson participants: ' + ', '.join(sorted(missing)))
                for n in instances: phase_nodes.remove(n)
                declarations.remove(d); omitted.append(dict(file=dp, roles=sorted(roles)))
                continue
            renamed = namespace + '_dialog_' + hashlib.sha256(dp.encode()).hexdigest()[:12]
            dh.set('Name', renamed); dh.set('VoiceNamespace', 'true')
            dialogue = dh.find('Dialogue')
            selections = dialogue.find('SelectedSouls')
            if selections is None: selections = E.SubElement(dialogue, 'SelectedSouls')
            for role in sorted(roles):
                if not selections.findall("SelectedSoul[@Role='" + role + "'][@Language='ENG']"):
                    # Native barks often inherit their original actor's voice.
                    # The recording stage resolves it from the native character
                    # table before the local soul is allowed to change speaker.
                    E.SubElement(selections, 'SelectedSoul', Role=role, Language='ENG', Type='Wave')
            for soul in dh.findall('.//SelectedSoul'):
                binding = role_bindings[soul.get('Role')]
                if binding is not None: soul.set('Soul', binding)
            for n in instances:
                n.tag = renamed
                # The voice resolver uses instance names for explicit namespaces.
                old = n.get('Name'); n.set('Name', renamed)
                for e in phase_nodes.findall('./*/Edge'):
                    value = e.get('From', '')
                    if value.startswith(old + '.'): e.set('From', renamed + value[len(old):])
            d.set('File', renamed + '.xml')
            files[renamed + '.xml'] = xml(dr); dialogue_sources[renamed + '.xml'] = dp
            for n in instances:
                busy = E.SubElement(phase_nodes, 'State', Name='gm_talking_' + n.get('Name'), TypeT='bool')
                constant(busy, 'DefaultValue', 'false')
                edge(busy, n.get('Name') + '.BeforePlay', 'SetTrue')
                released = E.SubElement(phase_nodes, 'SceneFinishedWaiter', Name=busy.get('Name') + '_release')
                edge(released, n.get('Name') + '.AfterPlay', 'Enqueue')
                order = E.SubElement(phase_nodes, 'TriggerSequence', Name=busy.get('Name') + '_released')
                edge(order, released.get('Name') + '.OnFinished', 'Exec')
                edge(busy, order.get('Name') + '.A', 'SetFalse')
                edge(_one(phase_nodes.findall('Output'), 'phase output'), order.get('Name') + '.B', 'gm_dialogue_released')
                # Stop/reset cannot pretend a still-running scene has released
                # its actors. Retain occupancy until its actual release event.
                occupied.append(busy.get('Name') + '.State')
            if dp == phase['instruction_file'] and phase['custom_step']:
                instruction = _one(instances, 'native phase instruction instance')
                ps = ph.find('Ports')
                if ps is None: ps = E.SubElement(ph, 'Ports')
                E.SubElement(ps, 'Port', Name='gm_instruction_released', Direction='Out', Type='trigger')
                cue = E.SubElement(phase_nodes, 'State', Name='gm_instruction_pending', TypeT='bool')
                constant(cue, 'DefaultValue', 'false')
                cue_gate = E.SubElement(phase_nodes, 'If', Name='gm_live_instruction_cue')
                edge(cue_gate, instruction.get('Name') + '.' + phase['instruction_port'], 'Exec')
                edge(cue_gate, 'gm_active', 'Condition')
                edge(cue, cue_gate.get('Name') + '.True', 'SetTrue')
                edge(cue, 'gm_reset', 'SetFalse'); edge(cue, 'gm_stop', 'SetFalse')
                waiter = E.SubElement(phase_nodes, 'SceneFinishedWaiter', Name='gm_instruction_release')
                edge(waiter, instruction.get('Name') + '.AfterPlay', 'Enqueue')
                valid = E.SubElement(phase_nodes, 'If', Name='gm_instruction_had_cue')
                edge(valid, waiter.get('Name') + '.OnFinished', 'Exec')
                edge(valid, cue.get('Name') + '.State', 'Condition')
                order = E.SubElement(phase_nodes, 'TriggerSequence', Name='gm_instruction_ack')
                edge(order, valid.get('Name') + '.True', 'Exec')
                edge(cue, order.get('Name') + '.A', 'SetFalse')
                edge(_one(phase_nodes.findall('Output'), 'phase output'), order.get('Name') + '.B', 'gm_instruction_released')
        declared_names = {E.fromstring(files[d.get('File')]).find('./Skald/*').get('Name') for d in declarations}
        for n in phase_nodes:
            if n.tag in declared_names or n.get('RequiredForOutput') is None: continue
            if n.tag == 'State': continue
            _, obj = inherited('Objectives', 'Name', n.tag)
            if obj.findall('.//*[@Marker]'):
                raise ValueError('Native lesson objective requires a world marker conversion')
            objectives.setdefault(n.tag, obj)
            obj.set('Name', namespace + '_' + n.tag)
            n.tag = namespace + '_' + n.tag
        edge(_one(phase_nodes.findall('Output'), 'phase output'), any_of(phase_nodes, 'gm_speech_busy', occupied), 'gm_dialogue_busy')
        lifecycle(ph); rewrite_types(ph)
        from training_presentation_repair import guard_progress
        guard_progress(ph)
        files[new_name + '.xml'] = xml(pr)
        instance = _one((n for n in nodes if n.get('Name') == phase['module_instance']), 'phase instance')
        instance.tag = new_name
        instance.set('Name', new_name)
        for e in nodes.findall('./*/Edge'):
            value = e.get('From', '')
            if value.startswith(phase['module_instance'] + '.'):
                e.set('From', new_name + value[len(phase['module_instance']):])
        for key in ('active', 'reset', 'stop'): edge(instance, key, 'gm_' + key)
        E.SubElement(defs, 'Definition', File=new_name + '.xml')
        phase_occupancy.append(new_name + '.gm_dialogue_busy')
        edge(output, new_name + '.gm_dialogue_released', 'dialogue_released')
        if phase['custom_step']:
            check = E.SubElement(nodes, 'IfFunction', Name='gm_instruction_' + str(phase['phase']),
                TypeT='int', MethodName='Control::Compare', DeclaringType='Control')
            constant(check, 'Op', 'Equals'); constant(check, 'ValueB', phase['phase'])
            edge(check, 'phase', 'ValueA'); edge(check, new_name + '.gm_instruction_released', 'Exec')
            gate = E.SubElement(nodes, 'If', Name=check.get('Name') + '_live')
            edge(gate, check.get('Name') + '.True', 'Exec'); edge(gate, 'active', 'Condition')
            edge(output, gate.get('Name') + '.True', 'continue')
    edge(output, any_of(nodes, 'gm_any_speech_busy', phase_occupancy), 'dialogue_busy')
    rewrite_types(host)
    for n in nodes.findall('State'):
        typ = n.get('TypeT', '').removeprefix(namespace + '_')
        if typ in types:
            if types[typ].find("StateTypeEnumeration[@Name='None']") is None:
                raise ValueError('Native presentation state lacks an inactive value')
            edge(n, 'reset', 'SetNone'); edge(n, 'stop', 'SetNone')
    from training_presentation_repair import guard_progress
    guard_progress(host)
    files[namespace + '.xml'] = xml(root)
    additions = E.Element('QuestAdditions')
    ts = E.SubElement(additions, 'Types'); ts.extend(types.values())
    os = E.SubElement(additions, 'Objectives'); os.extend(objectives.values())
    rewrite_types(os)
    return files, xml(additions), dict(curriculum=curriculum, root=namespace + '.xml',
        dialogue_sources=dialogue_sources, omitted_passive_barks=omitted,
        asset_ports=asset_ports,
        dispatch='native aliases; no explicit EnqueueDialogue', runtime_validated=False)


def wire(nodes, lifecycle, presentation):
    """Connect the native presentation to an emitted acknowledged lifecycle."""
    name = identifier(lifecycle.get('Name')); target = identifier(presentation.get('Name'))
    if (list(presentation) or any(e.get('To') in ('instruction_ack', 'ack_phase')
                                for e in lifecycle.findall('Edge'))):
        raise ValueError('Native lesson presentation is already connected')
    for key, source in dict(active='training_active', reset='arrive', stop='stop_workers',
                            phase='phase', phase_started='phase_started', phase_skipped='phase_skipped',
                            success='success', failure='failure', tracker='tracker').items():
        edge(presentation, name + '.' + source, key)
    # Cancellation also stops workers. It must never mark native objectives
    # completed; only the actual tutorial end advances their final phase.
    edge(presentation, name + '.exercises_finished', 'finished')
    edge(lifecycle, target + '.continue', 'instruction_ack')
    edge(lifecycle, name + '.phase', 'ack_phase')


def recordings(files, report, voices, lookup, *, parent_namespace, characters, native_dubbing):
    """Relocate existing native recordings without changing their text/voice.

    lookup(stem) must resolve one native recording, returning (path, bytes).
    The caller supplies the actual instantiated parent voice namespace, as
    resolved by campaign_dialogue_runtime.voice_namespace after quest assembly.
    No global soul voice or localization table is replaced.
    """
    from dialogue_dubbing import ogg_duration
    for segment in parent_namespace: identifier(segment)
    catalog = {}
    by_id = {}
    for voice in E.fromstring(voices).iter('voice'):
        catalog.setdefault(voice.get('voice_technical_name'), []).append(voice.get('abbreviation'))
        by_id.setdefault(voice.get('voice_id'), []).append(voice.get('voice_technical_name'))
    roles = {}
    for character in E.fromstring(characters).iter('skald_character'):
        roles.setdefault(character.get('master_role_name'), []).append(character.get('voice_id'))
    durations = {}
    for row in E.fromstring(native_dubbing).iter('DialogueDubbing'):
        durations.setdefault(row.get('FileHash'), []).append(float(row.get('Duration')))
    result, media, evidence = dict(files), {}, []
    for path, source in report['dialogue_sources'].items():
        root = E.fromstring(files[path]); host = root.find('./Skald/*')
        selected = {}
        for s in host.findall('.//SelectedSoul'):
            if s.get('Language') == 'ENG':
                if not s.get('Voice'):
                    voice_id = _one(roles.get(s.get('Role'), []), 'native role character')
                    s.set('Voice', _one(by_id.get(voice_id, []), 'native character voice'))
                selected.setdefault(s.get('Role'), []).append(s)
        folder = '/'.join((*parent_namespace, host.get('Name'))).lower()
        for response in host.iter('Response'):
            text = response.find('Text')
            if text is None and not len(response) and set(response.attrib) == {'Role'}:
                # Authored silent response placeholders still carry participant
                # and sequence identity. Preserve them without inventing audio.
                continue
            if text is None or not text.get('StringName'):
                raise ValueError('Native instruction response lacks its text identity')
            speaker = _one(selected.get(response.get('Role'), []), 'native English speaker')
            abbreviation = _one(catalog.get(speaker.get('Voice'), []), 'native voice abbreviation')
            if not abbreviation: raise ValueError('Native voice has no recording abbreviation')
            stem = abbreviation + '_' + text.get('StringName')
            origin, payload = lookup(stem)
            if posixpath.basename(origin) != stem + '.ogg':
                raise ValueError('Native recording identity mismatch: ' + stem)
            # Some shipped recordings end on a complete page without EOS. They
            # are valid native resources only when their final granule agrees
            # with the shipped dubbing index. Do not relax the source importer.
            duration = ogg_duration(payload, allow_missing_eos=True)
            native_times = durations.get(str(zlib.crc32(stem.encode('utf-8'))), [])
            if not any(abs(t - duration) <= 0.002 for t in native_times):
                raise ValueError('Native recording does not match its dubbing index: ' + stem)
            destination = 'dialog/' + folder + '/' + stem + '.ogg'
            if destination in media and media[destination] != payload:
                raise ValueError('Native instruction recording collision: ' + destination)
            media[destination] = payload
            response.set('ReferenceLength', f'{duration:.6f}')
            evidence.append(dict(dialogue=source, source=origin, destination=destination,
                                 sha256=hashlib.sha256(payload).hexdigest(), duration=duration,
                                 dubbing_index='unchanged native filename hash'))
        result[path] = xml(root)
    return result, media, evidence
