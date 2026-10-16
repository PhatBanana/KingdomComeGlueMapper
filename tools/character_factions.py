"""Convert the two distinct KCD1 faction ID domains to native faction trees."""
import math
import xml.etree.ElementTree as ET

PATH = 'Libs/Tables/rpg/FactionTree__gluemapper_people.xml'
LEAF = 'gluemapper_kcd1_faction_'
GROUP = 'gluemapper_kcd1_superfaction_'


def capture(tables, faction_id):
    faction = tables.row('rpg/faction', 'faction_id', faction_id)
    group = tables.row('rpg/superfaction', 'superfaction_id', faction['superfaction_id'])
    return dict(faction=faction, superfaction=group,
        factions=tables.get('rpg/faction')['rows'],
        superfactions=tables.get('rpg/superfaction')['rows'],
        relationships=tables.get('rpg/superfaction2superfaction_relationship')['rows'])


def reputation(value):
    if not math.isfinite(float(value)) or not -1 <= float(value) <= 1:
        raise ValueError('Invalid source faction reputation: ' + str(value))
    return str(value)


def register(files, data):
    """Rebuild importer-owned records, including old incorrectly nested leaves.

    Faction and superfaction numeric IDs overlap; they must never be walked as
    one hierarchy. Relations are directional and signed in both native formats.
    Location/UI references are withheld until their resources are registered.
    """
    factions = {r['faction_id']: r for r in data['factions']}
    groups = {r['superfaction_id']: r for r in data['superfactions']}
    if len(factions) != len(data['factions']) or len(groups) != len(data['superfactions']):
        raise ValueError('Duplicate source faction identity')
    selected = {data['faction']['faction_id']}
    if PATH in files:
        for node in ET.fromstring(files[PATH]).iter('Faction'):
            name = node.get('Name', '')
            if name.startswith(LEAF):
                selected.add(name[len(LEAF):])
            elif not name.startswith(GROUP):
                raise ValueError('Foreign faction in importer-owned table: ' + name)
    if selected - factions.keys():
        raise ValueError('Previously imported faction absent from source catalog')
    root = ET.Element('database', name='barbora')
    tree = ET.SubElement(root, 'FactionTree', version='1')
    nodes = {}
    # Keep all referenced group targets registered, including groups with no
    # placed actor yet. This does not spawn the attack population.
    for identity, row in sorted(groups.items()):
        nodes[identity] = ET.SubElement(tree, 'Faction', Name=GROUP + identity,
            Comment='KCD1 superfaction ' + row['superfaction_name'])
    players = [k for k, row in groups.items() if row['superfaction_name'] == 'Player']
    if len(players) != 1:
        raise ValueError('Expected one source player superfaction')
    seen = set()
    for row in data['relationships']:
        source, target = row['from_superfaction_id'], row['to_superfaction_id']
        if source not in nodes or target not in nodes or (source, target) in seen:
            raise ValueError('Missing or duplicate source faction relation')
        seen.add((source, target))
        relations = nodes[source].find('Relations')
        if relations is None:
            relations = ET.SubElement(nodes[source], 'Relations')
        ET.SubElement(relations, 'Relation', target='player' if target == players[0] else GROUP + target,
            reputation=reputation(row['relationship']))
    for identity in sorted(selected):
        row = factions[identity]
        parent = nodes.get(row['superfaction_id'])
        if parent is None:
            raise ValueError('Missing source superfaction: ' + row['superfaction_id'])
        children = parent.find('Children')
        if children is None:
            children = ET.SubElement(parent, 'Children')
        node = ET.SubElement(children, 'Faction', Name=LEAF + identity,
            Comment='KCD1 ' + row['faction_name'])
        if row.get('player_reputation') not in ('', None):
            ET.SubElement(ET.SubElement(node, 'Relations'), 'Relation', target='player',
                reputation=reputation(row['player_reputation']))
    # Assign only after validation completes, so callers never retain half a tree.
    files[PATH] = ET.tostring(root, encoding='utf-8', xml_declaration=True)
    return LEAF + data['faction']['faction_id']
