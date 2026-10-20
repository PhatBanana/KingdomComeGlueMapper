"""Select and compile source-owned exercises without inventing native phases.

The caller resolves the entry/exit objectives and behavior registrations. The
quest graph owns advancement; exercises retain their complete source programs,
including instruction locks, controls, listeners and objective completion.
"""
import copy
import xml.etree.ElementTree as E

from campaign_behavior import BehaviorCompiler
from campaign_quest_graph import objective_identifier, edge, all_of, identifier


class ExerciseConversionError(ValueError):
    def __init__(self, report):
        self.report = report
        reasons = sorted({e['reason'] for t in report['trees'] for e in t['unresolved']})
        super().__init__('Source exercise conversion blocked: ' + '; '.join(reasons))


def resolve(model, entry, exit, programs, *, include_exit=False):
    """Follow enabled edges between explicit lesson boundaries.

    programs maps source objective names to {document, tree} registrations.
    A branch/cycle is rejected, not flattened into a numeric ordering. The exit
    objective is normally an external boundary. include_exit supports lessons
    whose last exercise is itself the boundary, with no outgoing transition.
    """
    rows = model['tables']['quest_objective']['rows']
    by_name = {r['objective_name']: r for r in rows}
    by_id = {r['objective_id']: r for r in rows}
    if len(by_name) != len(rows) or len(by_id) != len(rows):
        raise ValueError('Duplicate source objective identity')
    if entry not in by_name or exit not in by_name or entry == exit:
        raise ValueError('Training requires distinct existing entry and exit objectives')
    if any(r['quest_id'] != model['quest_id'] for r in rows):
        raise ValueError('Cross-quest exercise objective')
    successors = {}
    for row in model['tables']['quest_transition']['rows']:
        enabled = str(row['enabled']).lower()
        if enabled not in ('true', 'false', '1', '0'):
            raise ValueError('Unknown source transition enabled value')
        if enabled in ('false', '0'):
            continue
        source, target = row['from_objective_id'], row['to_objective_id']
        if row['quest_id'] != model['quest_id']:
            raise ValueError('Cross-quest exercise transition')
        successors.setdefault(source, []).append(target)
    stages, visited = [], set()
    current = by_name[entry]['objective_id']
    end = by_name[exit]['objective_id']
    while current != end or include_exit:
        if current not in by_id:
            raise ValueError('Unresolved source exercise transition endpoint: ' + current)
        if current in visited:
            raise ValueError('Cyclic source exercise sequence')
        visited.add(current)
        name = by_id[current]['objective_name']
        binding = programs.get(name)
        if not binding:
            raise ValueError('Missing source exercise registration: ' + name)
        document, tree = binding['document'], binding['tree']
        try:
            program = model['behavior_documents'][document]['trees'][tree]
        except KeyError as error:
            raise ValueError('Missing source exercise program: ' + name) from error
        # Some libraries complete $__behaviorName. A public registration name
        # cannot replace that execution identity with a synthetic phase name.
        stages.append(dict(objective=name, objective_id=current,
                           objective_port=objective_identifier(name),
                           document=document, tree=tree, program=copy.deepcopy(program)))
        if current == end:
            break
        outgoing = successors.get(current, [])
        if len(outgoing) != 1:
            raise ValueError('Exercise needs one enabled successor: ' + name)
        current = outgoing[0]
    return dict(entry=entry, exit=exit, include_exit=include_exit,
                stages=stages, runtime_validated=False)


def compile_exercises(model, sequence, namespace, catalog, registered=None,
                      importer=None, profile_streaming=None):
    """Use the full behavior compiler and its dependency closure atomically.

    No successful subset is returned when a required exercise is withheld.
    Callers must also bind the returned bridge and registration requirements.
    """
    bindings = {s['objective']: dict(document=s['document'], tree=s['tree'])
                for s in sequence['stages']}
    expected = resolve(model, sequence['entry'], sequence['exit'], bindings,
                       include_exit=sequence.get('include_exit', False))
    if expected != sequence:
        raise ValueError('Source exercise plan is stale or modified')
    compiler = BehaviorCompiler([copy.deepcopy(model)], namespace, catalog,
                                registered, importer, profile_streaming)
    files, bridge, report = compiler.compile()
    records = {(r['owner'], r['document'], r['tree']): r for r in report['trees']}
    selected = []
    for stage in sequence['stages']:
        identity = (model['quest'], stage['document'], stage['tree'])
        record = records.get(identity)
        if record is None:
            raise ValueError('Exercise compiler ownership unresolved: ' + repr(identity))
        selected.append(record)
    if not selected or any(not r['native_emitted'] for r in selected):
        # Include dependency failures as well as the selected callers, because
        # a caller may be withheld solely by include closure.
        raise ExerciseConversionError(dict(sequence=sequence, trees=report['trees'],
                                           runtime_validated=False))
    return files, bridge, dict(sequence=sequence, behavior=report,
                               runtime_validated=False, publication_ready=False)


def bind(nodes, quest, quest_definition, sequence, workers, active):
    """Schedule dedicated converted workers from actual source objective state.

    active is the host's authorized/prepared/readiness state, cleared on cancel
    and cleanup. Workers must retain their source object and variable bindings.
    Completion is performed by the converted source program through its quest
    bridge, not by an arbitrary native tutorial phase or worker success event.
    """
    stages = sequence['stages']
    names = [s['objective'] for s in stages]
    if not names or set(workers) != set(names) or len(set(names)) != len(names):
        raise ValueError('Every source exercise needs a distinct worker binding')
    ports = E.fromstring(quest_definition).find('./Skald/Quest/Ports')
    if ports is None:
        raise ValueError('Missing compiled source quest ports')
    q = identifier(quest.get('Name'))
    planned = []
    for stage in stages:
        name = stage['objective']
        port = objective_identifier(name) + '_Started'
        if ports.find("Port[@Name='" + port + "'][@Direction='Out'][@Type='bool']") is None:
            raise ValueError('Missing source exercise state port: ' + port)
        worker = workers[name]
        if worker.tag != 'EnableBehavior' or worker not in list(nodes):
            raise ValueError('Exercise worker must be a host EnableBehavior instance')
        prefix = identifier(worker.get('Name')) + '_exercise'
        if worker.findall("Edge[@To='IsActive']") or worker.findall("Constant[@Name='IsActive']"):
            raise ValueError('Exercise worker already scheduled')
        if any(n.get('Name', '').startswith(prefix) for n in nodes):
            raise ValueError('Exercise scheduler identity collision')
        planned.append((worker, prefix, q + '.' + port))
    if len({w.get('Name') for w, _, _ in planned}) != len(planned):
        raise ValueError('Source exercises cannot share a worker invocation')
    for worker, prefix, state in planned:
        conditions = [active, state]
        for index, (_, _, other) in enumerate(planned):
            if other == state:
                continue
            negate = E.SubElement(nodes, 'Function', Name=prefix+'_not_'+str(index),
                                  MethodName='math::boolean::Not', DeclaringType='math::boolean')
            edge(negate, other, 'Value')
            conditions.append(negate.get('Name')+'.bool')
        edge(worker, all_of(nodes, prefix+'_active', conditions), 'IsActive')
    return dict(source_objectives=names, runtime_validated=False,
                requires=['source controller bindings', 'compiled objective bridge',
                          'host cancellation and cleanup', 'in-game validation'])
