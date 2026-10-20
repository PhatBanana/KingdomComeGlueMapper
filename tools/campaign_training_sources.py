"""Resolve equipment callbacks by authored smart-object registrations.

The caller selects a controller program, not a quest-specific implementation.
Pairing follows its calls and exact borrowed-item lifetimes, never tag spelling.
"""
import copy
import re

from campaign_behavior_requests import resolve
from campaign_combat_plan import attrs, walk
from campaign_training_plan import borrowed_equipment
from campaign_quest_bridge import UnsupportedOperation


def resolve_equipment(model, document, tree):
    try:
        controller = model['behavior_documents'][document]['trees'][tree]
    except KeyError as exc:
        raise UnsupportedOperation('Training controller program is not imported') from exc
    calls, unresolved = [], []
    def visit(node, path):
        if node['op'] == 'CallBehavior':
            a = attrs(node)
            name = a.get('BehaviorName', '')
            if name and not name.startswith('$') and a.get('Target', '').lstrip('$') == '__object.id':
                try:
                    target = resolve(model, dict(source=a['Target'], tree=name))
                    calls.append(dict(path=path, name=name, target=a['Target'], **target))
                except UnsupportedOperation as error:
                    unresolved.append(dict(path=path, reason=str(error)))
        for i, child in enumerate(node['children']): visit(child, path + '/' + str(i))
    visit(controller['root'], 'Root')
    # Unresolved static calls could be a second equipment pair. Do not select
    # the first working pair and silently omit an unimported callback.
    if unresolved:
        raise UnsupportedOperation('Unresolved controller callbacks: ' + '; '.join(r['reason'] for r in unresolved))
    pairs = []
    for prepare in calls:
        if not any(n['op'] == 'CreateItem' for n in walk(prepare['program']['root'])): continue
        for cleanup in calls:
            if prepare is cleanup: continue
            if not any(n['op'] == 'RemoveItem' for n in walk(cleanup['program']['root'])): continue
            try: plan = borrowed_equipment(prepare['program']['root'], cleanup['program']['root'])
            except UnsupportedOperation: continue
            pairs.append((prepare, cleanup, plan))
    if len(pairs) != 1:
        raise UnsupportedOperation('Training controller requires one unambiguous borrowed-equipment pair')
    prepare, cleanup, plan = pairs[0]
    variables = {}
    # Retain referenced controller variables and every callback-local variable.
    # Unrelated legacy tutorial message types belong to the controller adapter,
    # not the equipment callbacks. Overinclusive token matching is intentional:
    # uncertain references remain dependency checks rather than disappearing.
    referenced = set()
    for program in (prepare['program'], cleanup['program']):
        for node in walk(program['root']):
            for value in attrs(node).values(): referenced.update(re.findall(r'[A-Za-z_]\w*', value))
    changed = True
    while changed:
        before = len(referenced)
        for variable in controller['variables']:
            if variable['name'] in referenced:
                referenced.update(re.findall(r'[A-Za-z_]\w*', variable.get('values', '')))
        changed = len(referenced) != before
    for program in (dict(variables=[v for v in controller['variables'] if v['name'] in referenced]),
                    prepare['program'], cleanup['program']):
        for variable in program['variables']:
            name = variable['name']
            if name in variables and variables[name] != variable:
                raise UnsupportedOperation('Incompatible callback variable scopes: ' + name)
            variables[name] = copy.deepcopy(variable)
    return dict(controller=dict(document=document, tree=tree),
                prepare=copy.deepcopy(prepare), cleanup=copy.deepcopy(cleanup),
                variables=list(variables.values()), equipment=plan,
                runtime_validated=False, publication_ready=False)
