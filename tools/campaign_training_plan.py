"""Extract reusable training arrival and borrowed-equipment contracts.

This is a conversion plan, not permission to execute a flattened source tree.
The complete source programs accompany each plan for lowering and provenance.
Unsupported branches are errors; unresolved native resources block publication.
"""
import copy
import re

from campaign_combat_plan import attrs, one, walk
from campaign_quest_bridge import UnsupportedOperation


def sequence(root):
    if root['op'] != 'Root':
        raise UnsupportedOperation('Training callback must have a complete Root')
    if any(n['op'] not in ('OnInit', 'Behavior') for n in root['children']):
        raise UnsupportedOperation('Training callback has unconverted exit handlers')
    body = one((n for n in root['children'] if n['op'] == 'Behavior'), 'Missing training callback body')
    seq = one(body['children'], 'Training callback has multiple bodies')
    if seq['op'] != 'Sequence':
        raise UnsupportedOperation('Training callback requires ordered operations')
    return seq['children']


def subject(value):
    # These denote the executing tutor; other names remain explicit references.
    return 'actor' if value in ('', 'this.id', '$this.id') else value


def borrowed_equipment(prepare, cleanup):
    """Pair CreateItem outputs with RemoveItem handles, never item-type counts."""
    before, after = sequence(prepare), sequence(cleanup)
    prepare_ops = {'AddBuff', 'CreateItem', 'EquipItem', 'InstantSendMessageToNPC'}
    cleanup_ops = {'RemoveBuffs', 'InstantHolsterWeapon', 'InstantSendMessageToNPC', 'RemoveItem', 'EquipItem', 'AddBuff'}
    for nodes, allowed in ((before, prepare_ops), (after, cleanup_ops)):
        for node in nodes:
            if node['op'] not in allowed or node['children']:
                raise UnsupportedOperation('Unconverted training equipment operation: ' + node['op'])
    leases = {}
    for index, node in enumerate(before):
        a = attrs(node)
        if node['op'] == 'CreateItem':
            handle = a.get('CreatedItem', '').removeprefix('$')
            if not handle or handle in leases:
                raise UnsupportedOperation('Missing or reused training item handle')
            if not re.fullmatch(r'[0-9a-fA-F-]{36}', a.get('ItemGUID', '')) or a.get('Amount') != '1':
                raise UnsupportedOperation('Training item must resolve to one source item instance')
            leases[handle] = dict(handle=handle, item=a['ItemGUID'], owner=subject(a['Target']),
                                 create_index=index, equip_indices=[], remove_index=None)
        elif node['op'] == 'EquipItem':
            handle = a.get('item', '').removeprefix('$')
            lease = leases.get(handle)
            if lease is None or lease['owner'] != subject(a.get('Target', '')):
                raise UnsupportedOperation('Training equips an unowned or uncreated item')
            lease['equip_indices'].append(index)
        elif node['op'] == 'InstantSendMessageToNPC' and a.get('type') != 'player:drawWeapon':
            raise UnsupportedOperation('Unconverted preparation message: ' + a.get('type', ''))
    if not leases:
        raise UnsupportedOperation('Training preparation creates no borrowed equipment')
    for index, node in enumerate(after):
        a = attrs(node)
        if node['op'] == 'RemoveItem':
            handle = a.get('Item', '').removeprefix('$')
            lease = leases.get(handle)
            if (lease is None or lease['remove_index'] is not None or a.get('ItemGUID')
                    or a.get('Amount') != '0' or a.get('FailOnDoesntExist') != 'false'
                    or lease['owner'] != subject(a.get('Source', ''))):
                raise UnsupportedOperation('Training cleanup is not an idempotent owned-handle removal')
            lease['remove_index'] = index
        elif node['op'] == 'InstantSendMessageToNPC' and a.get('type') != 'player:holsterWeapon':
            raise UnsupportedOperation('Unconverted cleanup message: ' + a.get('type', ''))
    if any(not v['equip_indices'] or v['remove_index'] is None for v in leases.values()):
        raise UnsupportedOperation('Training equipment has incomplete equip/cleanup lifetime')
    return dict(leases=list(leases.values()), prepare=copy.deepcopy(prepare), cleanup=copy.deepcopy(cleanup),
                cleanup_on=['completion', 'cancellation', 'preparation_failure', 'quest_shutdown'],
                publication_ready=False,
                requirements=['native item registration', 'persistent instance handles',
                              'acknowledged preparation and cleanup', 'restore source equipment',
                              'convert protection and recovery effects'])


def arrival(root):
    """Resolve a guarded Move -> objective completion using its QuestPlace link."""
    body = sequence(root)
    guard = body[0]
    a = attrs(guard)
    if (guard['op'] != 'QuestObjectiveCondition' or a.get('quest') not in ('', '$__object.name')
            or a.get('function') != 'IsObjectiveStarted'):
        raise UnsupportedOperation('Training arrival is not guarded by a local started objective')
    branch = one(guard['children'], 'Ambiguous arrival conditional')
    seq = one(branch['children'], 'Ambiguous arrival sequence')
    if branch['op'] != 'Then' or seq['op'] != 'Sequence' or [n['op'] for n in seq['children']] != ['Move', 'SetQuestObjective']:
        raise UnsupportedOperation('Training arrival must complete after a successful Move')
    move, completion = seq['children']
    c = attrs(completion)
    if c.get('quest') not in ('', '$__object.name') or c.get('objective') != a.get('objective') or c.get('function') != 'CompleteObjective':
        raise UnsupportedOperation('Arrival completion does not match its objective')
    destination = attrs(move).get('destinationSpecification')
    links = [attrs(n) for init in root['children'] if init['op'] == 'OnInit'
             for n in walk(init) if n['op'] == 'LinkDataFilter' and attrs(n).get('Child') == destination]
    link = one(links, 'Arrival needs one source place binding')
    match = re.fullmatch(r"\$QuestPlace\s*==\s*'([A-Za-z_]\w*)'", link.get('condition', ''))
    if link.get('tag') != 'QuestPlace' or not match:
        raise UnsupportedOperation('Arrival uses an unresolved place selector')
    return dict(objective=a['objective'], place_role=match[1], move=attrs(move),
                source=copy.deepcopy(root), publication_ready=False,
                requirements=['world place binding', 'complete movement behavior conversion',
                              'invocation-scoped success/failure callbacks'])
