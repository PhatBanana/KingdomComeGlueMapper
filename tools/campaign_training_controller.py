"""Install converted equipment programs into one existing AI controller.

Call sites are explicit imported IncludeTree identities, never quest/NPC names.
Inlining keeps borrowed handles in the controller's single variable scope.
This does not invent a scheduler or silently replace the controller lifetime.
"""
import copy
import xml.etree.ElementTree as E

from campaign_quest_bridge import UnsupportedOperation
from campaign_quest_graph import xml
from campaign_quest_graph import edge, identifier
from quest_import import literal


def bind(blob, tree_name, call_sites, roots, variables, events):
    document = E.fromstring(blob)
    trees = document.findall("./BehaviorTree")
    matches = [t for t in trees if t.get('name') == tree_name]
    if len(matches) != 1:
        raise UnsupportedOperation('Training requires exactly one shared controller tree')
    tree = matches[0]
    if set(call_sites) != {'prepare', 'cleanup'} or set(roots) != set(call_sites):
        raise UnsupportedOperation('Training requires paired preparation and cleanup sites')
    if set(events) != set(call_sites) or any(set(v) != {'Success', 'Fail'} for v in events.values()):
        raise UnsupportedOperation('Training requires explicit phase success/failure events')
    event_names = [name for phase in events.values() for name in phase.values()]
    if len(set(event_names)) != 4 or any(not n.isidentifier() for n in event_names):
        raise UnsupportedOperation('Training callback events must be distinct identifiers')
    replacements = []
    controller_root = tree.find('Root')
    if controller_root is None:
        raise UnsupportedOperation('Training controller has no executable Root')
    for phase, site in call_sites.items():
        def matches_call(child):
            if site.get('kind', 'include') == 'behavior':
                return (child.tag == 'CallBehavior'
                        and literal(child.get('Target', '')) in (site['target'], repr(site['target']))
                        and literal(child.get('BehaviorName', '')) in (site['behavior'], repr(site['behavior'])))
            if site.get('kind', 'include') != 'include':
                raise UnsupportedOperation('Unknown training call-site kind')
            return (child.tag == 'IncludeTree'
                    and literal(child.get('File', '')) in (site['file'], repr(site['file']))
                    and literal(child.get('Name', '')) in (site['tree'], repr(site['tree'])))
        found = [(parent, child) for parent in controller_root.iter() for child in parent
                 if matches_call(child)]
        if len(found) != 1:
            raise UnsupportedOperation('Training needs one controller call site for ' + phase)
        replacements.append((phase, *found[0]))
    if replacements[0][2] is replacements[1][2]:
        raise UnsupportedOperation('Training preparation and cleanup cannot share a call site')

    declarations = tree.find('Variables')
    if declarations is None:
        declarations = E.Element('Variables'); tree.insert(0, declarations)
    for variable in variables:
        current = declarations.findall("Variable[@name='" + variable.get('name') + "']")
        if len(current) > 1:
            raise UnsupportedOperation('Duplicate controller variable')
        if current:
            old, new = dict(current[0].attrib), dict(variable.attrib)
            old.pop('isPersistent', None); new.pop('isPersistent', None)
            if old != new:
                raise UnsupportedOperation('Conflicting shared training variable: ' + variable.get('name'))
            if variable.get('isPersistent') == '1': current[0].set('isPersistent', '1')
        else:
            declarations.append(copy.deepcopy(variable))

    for phase, parent, call in replacements:
        root = E.fromstring(roots[phase])
        if any(n.tag not in ('OnInit', 'Behavior') for n in root):
            raise UnsupportedOperation('Cannot inline training callback exit handlers')
        behavior = root.find('Behavior')
        if behavior is None or len(behavior) != 1 or behavior[0].tag != 'FuseBox':
            raise UnsupportedOperation('Training callback is missing its acknowledgement wrapper')
        fuse = behavior[0]
        child = fuse.find('Child')
        sequence = E.Element('Sequence')
        # Initialization runs each time this source callback is invoked. Keeping
        # it inside the same FuseBox also reports a failed restoration lookup.
        for init in root.findall('OnInit'):
            for operation in init: sequence.append(copy.deepcopy(operation))
        for operation in list(child): sequence.append(operation); child.remove(operation)
        child.append(sequence)
        for outcome in ('Success', 'Fail'):
            callback = fuse.find('On' + outcome + '/Callback_empty')
            if callback is None: raise UnsupportedOperation('Missing training callback acknowledgement')
            callback.set('EventName', repr(events[phase][outcome]))
        index = list(parent).index(call); parent.remove(call); parent.insert(index, fuse)
    return xml(document), dict(controller=tree_name, shared_state=True,
        callbacks=events, event_signatures={name: 'empty' for name in event_names},
        runtime_validated=False, publication_ready=False)


def register_events(blob, tree_name, name, signatures, native_event_sets):
    """Extend the controller's event contract without dropping existing events."""
    identifier(name)
    root = E.fromstring(blob)
    tree = next(t for t in root.findall('BehaviorTree') if t.get('name') == tree_name)
    editor = tree.find('EditorData')
    previous = editor.get('EventSet', '') if editor is not None else ''
    registry = E.fromstring(native_event_sets)
    existing = [n for n in registry.iter('TreeEventSet') if n.get('Name') == previous]
    if previous and len(existing) != 1:
        raise UnsupportedOperation('Cannot resolve original controller event set: ' + previous)
    definition = copy.deepcopy(existing[0]) if previous else E.Element('TreeEventSet')
    definition.set('Name', name)
    events = definition.find('Events')
    if events is None: events = E.SubElement(definition, 'Events')
    for event, signature in signatures.items():
        if any(n.get('Name') == event for n in events):
            raise UnsupportedOperation('Training event collides with existing controller event: ' + event)
        E.SubElement(events, 'CallbackEventDefinition', Atomic='false', Name=event, Signature=signature)
    table = E.Element('database', name='barbora')
    E.SubElement(table, 'EventSets', version='1').append(definition)
    if editor is None: editor = E.SubElement(tree, 'EditorData')
    editor.set('EventSet', name)
    return xml(root), xml(table)


def wire_acknowledgements(lifecycle, controller, binding, event_set):
    """Connect a caller-owned native behavior invocation to lifecycle inputs.

    Control of the source controller is not inferred here. Its caller still
    owns request/stop scheduling and the workers_stopped acknowledgement.
    """
    if controller.tag != 'EnableBehavior' or controller.get('EventSet') != event_set:
        raise UnsupportedOperation('Training acknowledgements require the matching native behavior event set')
    pairs = [('prepare', 'Success', 'prepared'), ('prepare', 'Fail', 'preparation_failed'),
             ('cleanup', 'Success', 'cleanup_done'), ('cleanup', 'Fail', 'cleanup_failed')]
    if any(e.get('To') in {p[2] for p in pairs} for e in lifecycle.findall('Edge')):
        raise UnsupportedOperation('Training equipment acknowledgements are already bound')
    for phase, outcome, target in pairs:
        edge(lifecycle, controller.get('Name') + '.' + binding['callbacks'][phase][outcome], target)
