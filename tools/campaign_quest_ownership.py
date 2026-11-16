"""Hold the ownership a controller grants, as retail quests do.

Call after quest emission, with the rows campaign_controller_ownership found
(`bindings['owned_assets']`: port, alias, asset_type) and the player's soul
alias (`bindings['player_asset']`). Per row the quest gains

    Port   In trigger `own_<key>`     fired by the controller's bridge signal
    State  bool, default false        set by the port; a quest State is saved
    SetOwner  What = the object's asset, Who = the player, IsActive = the State

which is the retail shape (`<SetOwner><Asset Name="What"/><Asset Name="Who"/>
<Edge To="IsActive"/></SetOwner>`, e.g. A201_kovani/zbrojnice.xml: a stash
owned by `player` while a bool holds). KCD1 changes the owner once and for
good; here the effect is held for as long as the quest's State is true, and
the State is never cleared. Whether the effect survives the quest's
deactivation is not established. Not runtime-verified.
"""
import xml.etree.ElementTree as ET

from campaign_quest_graph import constant, edge, identifier, xml

PREFIX = 'lowered_own_'
WHAT = {'StashAsset', 'SmartObjectAsset', 'ItemSlotAsset', 'AnimDoorAsset', 'SmartAreaAsset'}


def bind(blob, model, bindings):
    rows = [r for r in bindings.get('owned_assets', {}).get(model['quest'], [])]
    report = dict(converted=[], pending=[], runtime_verified=False)
    if not rows:
        return blob, report
    if not bindings.get('player_asset'):
        report['pending'] = [dict(port=r['port'], reason='no player asset') for r in rows]
        return blob, report
    player = identifier(bindings['player_asset'])
    root = ET.fromstring(blob)
    quest = root.find('./Skald/Quest')
    if quest is None or quest.get('Name') != model['quest']:
        raise ValueError('Destination quest identity mismatch')
    nodes, ports = quest.find('Nodes'), quest.find('Ports')
    if any(n.get('Name', '').startswith(PREFIX) for n in nodes):
        raise ValueError('Ownership already lowered')
    taken = {p.get('Name') for p in ports}
    for row in rows:
        port, alias = identifier(row['port']), identifier(row['alias'])
        if row['asset_type'] not in WHAT:
            raise ValueError('No retail SetOwner takes this asset class: ' + row['asset_type'])
        if port in taken:
            raise ValueError('Quest port name is taken: ' + port)
        taken.add(port)
        ET.SubElement(ports, 'Port', Name=port, Direction='In', Type='trigger')
        latch = ET.SubElement(nodes, 'State', Name=PREFIX + port, TypeT='bool')
        constant(latch, 'DefaultValue', 'false')
        edge(latch, port, 'SetTrue')
        effect = ET.SubElement(nodes, 'SetOwner', Name=PREFIX + port + '_effect')
        ET.SubElement(effect, 'Asset', Name='What', Alias=alias)
        ET.SubElement(effect, 'Asset', Name='Who', Alias=player)
        edge(effect, PREFIX + port + '.State', 'IsActive')
        report['converted'].append(dict(port=port, what=alias, asset_type=row['asset_type'], who=player))
    return xml(root), report
