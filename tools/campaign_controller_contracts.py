"""Generic source-side preparation for quest-controller conversion (C2).

`prepare(models)` returns rewritten copies of quest IR models plus a report;
`register()` adds operation contracts to the behaviour compiler. Nothing here
names a quest, an actor or a site. Three rules:

1. Document scope. A KCD1 controller tree that is entered through IncludeTree
   or a callback runs in its caller's variable scope: retail callback trees use
   names such as `t_actors[x]` with an empty <Variables/> of their own. A bare
   index `name[key]` is therefore typed from the controller document when the
   tree does not declare `name`: every tree of that document that declares it
   must declare it associative, and `key` must not itself be a variable in
   either scope. The key is then quoted, exactly as
   campaign_behavior.associative_indexes does for a locally declared map. No
   declaration is added to the tree, so no variable is shadowed.

2. Renamed operations. An operation whose KCD2 node has another name and the
   same fields is renamed, with its attributes mapped one-to-one. Each entry
   records its evidence; an attribute outside the map blocks the node.

3. Same-name contracts. An operation that exists in KCD2 under the same name,
   whose source attributes all occur on native examples, gets a contract with
   the serialisation kinds read from those examples.

Not runtime-verified.
"""
import copy
import re

SCRIPT_ATTRIBUTES = {'code', 'onEnter', 'onExit', 'onUpdate'}
INDEX = re.compile(r'(\$?)([A-Za-z_]\w*)\[([A-Za-z_]\w*)\]')
QUOTED = re.compile(r'''(&apos;.*?&apos;|'(?:\\.|[^'\\])*')''')

# source op -> (native op, {source attribute: native attribute}, evidence)
RENAMES = {
    'TurnBody': ('Turn', dict(destinationSpecification='target', alignWith='align', destinationType='destinationType',
                              stopWithinAngle='stopWithinAngle', randomMinAngle='randomMinAngle',
                              randomMaxAngle='randomMaxAngle', randomTurnRightChance='randomTurnRightChance',
                              stopRunninganimation='stopRunninganimation'),
                 'KCD2 Turn carries the six unrenamed TurnBody fields verbatim (AI/_lukas/test_lukas_helper.xml); '
                 'target/align hold a variable and a boolean as destinationSpecification/alignWith do. Inference.'),
}
# Kinds follow native serialisation: GameOver Reason="DiedInCombat" (bare),
# ExecuteSoundTrigger triggerName="'boar_hit'" entity="$this.id",
# HasActiveThreats SoulWUID="$__player", UnionOp booleans bare.
CONTRACTS = {
    'Turn': dict(target='reference', align='value', destinationType='value', stopWithinAngle='value',
                 randomMinAngle='value', randomMaxAngle='value', randomTurnRightChance='value',
                 stopRunninganimation='value'),
    'GameOver': dict(Reason='value'),
    'ExecuteSoundTrigger': dict(entity='reference', triggerName='string_expression', stop='value'),
    'HasActiveThreats': dict(SoulWUID='reference', FailSubtMissing='value', saveVersion='value'),
    'UnionOp': dict(Results='value', Advance='value', EndOp='value', ShortCircuit='value', LocalNodalyzers='value'),
}


def register():
    """Add the contracts above to the behaviour compiler. Existing entries win."""
    import campaign_behavior
    added = [op for op in CONTRACTS if op not in campaign_behavior.CONTRACTS]
    for op in added:
        campaign_behavior.CONTRACTS[op] = dict(CONTRACTS[op])
    return added


def document_scope(payload):
    """{name: declaration} for names every declaring tree of a document agrees on."""
    seen, conflict = {}, set()
    for tree in payload['trees'].values():
        for variable in tree['variables']:
            name, shape = variable.get('name'), (variable.get('form'), variable.get('type'))
            if name in seen and (seen[name].get('form'), seen[name].get('type')) != shape:
                conflict.add(name)
            seen.setdefault(name, variable)
    return {name: v for name, v in seen.items() if name not in conflict}


def _walk(node, path='Root'):
    yield node, path
    for index, child in enumerate(node['children']):
        yield from _walk(child, path + '/' + str(index))


def prepare(models):
    """Return (models, report). Inputs are not modified."""
    models = copy.deepcopy(models)
    report = dict(scope_resolutions=[], renamed=[], rename_blocked=[], runtime_verified=False)
    for model in models:
        for document, payload in model['behavior_documents'].items():
            scope = document_scope(payload)
            for name, tree in payload['trees'].items():
                local = {v.get('name') for v in tree['variables']}
                site = dict(quest=model['quest'], document=document, tree=name)

                def typed(match, attribute, path):
                    base, key = match[2], match[3]
                    if base in local or key in local or key in scope:
                        return match[0]
                    if scope.get(base, {}).get('form') != 'associative':
                        return match[0]
                    report['scope_resolutions'].append(dict(site, path=path, attribute=attribute, source=match[0]))
                    return match[1] + base + "['" + key + "']"

                for node, path in _walk(tree['root']):
                    for attribute, raw in list(node['attributes'].items()):
                        if attribute in SCRIPT_ATTRIBUTES or '[' not in raw:
                            continue
                        parts = QUOTED.split(raw)
                        node['attributes'][attribute] = ''.join(
                            part if i % 2 else INDEX.sub(lambda m: typed(m, attribute, path), part)
                            for i, part in enumerate(parts))
                    if node['op'] in RENAMES:
                        target, mapping, evidence = RENAMES[node['op']]
                        extra = sorted(set(node['attributes']) - set(mapping))
                        if extra or node['children']:
                            report['rename_blocked'].append(dict(site, path=path, operation=node['op'], unmapped=extra))
                            continue
                        report['renamed'].append(dict(site, path=path, source=node['op'], target=target))
                        node['attributes'] = {mapping[k]: v for k, v in node['attributes'].items()}
                        node['source_op'], node['op'] = node['op'], target
    report['rename_evidence'] = {source: entry[2] for source, entry in RENAMES.items()}
    return models, report
