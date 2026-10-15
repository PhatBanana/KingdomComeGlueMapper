"""Expose executed dialogue sequences to native gameplay handoff consumers."""
import xml.etree.ElementTree as E

ACTIVITY_PORT = 'gm_sequence_active'


def expose(host):
    if host.tag not in ('FaderDialog', 'ForcedDialog'):
        return None
    ports = host.find('Ports')
    if ports is None:
        ports = E.SubElement(host, 'Ports')
    existing = ports.find("Port[@Name='" + ACTIVITY_PORT + "']")
    if existing is None:
        E.SubElement(ports, 'Port', Name=ACTIVITY_PORT, Direction='Out', Type='trigger')
    elif existing.get('Direction') != 'Out' or existing.get('Type') != 'trigger':
        raise ValueError('Dialogue activity port collision')
    for sequence in host.findall('.//Dialogue//Sequence'):
        triggers = sequence.find('Triggers')
        if triggers is None:
            triggers = E.Element('Triggers'); sequence.insert(0, triggers)
        if triggers.find("Port[@Name='" + ACTIVITY_PORT + "']") is None:
            # Establish occupancy before this sequence's quest effects execute.
            triggers.insert(0, E.Element('Port', Name=ACTIVITY_PORT))
    return ACTIVITY_PORT
