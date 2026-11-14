"""Lower a counted source place asset to a native area presence latch.

Used by campaign_quest_tracking for tracked rows whose asset is a quest_place.
A source place names a level entity. Only an entity the caller registered as a
TriggerArea is lowered: a TagPoint has no extent, and the reach distance the
source engine used for a point place is not established. Geometry is never
computed here; the stage that installs the level owns the TriggerArea entity,
its compiled polygon and the asset link.

    bindings['place_assets'] = {source entity name:
        dict(alias=<TriggerAreaAsset alias>, entity_class=<source EntityClass>)}

Native shape follows retail KCD2 quest XML (855 files use it): an AreaTrigger
with `Souls` and `Areas` assets, an `IsActive` edge, and `OnEnter` / `OnLeave`
events. The trigger is an event; the source predicate is a state, so presence
is kept in a latch, as campaign_quest_tracking does for an NPC death.

Not established, and reported on every record as `initial_presence_verified`:
whether a native AreaTrigger raises OnEnter for a soul already inside when it
becomes active. The latch listens for the whole time the quest is active, so
the question only matters when the player is inside as the quest starts or as
a save loads. Not runtime-verified.
"""
import xml.etree.ElementTree as ET

from campaign_quest_graph import constant, edge, identifier

NO_BINDING = 'place tracking requires a spatial adapter '


def requirement(row, place, bindings):
    """Return (requirement, None) or (None, pending reason) for one tracked row."""
    aid = row['quest_asset_id']
    registered = bindings.get('place_assets')
    if registered is None:
        return None, NO_BINDING + aid
    if place.get('map'):
        return None, 'place on another map ' + aid
    if row['count'] != '1':
        return None, 'unsupported place count ' + row['count']
    entity = place.get('entity') or ''
    record = registered.get(entity)
    if record is None:
        return None, 'unregistered place ' + entity
    if record.get('entity_class') != 'TriggerArea':
        return None, 'place without an area (' + str(record.get('entity_class')) + ') ' + entity
    return dict(kind='place', asset=aid, source_entity=entity, area_asset=identifier(record['alias']),
                initial_presence_verified=False), None


def emit(nodes, name, req, player):
    """Add the trigger and its latch; return (state check, change event)."""
    watch = ET.SubElement(nodes, 'AreaTrigger', Name=name + '_watch')
    ET.SubElement(watch, 'Asset', Name='Souls', Alias=player)
    ET.SubElement(watch, 'Asset', Name='Areas', Alias=req['area_asset'])
    edge(watch, 'quest_progress.Active', 'IsActive')
    latch = ET.SubElement(nodes, 'State', Name=name + '_inside', TypeT='bool')
    constant(latch, 'DefaultValue', 'false')
    edge(latch, name + '_watch.OnEnter', 'SetTrue')
    edge(latch, name + '_watch.OnLeave', 'SetFalse')
    return name + '_inside.State', name + '_inside.OnExec'


def world_requirements(tracking):
    """What the level stage must provide for the place records that were lowered."""
    return sorted({(q['source_entity'], q['area_asset']) for r in tracking['converted']
                   for q in r['requirements'] if q['kind'] == 'place'})
