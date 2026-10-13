"""Discover work programs invoked through source behavior-tag registries.

An AI IncludeTree is not the only program dependency: smart-area requests
dispatch through database tags. Preserve all matching implementations and
report dynamic/fallback selection, rather than choosing one actor's routine.
"""
import re


def discover(trees, table_rows, *, include_area_context=False):
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
            if include_area_context:
                call['area_context'] = area_context(call['candidates'], table_rows)
                call['candidates'].extend(call['area_context']['programs'])
            calls.append(call)
    return calls


def area_context(candidates, table_rows):
    """A requested job also depends on its area's callbacks and sibling jobs.

    Work loops dispatch other behaviors dynamically. Discovering only their
    first named entry loses both the area lifecycle and those subsequent jobs.
    Retain all possible source areas; placement narrows which one is used.
    """
    from quest_import import behavior_path
    tags={c['row']['sa_behaviour_tag_id'] for c in candidates
          if c['table']=='sa_behaviour_tag' and c['row'].get('sa_behaviour_tag_id')}
    if not tags:
        return dict(templates=[],programs=[])
    links=table_rows('sa_smart_area2sa_behaviour_tag')
    ids={r['sa_smart_area_id'] for r in links if r['sa_behaviour_tag_id'] in tags}
    areas=[dict(r) for r in table_rows('sa_smart_area') if r['sa_smart_area_id'] in ids]
    sibling_ids={r['sa_behaviour_tag_id'] for r in links if r['sa_smart_area_id'] in ids}
    programs=[]
    for row in table_rows('sa_behaviour_tag'):
        if row['sa_behaviour_tag_id'] in sibling_ids and row.get('tree_file') and row.get('tree_name'):
            programs.append(dict(kind='area_behavior',table='sa_behaviour_tag',row=dict(row),
                tag=row['sa_behaviour_tag_name'],file=behavior_path(row['tree_file']),tree=row['tree_name']))
    brains={r['brain_id'] for r in areas if r.get('brain_id')}
    if brains:
        sub_ids={r['subbrain_id'] for r in table_rows('brain2subbrain') if r['brain_id'] in brains}
        types={r['subbrain_type_id']:r['subbrain_type_name'] for r in table_rows('subbrain_type')}
        schemas={'SmartArea':('subbrain_smart_area',('on_enter_tree','on_exit_tree','on_update_tree','on_request_tree','on_release_tree')),
                 'SmartObject':('subbrain_smart_object',('on_update_tree','on_request_tree','on_release_tree')),
                 'BehaviorTree':('subbrain_behaviour_tree',('tree_name',))}
        for sub in table_rows('subbrain'):
            if sub['subbrain_id'] not in sub_ids:continue
            schema=schemas.get(types[sub['subbrain_type']])
            if schema is None:continue # SubbrainAdapter reports unsupported runtime types.
            table,fields=schema
            for row in table_rows(table):
                if row['subbrain_id']!=sub['subbrain_id']:continue
                for field in fields:
                    if row.get(field):
                        programs.append(dict(kind='area_brain_callback',table=table,row=dict(row),
                            callback=field,file=behavior_path(row['file_name']),tree=row[field]))
    unique={(p['file'],p['tree']):p for p in programs}
    return dict(templates=areas,programs=list(unique.values()))
