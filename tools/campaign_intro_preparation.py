"""Source-derived startup protection until a quest worker acknowledges entry.

KCD1 controller-side DisablePerception runs independently of the NPC scheduler.
The KCD2 quest context below suppresses perception reactions while the source
introduction request is eligible, before its worker acknowledges initialization;
it is not a replacement for the worker's native Disable/EnablePerception pair
and does not make the actor invisible or invulnerable.
"""
import xml.etree.ElementTree as E

from campaign_quest_graph import all_of, constant, edge, xml
from campaign_quest_start_placement import unique

CONTEXT = 'switch_disabledPerceptionReaction'
NATIVE = 'Quests/Final/Barbora/kutnohorsko/damaVNesnazich/rozdelovani_penez_v_seniku/cesta_zpet_do_seniku.xml'


def contract(controller_sequence, worker, actor_ref, source):
    disables = controller_sequence.findall('DisablePerception')
    if not disables:
        return None
    disable = unique(disables, 'intro controller perception preparation')
    faction = unique(controller_sequence.findall('SetTemporarySuperfaction'), 'intro controller faction preparation')
    operations = list(controller_sequence)
    enable = unique(worker.findall('Root/OnInit/Sequence/IfCondition/Sequence/EnablePerception'),
                    'intro worker perception release')
    if (disable.attrib != dict(Perceptor='true', Perceptible='true', ToWhom=actor_ref)
            or enable.attrib != dict(Perceptor='true', Perceptible='true', ToWhom='')
            or operations.index(disable) >= operations.index(faction)
            or not source.get('initialization')):
        raise ValueError('Unsupported source introduction preparation/release ordering')
    return dict(version=1, controller_operation=dict(disable.attrib),
                release='worker_initialization_acknowledgement', native_context=CONTEXT,
                native_contract=NATIVE, scope='eligible_intro_uninitialized',
                adaptation='suppress native perception reactions during eligible introduction; worker owns actual perception enable/disable')


def validate_native(scripts, tables):
    from upgrade_map import read
    document = E.fromstring(read(scripts, NATIVE))
    effects = [n for n in document.iter('SetEntityContext')
               if n.find("Constant[@Name='Context']") is not None
               and n.find("Constant[@Name='Context']").get('Value') == CONTEXT]
    if not any(n.find("Asset[@Name='Souls']") is not None
               and n.find("Edge[@To='IsActive']") is not None for n in effects):
        raise ValueError('Native introductory reaction protection contract changed')
    contexts = E.fromstring(read(tables, 'Libs/Tables/ai/ScriptContext.xml'))
    if not any(n.get('Name') == CONTEXT and n.get('Class') == 'Entity' for n in contexts):
        # Native tables wrap their rows in a database node.
        if not any(n.get('Name') == CONTEXT and n.get('Class') == 'Entity' for n in contexts.iter()):
            raise ValueError('Native introductory reaction context is unavailable')


def enabled(source):
    preparation = source.get('temporary_faction', {}).get('preparation')
    if preparation is None:
        return False
    if (preparation.get('version') != 1 or preparation.get('native_context') != CONTEXT
            or preparation.get('release') != 'worker_initialization_acknowledgement'
            or preparation.get('scope') != 'eligible_intro_uninitialized'):
        raise ValueError('Unsupported introductory preparation contract')
    return True


def event_set(stem, source):
    return stem+'_initialization' if enabled(source) else 'resultNotification'


def worker_files(tree, stem, source):
    if not enabled(source):
        return {}
    # Outside the first-entry guard: re-entering a previously initialized worker
    # also acknowledges its ready state after load without repeating placement.
    sequence = tree.find('Root/OnInit/Sequence')
    if sequence is None:
        raise ValueError('Intro protection requires an acknowledged initializer')
    E.SubElement(sequence, 'Callback_empty', EventName="'Initialized'")
    tree.find('EditorData').set('EventSet', event_set(stem, source))
    table = E.Element('database', name='barbora')
    definition = E.SubElement(E.SubElement(table, 'EventSets', version='1'),
                              'TreeEventSet', Name=event_set(stem, source))
    events = E.SubElement(definition, 'Events')
    for name in ('Success', 'Fail', 'Initialized'):
        E.SubElement(events, 'CallbackEventDefinition', Atomic='false', Name=name, Signature='empty')
    return {'Libs/Tables/ai/EventSet__'+stem+'.xml': xml(table)}


def attach(entry_root, stem, source, *, validate=False):
    if not enabled(source):
        return False
    nodes = entry_root.find('Skald/Level/Nodes')
    invocation = unique(nodes.findall("EnableBehavior[@Name='"+stem+"_enable']"), 'preparation worker')
    activation = unique(invocation.findall("Edge[@To='IsActive']"), 'preparation activation').get('From')
    expected = E.Element('Nodes')
    initialized = E.SubElement(expected, 'State', Name=stem+'_initialized', TypeT='bool')
    constant(initialized, 'DefaultValue', 'false')
    edge(initialized, stem+'_enable.Initialized', 'SetTrue')
    pending = E.SubElement(expected, 'Function', Name=stem+'_uninitialized',
                           MethodName='math::boolean::Not', DeclaringType='math::boolean')
    edge(pending, stem+'_initialized.State', 'Value')
    active = all_of(expected, stem+'_preparing',
                    [activation, stem+'_uninitialized.bool'])
    effect = E.SubElement(expected, 'SetEntityContext', Name=stem+'_preparation_guard')
    constant(effect, 'Context', CONTEXT)
    E.SubElement(effect, 'Asset', Name='Souls', Alias=stem+'_actor')
    edge(effect, active, 'IsActive')
    def shape(n):
        return n.tag, dict(n.attrib), [shape(c) for c in n]
    additions = []
    for n in expected:
        found = nodes.findall("*[@Name='"+n.get('Name')+"']")
        if found:
            if shape(unique(found, 'preparation node')) != shape(n):
                raise ValueError('Conflicting introduction preparation graph')
        elif validate:
            raise ValueError('Missing introduction preparation graph')
        else:
            additions.append(n)
    wanted = event_set(stem, source)
    previous = invocation.get('EventSet')
    if previous not in ('resultNotification', wanted) or validate and previous != wanted:
        raise ValueError('Introduction preparation callback contract differs')
    changed = bool(additions) or previous != wanted
    if not validate:
        nodes.extend(additions)
        invocation.set('EventSet', wanted)
    return changed


def rebind(entry, stem, previous, current):
    """Follow the invitation's narrowing of the same introduction request."""
    preparing = entry.find(".//Nodes/Function[@Name='"+stem+"_preparing_0']")
    if preparing is None:
        return
    activation = unique((n for n in preparing.findall('Edge') if n.get('From') == previous),
                        'preparation request activation')
    activation.set('From', current)
