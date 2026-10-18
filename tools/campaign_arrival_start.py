"""Restore the reference arrival chain for a bounded campaign-entry comparison.

This is deliberately not the shared travel package's default: an unmarked
existing player's first arrival would otherwise receive the new-game loadout.
"""
import xml.etree.ElementTree as ET
from upgrade_map import xml


def restore(blob, name):
    root = ET.fromstring(blob)
    nodes = root.find('./Skald/Project/Nodes')
    if nodes is None:
        raise ValueError('Missing campaign project')
    def one(suffix):
        matches = [n for n in nodes if n.get('Name') == name + suffix]
        if len(matches) != 1:
            raise ValueError('Missing or ambiguous campaign node: ' + suffix)
        return matches[0]
    begin, sequence, started = one('_begin'), one('_initialize'), one('_started')
    entry = begin.findall("Edge[@To='Exec']")
    if len(entry) != 1:
        raise ValueError('Ambiguous arrival edge')
    if entry[0].get('From') == name + '_new_game.True':
        ready = one('_ready').findall("Edge[@To='SetTrue']")
        if len(ready) != 1:
            raise ValueError('Ambiguous region readiness')
        entry[0].set('From', ready[0].get('From'))
    if not entry[0].get('From', '').endswith('.arrived'):
        raise ValueError('Expected explicit region arrival')
    execs = sequence.findall("Edge[@To='Exec']")
    if len(execs) != 1:
        raise ValueError('Ambiguous initialization edge')
    execs[0].set('From', name + '_begin.True')
    for edge in list(started):
        if edge.get('From') == name + '_new_game.False':
            started.remove(edge)
    removed = {name + suffix for suffix in ('_new_game', '_game_start', '_requested', '_ready')}
    for node in list(nodes):
        if node.get('Name') in removed:
            nodes.remove(node)
    for node in nodes:
        for edge in node.findall('Edge'):
            if edge.get('From', '').rsplit('.', 1)[0] in removed:
                raise ValueError('Dangling campaign gate edge')
    return xml(root)
