"""Lower source training equipment callbacks through the ordinary AI upgrader.

The returned roots belong to one controller scope. They must not be installed
as independent workers with separate copies of the borrowed-item variables.
"""
import copy
import re
import xml.etree.ElementTree as E

from campaign_behavior import TYPE_ADAPTERS
from campaign_training_plan import borrowed_equipment
from campaign_quest_bridge import UnsupportedOperation
from campaign_quest_graph import xml


def lower(compiler, owner, document, prepare, cleanup, variables, *, adapt=None):
    plan = borrowed_equipment(prepare, cleanup)
    declarations = {v['name']: copy.deepcopy(v) for v in variables}
    if len(declarations) != len(variables):
        raise UnsupportedOperation('Duplicate training variable declaration')
    # Keep the original variable and map key; separate callback-local variables
    # would lose the created instance when the preparation worker stops.
    for lease in plan['leases']:
        match = re.fullmatch(r"([A-Za-z_]\w*)(?:\['[^']+'\])?", lease['handle'])
        if not match or match[1] not in declarations:
            raise UnsupportedOperation('Missing shared training item variable: ' + lease['handle'])
        declaration = declarations[match[1]]
        expected_form = 'associative' if '[' in lease['handle'] else 'single'
        if TYPE_ADAPTERS.get(declaration.get('type')) != '_wuid' or declaration.get('form', 'single') != expected_form:
            raise UnsupportedOperation('Training item handle has incompatible type: ' + lease['handle'])
        declaration['isPersistent'] = '1'

    previous = compiler.variables
    roots, records = {}, {}
    try:
        compiler.variables = declarations
        native_variables = [compiler.variable(v) for v in declarations.values()]
        for phase, source in (('prepare', prepare), ('cleanup', cleanup)):
            source = copy.deepcopy(source)
            if adapt is not None:
                source = adapt(phase, source, plan)
            record = dict(includes=[], item_dependencies=[], buff_dependencies=[], unresolved=[])
            root = compiler.lower_node(source, owner, document,
                                       'training_' + phase, 'Root', record)
            if record['unresolved'] or root is None:
                reasons = '; '.join(r['reason'] for r in record['unresolved'])
                raise UnsupportedOperation('Training ' + phase + ' conversion failed: ' + reasons)
            if record['includes']:
                raise UnsupportedOperation('Training callback includes require dependency closure')
            # Preserve OnInit (including original-weapon searches) and all
            # operation order. A callback only acknowledges success at the end.
            body = root.find('Behavior')
            if body is None or len(body) != 1:
                raise UnsupportedOperation('Training callback requires one executable body')
            sequence = body[0]
            body.remove(sequence)
            fuse = E.SubElement(body, 'FuseBox', StatusPropagation='Child', OneCleanup='false', saveVersion='2')
            E.SubElement(fuse, 'Child', canSkip='1').append(sequence)
            for branch, event in (('OnSuccess', 'Success'), ('OnFail', 'Fail')):
                E.SubElement(E.SubElement(fuse, branch, canSkip='1'), 'Callback_empty', EventName=repr(event))
            roots[phase] = xml(root)
            records[phase] = record
    finally:
        compiler.variables = previous
    return roots, native_variables, dict(leases=plan['leases'], phases=records,
        event_set='resultNotification', requires_shared_controller_scope=True,
        runtime_validated=False, publication_ready=False,
        host_requirements=['serialize preparation invocations', 'stop preparation before cleanup',
                           'scope callbacks to invocation', 'retain shared variables through cleanup'])
