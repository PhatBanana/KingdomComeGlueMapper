"""Compare authoring objectives with effective retail records by stable ID.

The exported editor graph can lag the patched runtime database, just like its
transition edges. Preserve the disagreement; use the runtime names and flags
without rewriting source documents or inventing aliases for behavior scripts.
"""


def objective_differences(graph, tables):
    rows = tables['quest_objective']['rows']
    runtime = {r['objective_id']: r for r in rows}
    if len(runtime) != len(rows):
        raise ValueError('Duplicate database objective ID')
    authored = {}
    for identity, node in graph['nodes'].items():
        if node['attributes'].get('Class') != 'Quest:Objective':
            continue
        inputs = [p['attributes'] for p in node.get('payload', []) if p['op'] == 'Inputs']
        if len(inputs) != 1 or 'Name' not in inputs[0]:
            raise ValueError('Missing or ambiguous authoring objective inputs: ' + identity)
        authored[identity] = inputs[0]
    result = dict(graph_only={i: r['Name'] for i, r in authored.items() if i not in runtime},
                  table_only={i: r['objective_name'] for i, r in runtime.items() if i not in authored},
                  name_mismatches=[], flag_mismatches=[])
    for identity, row in runtime.items():
        attrs = authored.get(identity)
        for source_field, field in [('IsHidden', 'is_hidden'), ('IsExclusive', 'is_exclusive')]:
            # Import-only fixtures may omit flags; the emitter requires them.
            if field in row and row[field] not in ('True', 'False'):
                raise ValueError('Invalid runtime objective boolean: ' + identity + '.' + field)
            if attrs is not None and source_field in attrs and attrs[source_field] not in ('0', '1'):
                raise ValueError('Invalid authoring objective boolean: ' + identity + '.' + source_field)
            if attrs is not None and source_field in attrs and field in row and (
                    (attrs[source_field] == '1') != (row[field] == 'True')):
                result['flag_mismatches'].append(dict(id=identity, objective=row['objective_name'],
                    field=field, graph=attrs[source_field], table=row[field]))
        if attrs is not None and attrs['Name'] != row['objective_name']:
            result['name_mismatches'].append(dict(id=identity, graph=attrs['Name'], table=row['objective_name']))
    return result
