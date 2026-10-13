"""Discover work programs invoked through source behavior-tag registries.

An AI IncludeTree is not the only program dependency: smart-area requests
dispatch through database tags. Preserve all matching implementations and
report dynamic/fallback selection, rather than choosing one actor's routine.
"""
import re


def discover(trees, table_rows):
    from quest_import import walk, literal, behavior_path
    calls = []
    for tree_name, tree in trees.items():
        for index, node in enumerate(walk(tree['root'])):
            if node['op'] not in ('SmartAreaBehaviorTag', 'SmartObjectBehaviorTag', 'CallBehavior'):
                continue
            attrs = node['attributes']
            direct = node['op'] == 'CallBehavior'
            preferred = literal(attrs.get('BehaviorName' if direct else 'preferredBehaviors', ''))
            registries = ('sa_behaviour_tag', 'so_behaviour_tag') if direct else (
                ('sa_behaviour_tag',) if node['op'] == 'SmartAreaBehaviorTag' else ('so_behaviour_tag',))
            call = dict(tree=tree_name, preorder_index=index, operation=node['op'],
                arguments=dict(attrs), candidates=[], unresolved=[])
            if not re.fullmatch(r'[A-Za-z_]\w*(?:\s*,\s*[A-Za-z_]\w*)*', preferred):
                call['unresolved'].append('Dynamic or empty preferred work selection requires runtime dispatch')
            else:
                for name in re.split(r'\s*,\s*', preferred):
                    matches = [(registry, r) for registry in registries for r in table_rows(registry)
                               if r.get(registry + '_name') == name]
                    if not matches:
                        call['unresolved'].append('Source work behavior is not registered: ' + name)
                    for registry, row in matches:
                        if not row.get('tree_file') or not row.get('tree_name'):
                            call['unresolved'].append('Source work behavior has no program: ' + name)
                        else:
                            call['candidates'].append(dict(tag=name, table=registry, row=dict(row),
                                file=behavior_path(row['tree_file']), tree=row['tree_name']))
            if not direct and literal(attrs.get('preferredBehaviorsOnly', 'false')) != 'true':
                call['unresolved'].append('Unrestricted area fallback needs the placed area behavior registry')
            calls.append(call)
    return calls
