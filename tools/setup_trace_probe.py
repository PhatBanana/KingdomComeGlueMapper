"""Opt-in probe: can a Skald graph reach Lua through an NPC-less SmartEntity?

KCD2 has no Skald node that runs Lua (`ExecuteLua` is a behaviour-tree node), so a quest-state
trace needs a graph -> AI hop. This stage installs the smallest package change that tells, in one
game session, which hop works. It is never part of the normal finalize: apply it by hand (see
`main`) and remove it with `--remove`.

Route A, the shape Tooling's runner (scenario/trace-probe.json) reads:

    gm_trace_probe (Skald Module, instance in the kcd1_travel Level entry, fed by OnWake and
    OnLevelSwitched, the two events behind `kcd1_travel.arrived`)
      EnableBehavior(Behavior='gm_trace_probe', SmartEntity=gm_trace_probe_host, IsActive=active)
      active: true on arrival, false after 5 s, true again 3 s later (the latch test)
      Trace 'GlueTraceProbe skald trace' on arrival (and '... refire' at the second activation)
    AI/gm_trace_probe.xml, tree gm_trace_probe: ExecuteLua(LUA) once, then Wait(-1)

    Retail shape: utils/battle/wakeandbashgate.xml -> SmartEntity battleGateController, behaviour
    wakeAndBashGate (EnableBehavior with Signature="" and no NPC port). **Inference, the reason for
    route B:** that retail tree acts on `$this` (an NPC's hands and weapons), so the behaviour is
    most likely offered to NPCs linked to the controller rather than run by the controller itself.
    With no NPC and no links, route A is expected to stay silent.

Route B, the retail NPC-less idiom (AI/quests/kajicnaPout/so_kajicnaPout.xml and 17 more smart
objects whose own brain runs ExecuteLua in `onUpdate`; wakeandbashgate feeds battleGateController
the same way, InstantSendMessage `_string` -> inbox battle_groupController_init):

    gm_trace_probe_brain_host: SmartEntity with its own brain (brain, subbrain type SmartObject,
    always active) whose onUpdate tree runs ExecuteLua(LUA_BRAIN) once and then loops
    ProcessMessage(inbox) -> ExecuteLua(LUA_MESSAGE).
    The module sends it one `_string` message on arrival and one at the second activation.

All three snippets write the one global the runner prints, with separate fields:

    ticked, n, t          route A (the runner's expectations)
    brain_n, brain_t      route B: the smart object's own brain started
    msg_n, msg_t          route B: a Skald message reached Lua (edge-triggered, queued)

Not runtime-verified. Unknowns beyond the routes themselves: whether the AI table patches
(`brain__*.xml` and friends; the installed package has none yet) are merged, and whether a smart
object far from the player updates (the hosts are placed at an existing host, see ANCHORS).
"""
import argparse
import hashlib
import json
from pathlib import Path
import sys
import uuid
import xml.etree.ElementTree as ET
import zipfile

from campaign_entity_links import append_links, native_guid
from campaign_quest_graph import constant, definition, edge, xml

VERSION = 1
NAME = 'gm_trace_probe'
HOST = 'gm_trace_probe_host'
BRAIN_HOST = 'gm_trace_probe_brain_host'
BRAIN = 'gm_trace_probe_brain'
BRAIN_TREE = 'onUpdate'
TRACE_TEXT = 'GlueTraceProbe skald trace'
OFF_AFTER, ON_AFTER = '5s', '3s'

TRAVEL = 'Data/gluemappertravel.pak'
LEVEL_PAK = 'Data/Levels/kcd1_travel/level.pak'
PROJECT = 'Quests/GlueTravel/GlueTravel_kcd1.xml'
ENTRY = 'Quests/GlueTravel/entry/kcd1_travel.xml'
MODULE = 'Quests/GlueTravel/gm_trace_probe/gm_trace_probe.xml'
MODULE_REFERENCE = '../gm_trace_probe/gm_trace_probe.xml'    # from the entry's folder
TREES = 'AI/gm_trace_probe.xml'
TREE_FILE = 'gm_trace_probe.xml'                             # as tables name it, relative to AI/
MARKER = 'Libs/GlueMapper/trace_probe.json'
OBJECTS, WAITING = 'objects_mission0.xml', 'waitinglinks.xml'
DEFINITIONS = 'Libs/concept/definitions.xml'
SMART_OBJECT = 'wh::xgenaimodule::SmartObject*'
LEVEL_EVENTS = ('OnWake', 'OnLevelSwitched')
# The hosts go where a smart object is already known to load: the first of these in the level,
# else the project entity.
ANCHORS = ('gm_intro_q_tutorial_swordOne_vanek_idle_host',)

_INIT = 'local g=GlueTraceProbe if not g then g={n=0,first_t=Calendar.GetWorldTime()} GlueTraceProbe=g end '
# Tooling's snippet, byte for byte.
LUA = _INIT + 'g.ticked=true g.n=g.n+1 g.t=Calendar.GetWorldTime()'
LUA_BRAIN = _INIT + 'g.brain_n=(g.brain_n or 0)+1 g.brain_t=Calendar.GetWorldTime()'
LUA_MESSAGE = _INIT + 'g.msg_n=(g.msg_n or 0)+1 g.msg_t=Calendar.GetWorldTime()'

# Retail inbox reused for route B (Tables.pak ai/mailbox.xml, filter type `string`, consume): the
# one wakeandbashgate's `_string` message lands in. Only this probe's brain is bound to it here.
MAILBOX_ID, MAILBOX_NAME = 'bc236a46-5482-45b3-96f3-33aa50778764', 'battle_groupController_init'


def _guid(kind):
    return str(uuid.uuid5(uuid.NAMESPACE_URL, 'kingdomcomegluemapper/' + NAME + '/' + kind))


TEMPLATE_ID, BRAIN_TEMPLATE_ID = _guid('template'), _guid('brain_template')
BRAIN_ID, SUBBRAIN_ID = _guid('brain'), _guid('subbrain')
HOST_GUIDS = {name: native_guid(uuid.uuid5(uuid.NAMESPACE_URL, 'kingdomcomegluemapper/' + name).int & ((1 << 64) - 1))
              for name in (HOST, BRAIN_HOST)}
TEMPLATES = {HOST: TEMPLATE_ID, BRAIN_HOST: BRAIN_TEMPLATE_ID}


def label(alias):
    return "asset['" + alias + "']"


# ---------------------------------------------------------------- emitted files

def module():
    root, host = definition('Module', NAME)
    ports = ET.SubElement(host, 'Ports')
    ET.SubElement(ports, 'Port', Name='arrive', Direction='In', Type='trigger')
    for name in ('host', 'brain_host'):
        ET.SubElement(ports, 'Port', Name=name, Direction='In', Type=SMART_OBJECT)
    nodes = ET.SubElement(host, 'Nodes')
    active = ET.SubElement(nodes, 'State', Name='active', TypeT='bool')
    constant(active, 'DefaultValue', 'false')
    edge(active, 'arrive', 'SetTrue'); edge(active, 'off.OnFinished', 'SetFalse'); edge(active, 'on.OnFinished', 'SetTrue')
    for name, duration, start in (('off', OFF_AFTER, 'arrive'), ('on', ON_AFTER, 'off.OnFinished')):
        timer = ET.SubElement(nodes, 'Timer', Name=name)
        constant(timer, 'Duration', duration); constant(timer, 'TimeType', 'GameTime')
        edge(timer, start, 'SetRunning')
    # As retail wakeandbashgate: no Signature, no EventSet, no NPC.
    enable = ET.SubElement(nodes, 'EnableBehavior', Name='enable', Signature='', EventSet='')
    constant(enable, 'Behavior', NAME)
    edge(enable, 'host', 'SmartEntity'); edge(enable, 'active.State', 'IsActive')
    for name, text, event in (('trace', TRACE_TEXT, 'arrive'), ('trace_refire', TRACE_TEXT + ' refire', 'on.OnFinished')):
        trace = ET.SubElement(nodes, 'Trace', Name=name, TypeT='string')
        constant(trace, 'Value', text); edge(trace, event, 'Exec')
    # As retail wakeandbashgate: the string content comes from a ConstantPort, not a node constant.
    ET.SubElement(ports, 'ConstantPort', Name='message', Direction='In', Type='string', Value='probe')
    for name, event in (('send', 'arrive'), ('send_refire', 'on.OnFinished')):
        send = ET.SubElement(nodes, 'InstantSendMessage', Name=name, MessageType='_string')
        edge(send, event, 'Exec'); edge(send, 'brain_host', 'Receiver'); edge(send, 'message', 'Content')
    return xml(root)


def _tree(root, name):
    tree = ET.SubElement(root, 'BehaviorTree', name=name, is_function='0')
    variables = ET.SubElement(tree, 'Variables')
    body = ET.SubElement(ET.SubElement(tree, 'Root', OneTimeOnly='false', FailState='Recoverable', saveVersion='2'),
                         'Behavior', canSkip='1')
    return tree, variables, ET.SubElement(body, 'Sequence')


def trees():
    """Both trees. Each runs its first ExecuteLua once per start and then blocks; nothing ticks."""
    root = ET.Element('BehaviorTrees')
    tree, _, sequence = _tree(root, NAME)
    ET.SubElement(sequence, 'ExecuteLua', code=LUA)
    # Retail battleGateController/bashGate: an indefinite wait keeps the behaviour alive while enabled.
    ET.SubElement(sequence, 'Wait', duration="'-1'", timeType='GameTime', doFail='false', variation='', skipInLOD='false')
    ET.SubElement(tree, 'ForestContainer')
    brain, variables, sequence = _tree(root, BRAIN_TREE)
    ET.SubElement(variables, 'Variable', name='message', type='_string', values='', isPersistent='0', form='single')
    ET.SubElement(sequence, 'ExecuteLua', code=LUA_BRAIN)
    # Retail so_kajicnaPout/onUpdate.
    process = ET.SubElement(ET.SubElement(sequence, 'Loop', count='-1'), 'ProcessMessage', Atomic='true',
                            timeout="'-1'", timeType='GameTime', variable='$message', senderInfo='',
                            inbox="'" + MAILBOX_NAME + "'", condition='', answerVar='')
    ET.SubElement(process, 'ExecuteLua', code=LUA_MESSAGE)
    ET.SubElement(brain, 'ForestContainer')
    return xml(root)


def _table(container, row_tag, **row):
    root = ET.Element('database', name='barbora')
    ET.SubElement(ET.SubElement(root, container, version='1'), row_tag, row)
    return xml(root)


def _templates():
    files = {}
    for name, template, brain in ((NAME, TEMPLATE_ID, None), (BRAIN, BRAIN_TEMPLATE_ID, BRAIN_ID)):
        root = ET.Element('database', name='barbora')
        entity = ET.SubElement(ET.SubElement(root, 'SmartEntitys', version='1'), 'SmartEntityTemplate',
                               DatabaseId=template, Name=name, UpdatePriority='false')
        if brain:
            entity.set('BrainId', brain)
        else:
            behavior = ET.SubElement(ET.SubElement(entity, 'BehaviorTemplates'), 'SmartBehaviorTemplate',
                                     Name=NAME, InitialState='Disabled', MaxInstances='-1')
            ET.SubElement(behavior, 'TreeLocation', FileName=TREE_FILE, TreeName=NAME)
        files['Libs/Tables/ai/smartEntity/SmartEntity__' + name + '.xml'] = xml(root)
    return files


def emitted():
    """Every file the probe adds to the travel archive, less the marker."""
    table = lambda name: 'Libs/Tables/ai/' + name + '__' + NAME + '.xml'
    files = {MODULE: module(), TREES: trees(), **_templates()}
    files[table('brain')] = _table('brains', 'brain', brain_id=BRAIN_ID, brain_name=BRAIN)
    files[table('subbrain')] = _table('subbrains', 'subbrain', always_active='true', subbrain_id=SUBBRAIN_ID,
                                      subbrain_name=BRAIN, subbrain_type='4', timeout='0')
    files[table('brain2subbrain')] = _table('brain2subbrains', 'brain2subbrain', brain_id=BRAIN_ID, priority='0',
                                            subbrain_id=SUBBRAIN_ID)
    files[table('subbrain_smart_object')] = _table('subbrain_smart_objects', 'subbrain_smart_object',
                                                   file_name=TREE_FILE, on_update_tree=BRAIN_TREE, subbrain_id=SUBBRAIN_ID)
    files[table('brain2mailbox')] = _table('brain2mailboxs', 'brain2mailbox', brain_id=BRAIN_ID,
                                           mailbox_id=MAILBOX_ID, priority='0')
    return files


# ---------------------------------------------------------------- edits to existing documents

def _one(found, what):
    found = list(found)
    if len(found) != 1:
        raise ValueError('Expected one ' + what + ', found ' + str(len(found)))
    return found[0]


def _instance():
    node = ET.Element(NAME, Name=NAME)
    for event in LEVEL_EVENTS:
        edge(node, event, 'arrive')
    ET.SubElement(node, 'Asset', Name='host', Alias=HOST)
    ET.SubElement(node, 'Asset', Name='brain_host', Alias=BRAIN_HOST)
    return node


def _shape(node):
    return node.tag, sorted(node.attrib.items()), [_shape(child) for child in node]


def bind_entry(blob):
    root = ET.fromstring(blob)
    level = _one(root.findall('Skald/Level'), 'Level entry')
    definitions, nodes = level.find('Definitions'), level.find('Nodes')
    if definitions is None or nodes is None:
        raise ValueError('Level entry has no Definitions or Nodes')
    if any(n.get('Name') == NAME or n.tag == NAME for n in nodes) or any(d.get('File') == MODULE_REFERENCE for d in definitions):
        raise ValueError('Trace probe is already registered in the entry')
    ET.SubElement(definitions, 'Definition', File=MODULE_REFERENCE)
    nodes.append(_instance())
    return xml(root)


def unbind_entry(blob):
    root = ET.fromstring(blob)
    level = _one(root.findall('Skald/Level'), 'Level entry')
    for owner, match in ((level.find('Definitions'), lambda n: n.get('File') == MODULE_REFERENCE),
                         (level.find('Nodes'), lambda n: n.tag == NAME)):
        for node in [n for n in owner if match(n)]:
            owner.remove(node)
    return xml(root)


def bind_project(blob):
    root = ET.fromstring(blob)
    project = _one(root.findall('Skald/Project'), 'Project')
    assets = project.find('Assets')
    if assets is None:
        assets = ET.SubElement(project, 'Assets')
    for alias in (HOST, BRAIN_HOST):
        if any(a.get('Name') == alias for a in assets):
            raise ValueError('Asset alias already used: ' + alias)
        ET.SubElement(assets, 'SmartObjectAsset', Name=alias)
    return xml(root), project.get('Name')


def unbind_project(blob):
    root = ET.fromstring(blob)
    assets = _one(root.findall('Skald/Project'), 'Project').find('Assets')
    for node in [a for a in assets if a.get('Name') in (HOST, BRAIN_HOST)]:
        assets.remove(node)
    return xml(root)


def bind_level(objects_blob, waiting_blob, project_name):
    """Add the two hosts and link them to the project entity as its assets."""
    objects = ET.fromstring(objects_blob)
    names = {e.get('Name') for e in objects}
    guids = {e.get('EntityGuid') for e in objects}
    for name, guid in HOST_GUIDS.items():
        if name in names or guid in guids:
            raise ValueError('Trace probe host already in the level: ' + name)
    project = _one((e for e in objects if e.get('Name') == project_name), 'project entity ' + project_name)
    anchor = next((e for name in ANCHORS for e in objects if e.get('Name') == name), project)
    if not anchor.get('Pos'):
        raise ValueError('Anchor entity has no position: ' + str(anchor.get('Name')))
    links = project.find('EntityLinks')
    if links is None:
        links = ET.SubElement(project, 'EntityLinks')
    next_id = max(int(e.get('EntityId', '0')) for e in objects) + 1
    waiting = []
    for offset, (name, guid) in enumerate(HOST_GUIDS.items()):
        entity = ET.SubElement(objects, 'Entity', Name=name, EntityClass='SmartObjectHolder', EntityGuid=guid,
                               EntityId=str(next_id + offset), Pos=anchor.get('Pos'))
        ET.SubElement(entity, 'Properties', guidSmartObjectType=TEMPLATES[name], bSaved_by_game='0')
        ET.SubElement(links, 'Link', Name=label(name), TargetId=entity.get('EntityId'), TargetGuid=guid)
        waiting.append((project.get('EntityGuid'), guid, label(name)))
    return xml(objects), append_links(waiting_blob, waiting), anchor.get('Name')


def unbind_level(objects_blob, waiting_blob):
    objects = ET.fromstring(objects_blob)
    for entity in [e for e in objects if e.get('Name') in HOST_GUIDS]:
        objects.remove(entity)
    labels = {label(name) for name in HOST_GUIDS}
    for links in objects.iter('EntityLinks'):
        for link in [n for n in links if n.get('Name') in labels]:
            links.remove(link)
    waiting = ET.fromstring(waiting_blob)
    for owner in waiting.iter('WaitingLinks'):
        for link in [n for n in owner if n.get('TargetId') in HOST_GUIDS.values()]:
            owner.remove(link)
    return xml(objects), xml(waiting)


# ---------------------------------------------------------------- retail contracts (needs KCD2)

RETAIL_PORTS = {
    'EnableBehavior': (dict(Name='EnableBehavior'), ('IsActive', 'Behavior', 'SmartEntity')),
    'InstantSendMessage': (dict(MessageType='_string'), ('Exec', 'Receiver', 'Content')),
    'Trace': ({}, ('Exec', 'Value')),
    'Timer': ({}, ('Duration', 'TimeType', 'SetRunning', 'OnFinished')),
}


def verify_definitions(blob):
    """Problems with the retail node definitions this probe is written against."""
    found = {}
    for node in ET.fromstring(blob).find('Nodes'):
        if node.get('TypeName') in RETAIL_PORTS:
            attributes = dict(node.attrib, **{p.get('Name'): p.get('Value') for p in node.iterfind('Properties/Property')})
            ports = {p.get('Name') for kind in ('CompileTimePort', 'RunTimePort') for p in node.iterfind('Ports/' + kind)}
            found.setdefault(node.get('TypeName'), []).append((attributes, ports))
    problems = []
    for kind, (selector, ports) in RETAIL_PORTS.items():
        matches = [p for attributes, p in found.get(kind, []) if all(attributes.get(k) == v for k, v in selector.items())]
        if len(matches) != 1:
            problems.append('retail definition not found once: ' + kind + ' ' + json.dumps(selector))
        elif set(ports) - matches[0]:
            problems.append('retail ' + kind + ' lacks ports ' + ', '.join(sorted(set(ports) - matches[0])))
    return problems


def verify_retail(target):
    """Problems against an installed KCD2: node ports, the reused inbox, tree operations and table shapes."""
    from upgrade_map import read
    target = Path(target)
    problems = []
    with zipfile.ZipFile(target / 'Data/IPL_GameData.pak') as archive:
        problems += verify_definitions(read(archive, DEFINITIONS))
    with zipfile.ZipFile(target / 'Data/Tables.pak') as archive:
        rows = lambda table: list(ET.fromstring(read(archive, 'Libs/Tables/ai/' + table + '.xml'))[0])
        if not any(r.get('mailbox_id') == MAILBOX_ID and r.get('mailbox_name') == MAILBOX_NAME for r in rows('mailbox')):
            problems.append('retail mailbox changed: ' + MAILBOX_NAME)
        if not any(r.get('mailbox_id') == MAILBOX_ID and r.get('type') == 'string' for r in rows('mailbox_filter')):
            problems.append('retail mailbox no longer accepts string: ' + MAILBOX_NAME)
        if not any(r.get('subbrain_type_id') == '4' and r.get('subbrain_type_name') == 'SmartObject' for r in rows('subbrain_type')):
            problems.append('retail subbrain type 4 is not SmartObject')
        for path, blob in emitted().items():
            name = path.rsplit('/', 1)[-1]
            if '/smartEntity/' in path or not path.startswith('Libs/Tables/ai/'):
                continue
            ours = ET.fromstring(blob)[0]
            retail = ET.fromstring(read(archive, 'Libs/Tables/ai/' + name.split('__')[0] + '.xml'))[0]
            known = set().union(*(set(r.attrib) for r in retail))
            if retail.tag != ours.tag or retail[0].tag != ours[0].tag or set(ours[0].attrib) - known:
                problems.append('table shape differs from retail: ' + name)
    from campaign_combat_work import validate
    try:
        validate({TREES: trees()}, target)
    except ValueError as error:
        problems.append(str(error))
    return problems


# ---------------------------------------------------------------- package

def _read(path, names):
    with zipfile.ZipFile(path) as archive:
        present = set(archive.namelist())
        return {n: archive.read(n) for n in names if n in present}


def _rewrite(package, relative, replacements, remove=frozenset()):
    from setup_package_upgrade import rewrite
    rewrite(package, relative, replacements, remove=lambda name: name in remove)


def _digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def audit(package):
    """Problems with an installed probe; [] when it is intact. Reads only."""
    package = Path(package)
    files = emitted()
    travel = _read(package / TRAVEL, [MARKER, PROJECT, ENTRY, *files])
    if MARKER not in travel:
        return ['trace probe is not installed (no ' + MARKER + ')']
    problems = []
    marker = json.loads(travel[MARKER])
    if marker.get('version') != VERSION:
        problems.append('unsupported probe version: ' + str(marker.get('version')))
    for path, blob in files.items():
        if travel.get(path) != blob:
            problems.append('probe file missing or changed: ' + path)
    if TREES in travel:
        codes = [n.get('code') for n in ET.fromstring(travel[TREES]).iter('ExecuteLua')]
        if codes != [LUA, LUA_BRAIN, LUA_MESSAGE]:
            problems.append('ExecuteLua bodies differ from the probe contract')
    entry = ET.fromstring(travel[ENTRY]).find('Skald/Level')
    instances = [n for n in entry.find('Nodes') if n.tag == NAME or n.get('Name') == NAME]
    if len(instances) != 1 or _shape(instances[0]) != _shape(_instance()):
        problems.append('entry instance missing or changed: ' + NAME)
    if sum(d.get('File') == MODULE_REFERENCE for d in entry.find('Definitions')) != 1:
        problems.append('entry does not declare ' + MODULE_REFERENCE + ' once')
    project = ET.fromstring(travel[PROJECT]).find('Skald/Project')
    for alias in (HOST, BRAIN_HOST):
        if [a.tag for a in project.find('Assets') if a.get('Name') == alias] != ['SmartObjectAsset']:
            problems.append('project asset missing or not a SmartObjectAsset: ' + alias)
    level = _read(package / LEVEL_PAK, [OBJECTS, WAITING])
    objects = ET.fromstring(level[OBJECTS])
    owner = [e for e in objects if e.get('Name') == project.get('Name')]
    waiting = {(n.get('SourceId'), n.get('TargetId'), n.findtext('LinkDefinition'))
               for n in ET.fromstring(level[WAITING]).iter('WaitingLink')} if WAITING in level else set()
    for name, guid in HOST_GUIDS.items():
        found = [e for e in objects if e.get('Name') == name]
        if (len(found) != 1 or found[0].get('EntityClass') != 'SmartObjectHolder' or found[0].get('EntityGuid') != guid
                or found[0].find('Properties') is None
                or found[0].find('Properties').get('guidSmartObjectType') != TEMPLATES[name]):
            problems.append('level host missing or changed: ' + name)
            continue
        linked = [l for e in owner for l in e.iterfind('EntityLinks/Link') if l.get('Name') == label(name)]
        if len(owner) != 1 or len(linked) != 1 or linked[0].get('TargetGuid') != guid or linked[0].get('TargetId') != found[0].get('EntityId'):
            problems.append('project entity does not link its asset: ' + name)
        elif (owner[0].get('EntityGuid'), guid, label(name)) not in waiting:
            problems.append('link network lacks the asset link: ' + name)
    return problems


def upgrade(package, source=None, target=None):
    """Install the probe. Idempotent on its marker. Returns (files, report) like every stage.

    source is unused. With target (an installed KCD2) the retail contracts are checked first and
    a mismatch refuses the install. A package without the kcd1_travel entry is left alone.
    """
    package = Path(package)
    if not (package / TRAVEL).is_file() or not (package / LEVEL_PAK).is_file():
        return {}, {}
    files = emitted()
    travel = _read(package / TRAVEL, [MARKER, PROJECT, ENTRY, *files])
    if MARKER in travel:
        problems = audit(package)
        if problems:
            raise ValueError('Installed trace probe is damaged: ' + '; '.join(problems))
        return {}, json.loads(travel[MARKER])
    if PROJECT not in travel or ENTRY not in travel:
        return {}, {}
    if set(files) & set(travel):
        raise ValueError('Trace probe files exist without its marker')
    retail = None
    if target is not None:
        retail = verify_retail(target)
        if retail:
            raise ValueError('Retail contract changed: ' + '; '.join(retail))
    project, project_name = bind_project(travel[PROJECT])
    entry = bind_entry(travel[ENTRY])
    level = _read(package / LEVEL_PAK, [OBJECTS, WAITING])
    objects, waiting, anchor = bind_level(level[OBJECTS], level.get(WAITING, b''), project_name)
    report = dict(version=VERSION, hosts=HOST_GUIDS, anchor=anchor, files=sorted(files),
                  edited=[PROJECT, ENTRY, LEVEL_PAK + ':' + OBJECTS, LEVEL_PAK + ':' + WAITING],
                  hashes={n: hashlib.sha256(b).hexdigest() for n, b in files.items()},
                  retail_contracts='verified' if target is not None else 'not checked (no KCD2 folder given)',
                  runtime_verified=False)
    marker = json.dumps(report, indent=1, sort_keys=True).encode('utf-8')
    # Level first: a travel archive that names hosts the level lacks is the worse half-state.
    _rewrite(package, LEVEL_PAK, {OBJECTS: objects, WAITING: waiting})
    _rewrite(package, TRAVEL, {**files, PROJECT: project, ENTRY: entry, MARKER: marker})
    return {TRAVEL: _digest(package / TRAVEL), LEVEL_PAK: _digest(package / LEVEL_PAK)}, report


def remove(package):
    """Take the probe out again. Returns the changed archives; {} when it is not installed."""
    package = Path(package)
    files = emitted()
    travel = _read(package / TRAVEL, [MARKER, PROJECT, ENTRY])
    if MARKER not in travel:
        return {}
    level = _read(package / LEVEL_PAK, [OBJECTS, WAITING])
    objects, waiting = unbind_level(level[OBJECTS], level[WAITING])
    _rewrite(package, TRAVEL, {PROJECT: unbind_project(travel[PROJECT]), ENTRY: unbind_entry(travel[ENTRY])},
             remove={MARKER, *files})
    _rewrite(package, LEVEL_PAK, {OBJECTS: objects, WAITING: waiting})
    return {TRAVEL: _digest(package / TRAVEL), LEVEL_PAK: _digest(package / LEVEL_PAK)}


def main(argv=None):
    parser = argparse.ArgumentParser(description='Install, check or remove the quest-graph -> Lua transport probe.')
    parser.add_argument('package', type=Path, help='Package root (the folder that holds Data/)')
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument('--check', action='store_true', help='Read-only: FAIL unless the probe is installed and intact')
    modes.add_argument('--remove', action='store_true', help='Remove an installed probe')
    parser.add_argument('--kcd2', type=Path, help='Installed KCD2: also verify the retail node, table and tree contracts')
    args = parser.parse_args(argv)
    if args.check:
        problems = audit(args.package) + (verify_retail(args.kcd2) if args.kcd2 else [])
        for problem in problems:
            print('FAIL ' + problem)
        print('trace probe: ' + ('FAIL' if problems else 'ok'))
        return 1 if problems else 0
    if args.remove:
        changed = remove(args.package)
        print(json.dumps(dict(removed=bool(changed), files=changed), indent=1))
        return 0
    changed, report = upgrade(args.package, None, args.kcd2)
    if not report:
        print('No kcd1_travel campaign entry in this package; nothing done.')
        return 1
    print(json.dumps(dict(changed=changed, report=report), indent=1))
    return 0


if __name__ == '__main__':
    sys.exit(main())
