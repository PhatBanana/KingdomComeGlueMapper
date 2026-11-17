"""Explicit item acquisition stimuli for class/count tracking.

This models acquisition notifications, not native loot, ownership or transfer.
Snapshot replacement alone never synthesizes an acquisition.
"""
import copy
from . import Unsupported
from .expressions import boolean
from .objects import INVENTORY


def acquire(graph, inventory, item, amount, health=None):
    """Add items and notify matching active watchers. health is required when the inventory keeps stacks."""
    from .pure import checked_descriptor
    from .world import eligible, give
    if not isinstance(item, str) or not item or type(amount) is not int or amount <= 0:
        raise ValueError('Acquisition requires an item class and positive integer amount')
    if health is not None and (type(health) not in (int, float) or not 0 <= health <= 1):
        raise ValueError('Acquired item health must be a number from 0 to 1')
    facets = copy.deepcopy(graph.objects.records.get(inventory, {}))
    queries = facets.get(INVENTORY, {}).get('queries', [])
    matches = [q for q in queries if q['method'] == 'Items' and q['arguments'] == {}]
    if len(matches) != 1:
        raise Unsupported('Acquisition requires an explicit inventory Items snapshot')
    items = matches[0]['result']
    before = copy.deepcopy(items)
    held = items.get(item, 0)
    if (health is None) != (type(held) is int):
        raise Unsupported('Acquisition health must match the inventory representation (counts or health stacks)')
    give(items, item, amount if health is None else [dict(amount=amount, health=health)])
    events = []
    for name, node in graph.nodes.items():
        if node['kind'] != 'ItemDescriptorTrigger': continue
        args = graph._args(name)
        if set(args) != {'Inventory', 'ItemDescriptor', 'IsActive'}:
            raise Unsupported('Incomplete item tracking interface: ' + name)
        if not boolean(args['IsActive']) or args['Inventory'] != inventory: continue
        target = checked_descriptor(args['ItemDescriptor'])
        if target['item_class'] != item: continue
        was, now = eligible(before, target), eligible(items, target)
        if now == was: continue        # below the descriptor's minimum health: not an acquisition for this watcher
        events.append(name + '.OnAcquire')
        if was < target['amount'] <= now:
            events.append(name + '.OnTargetAmountAcquire')
    graph.objects.replace(inventory, facets)
    from .world import total
    graph.record('item_acquired', inventory=inventory, item=item, amount=amount, health=health,
                 before=total(before, item), after=total(items, item), boundary='explicit_acquisition_stimulus')
    for event in reversed(events): graph.emit(event)
    graph.drain()
