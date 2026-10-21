"""Assemble a complete native curriculum behind the source lifecycle contract.

Only the exercises/presentation/combat settings are replaced. The caller must
still supply real source arrival, equipment and release acknowledgements.
"""
import hashlib
import posixpath
import xml.etree.ElementTree as E

from campaign_quest_graph import definition, identifier, edge, xml, any_of
from campaign_native_training import SOUL
from campaign_training_curriculum import emit, _one, _path
from campaign_training_presentation import build, wire

SOULS = 'wh::rpgmodule::Souls'


def settings(archive, source, namespace, symbols, player_alias):
    """Copy native helpers locally, resolving explicit namespace definitions.

    Keep native post-fight grace periods. These helpers are not reconstructed
    from lists of buffs/contexts, and never change the actor's faction.
    """
    identifier(namespace)
    files, evidence, names, visiting = {}, [], {}, set()

    def visit(path):
        path = _path(path, posixpath.basename(path))
        if path in visiting: raise ValueError('Cyclic native combat settings dependency')
        if path in names: return names[path][0]
        visiting.add(path)
        payload = archive.read(path)
        root = E.fromstring(payload)
        host = _one(root.findall('./Skald/Module'), 'native combat settings module')
        old = host.get('Name')
        name = namespace + '_' + hashlib.sha256(path.encode()).hexdigest()[:12]
        host.set('Name', name)
        ports = host.find('Ports')
        if ports is None: raise ValueError('Native combat settings lack a port contract')
        declarations = host.find('Definitions')
        local = {}
        for d in (() if declarations is None else list(declarations)):
            target = _path(path, d.get('File', ''))
            child = _one(E.fromstring(archive.read(target)).findall('./Skald/Module'), 'native helper definition')
            if child.get('Name') in local: raise ValueError('Ambiguous native helper definition')
            local[child.get('Name')] = target
        imported = set()
        for node in host.findall('Nodes/*'):
            ns = node.get('Namespace')
            target = symbols.get((ns, node.tag)) if ns else local.get(node.tag)
            if ns and target is None: raise ValueError('Unresolved native helper namespace: ' + ns + ':' + node.tag)
            if target:
                child_name = visit(target)
                child = E.fromstring(files[child_name + '.xml']).find('./Skald/Module')
                if names[target][1] != node.tag: raise ValueError('Native helper symbol does not match definition')
                contract = {p.get('Name') for p in child.findall('Ports/*') if p.get('Direction') == 'In'}
                supplied = {p.get('To') for p in node.findall('Edge')} | {p.get('Name') for p in node.findall('Constant')}
                if supplied - contract: raise ValueError('Native helper invocation has unknown input ports')
                node.tag = child_name; node.attrib.pop('Namespace', None); imported.add(child_name)
                for p in child.findall('Ports/Port'):
                    if p.get('Name') not in ('gm_player', 'gm_player_souls'): continue
                    existing = ports.find("*[@Name='" + p.get('Name') + "']")
                    if existing is None: ports.append(E.fromstring(E.tostring(p)))
                    elif existing.attrib != p.attrib: raise ValueError('Native settings player port collision')
                    edge(node, p.get('Name'), p.get('Name'))
            for asset in list(node.findall('Asset')):
                if asset.get('Alias') != player_alias:
                    raise ValueError('Unbound native combat settings asset: ' + str(asset.get('Alias')))
                pair = (node.tag, asset.get('Name'))
                if pair == ('MakeArray', 'A') and node.get('TypeT') == SOULS:
                    port, typ = 'gm_player', SOUL
                elif pair in (('BuffEffect', 'Souls'), ('SetEntityContext', 'Souls')):
                    port, typ = 'gm_player_souls', SOULS
                else:
                    raise ValueError('Native combat settings asset requires a typed conversion')
                existing = ports.find("*[@Name='" + port + "']")
                if existing is None: E.SubElement(ports, 'Port', Name=port, Direction='In', Type=typ)
                elif existing.get('Type') != typ or existing.get('Direction') != 'In':
                    raise ValueError('Native settings player port collision')
                node.remove(asset); edge(node, port, asset.get('Name'))
        if declarations is not None: host.remove(declarations)
        if imported:
            declarations = E.SubElement(host, 'Definitions')
            for child_name in sorted(imported): E.SubElement(declarations, 'Definition', File=child_name + '.xml')
        # Declared but unused designer assets must not become world bindings.
        assets = host.find('Assets')
        if assets is not None: host.remove(assets)
        files[name + '.xml'] = xml(root)
        evidence.append(dict(file=path, sha256=hashlib.sha256(payload).hexdigest()))
        names[path] = (name, old); visiting.remove(path)
        return name

    name = visit(source)
    return files, name, evidence


def assemble(archive, source, domain, namespace, role_bindings, *, optional_roles=(),
             effect_roles, settings_source, settings_symbols, player_alias):
    """Emit one module with native presentation wired to the source lifecycle.

    effect_roles maps native root asset aliases to 'tutor'/'player'. No actor,
    quest, location, equipment identity or source objective is hardcoded here.
    QuestAdditions must be installed in the receiving quest by its assembler.
    """
    identifier(namespace)
    if any(role not in ('tutor', 'player') for role in effect_roles.values()):
        raise ValueError('Native lesson effects require a bound tutor or player')
    lifecycle_name = namespace + '_lifecycle'
    lifecycle, report = emit(lifecycle_name, archive, source, domain)
    presentation_name = namespace + '_presentation'
    presentation, additions, presentation_report = build(archive, source, domain, presentation_name,
        role_bindings, optional_roles=optional_roles,
        asset_ports={a: r + '_souls' for a, r in effect_roles.items()})
    helpers, helper_name, helper_evidence = settings(archive, settings_source,
        namespace + '_settings', settings_symbols, player_alias)
    helper = E.fromstring(helpers[helper_name + '.xml']).find('./Skald/Module')
    helper_ports = {p.get('Name'): p.get('Type') for p in helper.findall('Ports/*') if p.get('Direction') == 'In'}
    expected = dict(isactive='bool', trainers=SOULS, gm_player=SOUL, gm_player_souls=SOULS)
    if helper_ports != expected:
        raise ValueError('Native training settings contract changed')
    root, host = definition('Module', namespace)
    ports = E.SubElement(host, 'Ports'); declarations = E.SubElement(host, 'Definitions')
    nodes = E.SubElement(host, 'Nodes'); output = E.SubElement(nodes, 'Output', Name='Output')
    life = E.SubElement(nodes, lifecycle_name, Name=lifecycle_name)
    display = E.SubElement(nodes, presentation_name, Name=presentation_name)
    wire(nodes, life, display)
    # Dialogue acknowledgements are owned by the imported native presentation,
    # not exposed as a second way for the source to skip exercises.
    for p in E.fromstring(lifecycle).findall('./Skald/Module/Ports/*'):
        name = p.get('Name')
        if name in ('instruction_ack', 'ack_phase'): continue
        ports.append(E.fromstring(E.tostring(p)))
        if p.get('Direction') == 'In':
            if name != 'dialogue_busy': edge(life, name, name)
        else: edge(output, lifecycle_name + '.' + name, name)
    E.SubElement(ports, 'Port', Name='player', Direction='In', Type=SOUL)
    edge(life, any_of(nodes, 'gm_dialogue_busy', ['dialogue_busy', presentation_name + '.dialogue_busy']), 'dialogue_busy')
    edge(life, presentation_name + '.dialogue_released', 'dialogue_finished')
    for role in ('tutor', 'player'):
        array = E.SubElement(nodes, 'MakeArray', Name=role + '_souls', TypeT=SOULS)
        edge(array, role, 'A')
    for port in set(presentation_report['asset_ports'].values()): edge(display, port + '.Array', port)
    protection = E.SubElement(nodes, helper_name, Name='settings')
    for target, value in dict(isactive=lifecycle_name + '.training_active', trainers='tutor_souls.Array',
                              gm_player='player', gm_player_souls='player_souls.Array').items():
        edge(protection, value, target)
    for name in (lifecycle_name, presentation_name, helper_name):
        E.SubElement(declarations, 'Definition', File=name + '.xml')
    files = {**helpers, **presentation, lifecycle_name + '.xml': lifecycle, namespace + '.xml': xml(root)}
    report.update(root=namespace + '.xml', presentation=presentation_report, settings=helper_evidence,
        required_host_bindings=[p.get('Name') for p in ports if p.get('Direction') == 'In'],
        ready_for_game_test=False, installed=False,
        remaining=['source request/arrival and equipment controller bindings',
                   'native recording relocation in final quest namespace', 'in-game validation'])
    return files, additions, report


def bind_resources(files, report, directory, game, voices, characters, dubbing, lookup,
                   *, existing_facial_index):
    """Bind speech only after the lesson exists in a rooted quest hierarchy.

    The caller supplies its current combined facial index (None for a clean
    native baseline). Returning a combined index preserves prior KCD1 dialogue
    imports and supports package migration without dropping their facial tracks.
    Inputs and installed packages are never modified.
    """
    from campaign_dialogue_runtime import voice_namespace
    from campaign_training_presentation import recordings
    from dialogue_facials import NativeFacialImporter
    directory = directory.rstrip('/')
    if ('\\' in directory or ':' in directory or directory.startswith('/')
            or '..' in directory.split('/')):
        raise ValueError('Native lesson resource directory must be package-relative')
    def path(name): return posixpath.join(directory, name)
    presentation = report['presentation']
    namespaces = set()
    selected = {}
    for name in presentation['dialogue_sources']:
        scoped = voice_namespace(files, path(name))
        host = _one(E.fromstring(files[path(name)]).findall('./Skald/*'), 'native dialogue')
        if not scoped or scoped[-1] != host.get('Name'):
            raise ValueError('Native dialogue namespace does not match its instance')
        namespaces.add(scoped[:-1]); selected[name] = files[path(name)]
    parent = _one(namespaces, 'shared native lesson voice namespace')
    changed, media, audio_evidence = recordings(selected, presentation, voices, lookup,
        parent_namespace=parent, characters=characters, native_dubbing=dubbing)
    facial = NativeFacialImporter(game, existing_facial_index)
    try:
        facial.add(media)
        facial_files = facial.resources(); facial_report = facial.report()
    finally:
        facial.close()
    result = dict(files)
    result.update({path(name): payload for name, payload in changed.items()})
    return result, media, facial_files, dict(audio=audio_evidence, facials=facial_report,
        voice_namespace=parent, runtime_validated=False)
