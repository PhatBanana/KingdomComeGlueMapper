"""Place imported quests under their destination Level, preserving graph edges.

Native quest region ownership follows Level containment. A project-root quest
has no owning imported region even if its actors are standing in that region.
"""
import copy
import xml.etree.ElementTree as ET
from campaign_quest_graph import identifier, xml


def bind_level(project_blob, level_blob, quest_blob, instance_name, level_instance):
    identifier(instance_name); identifier(level_instance)
    project, level, definition = map(ET.fromstring, (project_blob, level_blob, quest_blob))
    host = project.find('./Skald/Project'); destination = level.find('./Skald/Level')
    quest = definition.find('./Skald/Quest')
    if host is None or destination is None or quest is None: raise ValueError('Expected Project, Level and Quest')
    nodes, dest_nodes = host.find('Nodes'), destination.find('Nodes')
    candidates = [n for n in nodes if n.get('Name') == instance_name and n.tag == quest.get('Name')]
    levels = [n for n in nodes if n.get('Name') == level_instance and n.tag == destination.get('Name')]
    if len(candidates) != 1 or len(levels) != 1: raise ValueError('Missing or ambiguous quest/level instance')
    if any(n.get('Name') == instance_name for n in dest_nodes): raise ValueError('Quest already belongs to level')
    source, level_node = candidates[0], levels[0]
    ports = destination.find('Ports')
    if ports is None: ports = ET.SubElement(destination, 'Ports')
    output = dest_nodes.find("Output[@Name='Output']")
    if output is None: output = ET.SubElement(dest_nodes, 'Output', Name='Output')
    declarations = {p.get('Name'): p for p in quest.findall('Ports/Port')}
    exposed = {}

    def expose(name, direction):
        if name not in declarations or declarations[name].get('Direction') != direction:
            raise ValueError('Undeclared quest connection: ' + name)
        if name in exposed: return exposed[name]
        alias = instance_name + '__' + name
        if any(p.get('Name') == alias for p in ports): raise ValueError('Level quest port collision: ' + alias)
        ET.SubElement(ports, 'Port', Name=alias, Direction=direction, Type=declarations[name].get('Type'))
        if direction == 'Out': ET.SubElement(output, 'Edge', From=instance_name + '.' + name, To=alias)
        exposed[name] = alias
        return alias

    moved = copy.deepcopy(source)
    for edge in moved.findall('Edge'):
        alias = expose(edge.get('To'), 'In')
        ET.SubElement(level_node, 'Edge', From=edge.get('From'), To=alias)
        edge.set('From', alias)
    nodes.remove(source)
    for edge in nodes.iter('Edge'):
        value = edge.get('From', '')
        if value.startswith(instance_name + '.'):
            port = value[len(instance_name) + 1:]
            edge.set('From', level_instance + '.' + expose(port, 'Out'))
    dest_nodes.append(moved)
    return xml(project), xml(level), dict(quest=instance_name, level=level_instance, ports=exposed,
                                         region_runtime_verified=False)
