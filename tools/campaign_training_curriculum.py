"""Resolve an explicitly selected native lesson from its production graph.

Native phase numbers, instruction aliases and UI tutorial IDs are different
namespaces. Follow graph references between them; never zip numerically sorted
source exercises to native phases. The caller still imports dialogue recordings
and binds the source arrival/equipment/quest lifetime.
"""
import hashlib
import posixpath
import xml.etree.ElementTree as E

from campaign_native_training import inspect_contract
from campaign_training_dialogue import native_phases
from campaign_training_runtime import emit as emit_runtime
from campaign_quest_graph import identifier


def _one(values, description):
    values = list(values)
    if len(values) != 1:
        raise ValueError('Expected one ' + description)
    return values[0]


def _path(parent, relative):
    path = posixpath.normpath(posixpath.join(posixpath.dirname(parent), relative))
    if ('\\' in path or ':' in path or not path.startswith('Quests/Final/')
            or not path.endswith('.xml')):
        raise ValueError('Native lesson definition escapes production quests')
    return path


class _SelectedArchive:
    """Do not merge contracts from unrelated examples of the same domain."""
    def __init__(self, path, blob):
        self.path, self.blob = path, blob

    def namelist(self):
        return [self.path]

    def read(self, path):
        if path != self.path:
            raise KeyError(path)
        return self.blob


def resolve(archive, path, domain):
    """Read the entire selected graph and each referenced phase/instruction.

    Only the explicitly selected native lesson is substituted. The surrounding
    source quest, its equipment programs and its objective graph are untouched.
    Returned instruction documents retain native voices, roles and conditions;
    they must pass through resource/participant binding before installation.
    """
    path = _path(path, posixpath.basename(path))
    blobs = {}

    def read(name):
        if name not in blobs:
            blobs[name] = archive.read(name)
        return E.fromstring(blobs[name])

    root = read(path)
    host = _one(root.findall('./Skald/*'), 'native lesson scope')
    nodes = host.find('Nodes')
    if nodes is None:
        raise ValueError('Native lesson has no nodes')
    tutorial = _one(nodes.findall('CombatTutorialNode'), 'native tutorial controller')
    if tutorial.find("Constant[@Name='Domain']") is None:
        raise ValueError('Native lesson has no explicit domain')
    if tutorial.find("Constant[@Name='Domain']").get('Value') != domain:
        raise ValueError('Selected native lesson has a different domain')
    initial = tutorial.find("Constant[@Name='InitialPhase']")
    if initial is None or initial.get('Value') != '0':
        raise ValueError('A complete native lesson must start at phase zero')
    contract = inspect_contract(_SelectedArchive(path, blobs[path]))
    # Validate the complete executable input/output contract before returning
    # a plan. This also requires Tracker, used by native progress displays.
    emit_runtime('validate_native_lesson', domain, contract)
    phases = native_phases(blobs[path])
    numbers = [p['phase'] for p in phases]
    if numbers != list(range(len(phases))):
        raise ValueError('Native lesson phase range is incomplete or unordered')

    def definitions(scope, source_path):
        result = {}
        for d in scope.findall('Definitions/Definition'):
            child_path = _path(source_path, d.get('File', ''))
            child = _one(read(child_path).findall('./Skald/*'), 'native definition scope')
            name = child.get('Name')
            if name in result:
                raise ValueError('Ambiguous native definition: ' + str(name))
            result[name] = (child_path, child)
        return result

    declared = definitions(host, path)
    result = []
    for phase in phases:
        instance_name, output_name = phase['native_scene_event'].split('.', 1)
        instance = _one((n for n in nodes if n.get('Name') == instance_name), 'phase module instance')
        if instance.tag not in declared:
            raise ValueError('Native phase module is not declared: ' + instance.tag)
        phase_path, phase_host = declared[instance.tag]
        phase_nodes = phase_host.find('Nodes')
        if phase_nodes is None:
            raise ValueError('Native phase module has no nodes')
        phase_defs = definitions(phase_host, phase_path)
        source = _one(phase_nodes.findall("Output/Edge[@To='" + output_name + "']"),
                      'native instruction output').get('From')
        visited = set()
        # Shipped phases acknowledge through a Progress state. Preserve the
        # actual dialogue trigger at the end of this chain, not AfterPlay of
        # an unrelated scene or a phase-start pulse.
        while True:
            if source in visited:
                raise ValueError('Cyclic native instruction acknowledgement')
            visited.add(source)
            name, port = source.split('.', 1)
            node = _one((n for n in phase_nodes if n.get('Name') == name), 'instruction source node')
            if node.tag == 'State' and port.startswith('On'):
                source = _one(node.findall("Edge[@To='Set" + port[2:] + "']"),
                              'instruction state activation').get('From')
                continue
            if node.tag not in phase_defs:
                raise ValueError('Unsupported native instruction acknowledgement: ' + source)
            instruction_path, instruction = phase_defs[node.tag]
            if instruction.tag not in ('Dialog', 'ForcedDialog', 'FaderDialog'):
                raise ValueError('Native instruction does not resolve to a dialogue')
            _one(instruction.findall("Ports/Port[@Name='" + port + "'][@Direction='Out'][@Type='trigger']"),
                 'instruction trigger declaration')
            if not instruction.findall(".//Triggers/Port[@Name='" + port + "']"):
                raise ValueError('Native instruction never emits its declared trigger')
            aliases = sorted({d.get('Alias') for d in instruction.findall('.//Decision') if d.get('Alias')})
            if not aliases:
                raise ValueError('Native instruction has no registered dialogue alias')
            result.append(dict(phase, module_file=phase_path, module_instance=instance_name,
                instruction_file=instruction_path, instruction_port=port, instruction_aliases=aliases,
                roles=sorted({r.get('Role') for r in instruction.findall('.//Response')}),
                tutorials=[c.get('Value') for c in phase_nodes.findall("DisplayTutorial/Constant[@Name='Tutorial']")]))
            break
    if len({p['instruction_file'] for p in result}) != len(result):
        raise ValueError('Native phases share an ambiguous instruction invocation')
    return dict(mode='native_complete', domain=domain, source=path, phases=result, contract=contract,
        evidence=[dict(file=n, sha256=hashlib.sha256(b).hexdigest()) for n, b in sorted(blobs.items())],
        runtime_validated=False)


def emit(name, archive, path, domain):
    """Emit all native combat phases under the existing acknowledged lifecycle.

    Arrival, preparation and cleanup remain host ports; the native engine owns
    the exercises. This function never compiles or executes legacy exercises,
    nor completes their objectives to pretend they were played.
    """
    identifier(name)
    curriculum = resolve(archive, path, domain)
    blob, report = emit_runtime(name, domain, curriculum['contract'])
    report.update(mode='native_complete', curriculum=curriculum,
                  source_exercises_reproduced=False, faction_conversion_required=False)
    return blob, report
