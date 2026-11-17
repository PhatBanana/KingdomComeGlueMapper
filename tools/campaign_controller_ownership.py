"""Ownership changes a controller makes, as the quest graph's `SetOwner` effect.

KCD1's `SetOwner Objects Owner MarkAsStolen` is a behaviour node and
`entity:SetLootLegal(true)` a script call. KCD2 has neither: ownership is the
Skald effect `SetOwner(IsActive, What, Who)`, whose `What` and `Who` are
assets bound when the quest is compiled (all 95 retail quest files that use
it; `What` is a StashAsset, SmartObjectAsset, ItemSlotAsset, AnimDoorAsset or
SmartAreaAsset). So the controller can only raise a signal, and the quest
holds the effect (campaign_quest_ownership):

    SetOwner Objects="t_x['key']" Owner="__player" MarkAsStolen="false"
        -> signal to the quest's In trigger `own_<key>`, when the level binds
           the reference to exactly one object of a class `What` accepts
    $v = $t_x['key'] ... GetEntityByWUID(data.v):SetLootLegal(true)
        -> the same signal (approved stand-in 8: the player owns the stash;
           reported as a stand-in, since owning is more than lootable)

An object found at run time (an item in an inventory, the NPC running the
tree) has no asset. Two such shapes are stand-ins by decision (Sean,
2026-11-16, relayed by Build); any other is left as written:

    SetOwner Objects="<found at run time>" Owner="__player" MarkAsStolen="false"
        -> Success (decision 9a: the owner stays as the level has it)
    entity.SetLootLegal(true|false) as a statement of a wrapper script
        -> the statement is removed, the rest of the script stays
           (decision 10a: looting the NPC who runs the tree is theft, as for
           any NPC in KCD2)

Not runtime-verified.
"""
import re
import xml.etree.ElementTree as ET

WHAT = {'StashAsset', 'SmartObjectAsset', 'ItemSlotAsset', 'AnimDoorAsset', 'SmartAreaAsset'}
PLAYER = ('__player', '$__player')
REFERENCE = re.compile(r"\$?(t_\w+\['(\w+)'\])")
LOOT = re.compile(r"XGenAIModule\.GetEntityByWUID\(data\.(\w+)\):SetLootLegal\(true\)")
ASSIGN = re.compile(r"\$(\w+)\s*=\s*(\S+)")
APPROVED = 'Sean, 2026-11-14 (relayed by the coordinator), stand-in 8'
DECIDED = 'Sean, 2026-11-16 (relayed by Build)'
RUN_TIME_OBJECT = 'object is found at run time'
SELF_LOOT = re.compile(r'^[ \t]*entity\.SetLootLegal\((?:true|false)\)[ \t\r]*(?:\n|$)', re.M)
WRAPPER_FIELDS = ('onEnter', 'onExit')


def _text(node, name):
    raw = node['attributes'].get(name, '')
    return raw[1:-1] if len(raw) >= 2 and raw[0] == raw[-1] == '"' else raw


def _walk(node, path='Root', parent=None):
    yield node, path, parent
    for index, child in enumerate(node['children']):
        yield from _walk(child, path + '/' + str(index), node)


def _assignments(root, variable):
    return [_text(node, 'expressions') for node, _, _ in _walk(root) if node['op'] == 'Expression'
            and re.search(r'\$' + re.escape(variable) + r'\s*=(?!=)', _text(node, 'expressions'))]


def _target(node, parent, root):
    """(reference, stand_in) the site names, or a reason string."""
    if node['op'] == 'SetOwner':
        if set(node['attributes']) - {'Objects', 'Owner', 'MarkAsStolen', 'saveVersion'} or node['children']:
            return 'fields outside Objects, Owner, MarkAsStolen'
        if _text(node, 'Owner') not in PLAYER or _text(node, 'MarkAsStolen') != 'false':
            return 'owner is not the player, or the object is marked stolen'
        match = REFERENCE.fullmatch(_text(node, 'Objects'))
        return (match[1], False) if match else RUN_TIME_OBJECT
    code = LOOT.fullmatch(_text(node, 'code').strip()) if node['op'] == 'ExecuteLua' else None
    if not code or set(node['attributes']) - {'code', 'saveVersion'}:
        return 'loot legality of an object found at run time'
    # The variable must hold one level object: assigned once in the tree, from a
    # static reference, by an earlier step of the same sequence.
    written = _assignments(root, code[1])
    earlier = parent['children'][:parent['children'].index(node)] if parent and parent['op'] == 'Sequence' else []
    here = [m for step in earlier if step['op'] == 'Expression'
            for m in [ASSIGN.fullmatch(_text(step, 'expressions').strip())] if m and m[1] == code[1]]
    match = REFERENCE.fullmatch(here[0][2]) if len(written) == 1 and len(here) == 1 else None
    return (match[1], True) if match else 'loot legality of an object found at run time'


def _without_self_loot(node):
    """{field: script} with every `entity.SetLootLegal(..)` statement removed, or None.

    Only a wrapper whose scripts keep another statement qualifies: a node is
    never emptied.
    """
    if node['op'] != 'LuaWrapper' or set(node['attributes']) - {*WRAPPER_FIELDS, 'saveVersion'}:
        return None
    changed = {}
    for field in WRAPPER_FIELDS:
        script = _text(node, field)
        kept = SELF_LOOT.sub('', script)
        if 'SetLootLegal' in kept or (kept != script and not kept.strip()):
            return None
        if kept != script:
            changed[field] = kept.rstrip()
    return changed or None


def apply(model, assets):
    """Rewrite the ownership sites the level binds; return the report.

    `assets` is `campaign_controller_schedule.level_bindings(...)['assets']`:
    {reference: dict(alias, asset_type)} for references bound to one object.
    """
    own = model['behavior_documents'].get('libs/ai/quests/' + model['quest'].lower() + '.xml', dict(trees={}))
    report = dict(quest=model['quest'], owned=[], stand_ins=[], left=[], runtime_verified=False)
    ports = {}
    for tree, body in own['trees'].items():
        for node, path, parent in list(_walk(body['root'])):
            if node['op'] != 'SetOwner' and not (node['op'] in ('ExecuteLua', 'LuaGate', 'LuaWrapper') and any(
                    'SetLootLegal' in _text(node, field) for field in ('code', 'onEnter', 'onExit'))):
                continue
            target = _target(node, parent, body['root'])
            if isinstance(target, tuple) and target[0] not in assets:
                target = 'the level does not bind the object to one entity'
            elif isinstance(target, tuple) and assets[target[0]]['asset_type'] not in WHAT:
                target = 'no retail SetOwner takes this class: ' + assets[target[0]]['asset_type']
            if target == RUN_TIME_OBJECT:
                node.update(op='Success', attributes={}, source_op='SetOwner', stand_in='the owner the level gives')
                report['stand_ins'].append(dict(tree=tree, path=path, operation='SetOwner', target='Success', decision='9a',
                                                approved=DECIDED, effect='the owner stays as the level has it'))
                continue
            scripts = _without_self_loot(node) if not isinstance(target, tuple) else None
            if scripts:
                node['attributes'].update({field: '"' + script + '"' for field, script in scripts.items()})
                node['stand_in'] = 'no loot legality for the acting NPC'
                report['stand_ins'].append(dict(tree=tree, path=path, operation='SetLootLegal', target='removed statement',
                                                decision='10a', approved=DECIDED, fields=sorted(scripts),
                                                effect='looting the NPC who runs the tree stays theft'))
                continue
            if not isinstance(target, tuple):
                report['left'].append(dict(tree=tree, path=path, operation=node['op'], reason=target))
                continue
            reference, stand_in = target
            port = 'own_' + REFERENCE.fullmatch(reference)[2]
            if ports.setdefault(port, assets[reference]['alias']) != assets[reference]['alias']:
                report['left'].append(dict(tree=tree, path=path, operation=node['op'], reason='port name is taken: ' + port))
                continue
            source = node['op']
            node.update(op='OwnershipSignal', attributes=dict(module=model['quest'], port=port), source_op=source)
            if stand_in:
                node['stand_in'] = 'SetOwner'
            report['owned'].append(dict(tree=tree, path=path, operation=source, reference=reference, port=port,
                                        stand_in=stand_in, **assets[reference]))
    return report


def quest_assets(report):
    """The quest side's input: one row per port (`bindings['owned_assets']`)."""
    rows = {}
    for site in report['owned']:
        rows[site['port']] = dict(port=site['port'], alias=site['alias'], asset_type=site['asset_type'])
    return [rows[port] for port in sorted(rows)]


def _signal(compiler, source, owner):
    record = dict(kind='action', quest=source['attributes']['module'], port=source['attributes']['port'],
                  source_operation='OwnershipSignal')
    record['name'] = compiler.bridge._name('action', record['quest'], record['port'])
    compiler.bridge.actions[record['name']] = record
    return ET.Element('SendAIConceptSignal_' + record['name'])


LOWERINGS = {'OwnershipSignal': _signal}
