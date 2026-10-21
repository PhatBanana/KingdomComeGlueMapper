"""Reusable adapter for the installed KCD2 combat tutorial controller.

The engine owns combat exercises, hit detection and phase advancement. A host
quest owns arrival, equipment, dialogue, protections and cancellation. Never
interpret an individual successful hit (OnSuccessEvent) as lesson completion.
"""
import hashlib
from pathlib import Path
import xml.etree.ElementTree as ET
import zipfile

from campaign_quest_graph import definition, identifier, edge, constant, xml


SOUL = 'wh::rpgmodule::I_Soul*'
OUTPUTS = {'phase': ('Phase', 'int'),
           'tracker': ('Tracker', 'wh::questmodule::nodes::Tracker'),
           'phase_started': ('OnPhaseStart', 'trigger'),
           'phase_skipped': ('OnPhaseSkipped', 'trigger'),
           'success': ('OnSuccessEvent', 'trigger'),
           'failure': ('OnFailEvent', 'trigger'),
           'finished': ('OnTutorialEnd', 'trigger')}


def inspect_contract(archive):
    """Extract only production examples; editor/testing copies are not proof."""
    domains = {}
    for entry in sorted(archive.namelist()):
        if not entry.lower().startswith('quests/final/') or not entry.lower().endswith('.xml'):
            continue
        data = archive.read(entry)
        if b'<CombatTutorialNode ' not in data:
            continue
        root = ET.fromstring(data)
        for nodes in root.findall('.//Nodes'):
            for node in nodes.findall('CombatTutorialNode'):
                constants = {c.get('Name'): c.get('Value') for c in node.findall('Constant')}
                domain = constants.get('Domain')
                if not domain or constants.get('InitialPhase') != '0':
                    continue
                inputs = {c.get('To') for c in node.findall('Edge')}
                inputs.update(c.get('Name') for c in node.findall('Asset'))
                prefix = node.get('Name') + '.'
                outputs = {e.get('From')[len(prefix):] for e in nodes.findall('./*/Edge')
                           if e.get('From', '').startswith(prefix)}
                record = domains.setdefault(domain, dict(inputs=set(), outputs=set(), evidence=[]))
                record['inputs'].update(inputs)
                record['outputs'].update(outputs)
                record['evidence'].append(dict(file=entry, sha256=hashlib.sha256(data).hexdigest()))
    return {domain: dict(inputs=sorted(r['inputs']), outputs=sorted(r['outputs']),
                        evidence=r['evidence']) for domain, r in sorted(domains.items())}


def load_contract(game):
    with zipfile.ZipFile(Path(game) / 'Data/Scripts.pak') as archive:
        return inspect_contract(archive)


def emit(name, domain, contract):
    """Emit a parameterized node, without choosing an NPC, quest or rewards.

    Continue is the dialogue acknowledgement used by native Basic lessons at
    their instruction barriers. The host must wire it deliberately, rather than
    pulse it automatically on every phase. IsActive is the host's persisted
    lifecycle state, also used to release combat on cancellation.
    """
    identifier(name)
    evidence = contract.get(domain)
    if not evidence:
        raise ValueError('No installed native combat tutorial domain: ' + domain)
    required_inputs = {'Tutor', 'IsActive', 'CustomStepEvent'}
    required_outputs = {v[0] for v in OUTPUTS.values()}
    missing_inputs = required_inputs - set(evidence['inputs'])
    missing_outputs = required_outputs - set(evidence['outputs'])
    if missing_inputs or missing_outputs:
        raise ValueError('Incomplete native combat tutorial contract: inputs=' +
                         ','.join(sorted(missing_inputs)) + '; outputs=' + ','.join(sorted(missing_outputs)))
    root, host = definition('Module', name)
    ports = ET.SubElement(host, 'Ports')
    for port, typ in [('tutor', SOUL), ('isactive', 'bool'), ('continue', 'trigger')]:
        ET.SubElement(ports, 'Port', Name=port, Direction='In', Type=typ)
    nodes = ET.SubElement(host, 'Nodes')
    controller = ET.SubElement(nodes, 'CombatTutorialNode', Name='training')
    constant(controller, 'Domain', domain)
    constant(controller, 'InitialPhase', '0')
    for source, target in [('tutor', 'Tutor'), ('isactive', 'IsActive'), ('continue', 'CustomStepEvent')]:
        edge(controller, source, target)
    output = ET.SubElement(nodes, 'Output', Name='Output')
    for port, (native, typ) in OUTPUTS.items():
        ET.SubElement(ports, 'Port', Name=port, Direction='Out', Type=typ)
        edge(output, 'training.' + native, port)
    return xml(root), dict(domain=domain, evidence=evidence['evidence'],
        completion_event='OnTutorialEnd', runtime_validated=False,
        required_host_bindings=['tutor', 'isactive', 'continue'],
        host_responsibilities=['arrival', 'equipment', 'dialogue', 'protections',
                               'cancellation', 'quest completion', 'save/load validation'])
