"""Discover controller-owned schedule changes without executing their guards.

KCD1 message registration is not a KCD2 scheduler consumer. Preserve each
request's actor, handle, policy and AST location for the native host adapter.
"""
import re

from campaign_behavior_requests import resolve
from campaign_quest_bridge import UnsupportedOperation
from quest_import import literal


MESSAGE = 'daycycle:change'


def request(node):
    if node['op'] not in ('InstantSendMessageToNPC', 'SendMessageToNPC'):
        return None
    a = {k: literal(v) for k, v in node['attributes'].items()}
    if a.get('type') != MESSAGE:
        return None
    text, fields, offset = a.get('values', ''), {}, 0
    pattern = re.compile(r"\s*(\w+)\(\s*('[^'\r\n]*'|[^(),'\r\n]+)\s*\)\s*(?:,|$)")
    while text[offset:].strip():
        match = pattern.match(text, offset)
        if not match or match[1] in fields:
            raise UnsupportedOperation('Unresolved or duplicate daycycle request field')
        fields[match[1]] = match[2].strip()
        offset = match.end()
    if fields.get('add') not in ('true', 'false'):
        raise UnsupportedOperation('Daycycle change requires an explicit add/remove operation')
    handle = fields.get('handle', '')
    if not re.fullmatch(r"'[A-Za-z_]\w*'", handle):
        raise UnsupportedOperation('Dynamic daycycle handle requires runtime identity conversion')
    actor = a.get('target', '')
    if not actor:
        raise UnsupportedOperation('Daycycle change requires an explicit actor')
    result = dict(actor=actor, handle=handle[1:-1], add=fields['add'] == 'true')
    if not result['add']:
        if set(fields) != {'add', 'handle'}:
            raise UnsupportedOperation('Unconverted daycycle removal fields')
        return result
    # daycycle:change.once is a bool without an explicit initializer in the
    # shipped source TypeDefinitions. Its zero/default value is false. Do not
    # infer once=true from the fact that a quest sends the request only once.
    fields.setdefault('once', 'false')
    if set(fields) != {'add', 'handle', 'name', 'immediate', 'once', 'priority', 'sourceId'}:
        raise UnsupportedOperation('Daycycle addition requires explicit scheduling policy')
    if not re.fullmatch(r"'[A-Za-z_]\w*'", fields['name']):
        raise UnsupportedOperation('Dynamic daycycle behavior requires runtime dispatch conversion')
    if (fields['immediate'] not in ('true', 'false') or fields['once'] not in ('true', 'false')
            or not re.fullmatch(r'\d+', fields['priority']) or not 0 <= int(fields['priority']) <= 255):
        raise UnsupportedOperation('Unsupported daycycle priority or lifetime')
    return dict(result, behavior=fields['name'][1:-1], source=fields['sourceId'],
                priority=int(fields['priority']), immediate=fields['immediate'] == 'true',
                once=fields['once'] == 'true')


def dependencies(model, root):
    """Keep branches and callback identities; this is not a startup action list."""
    result = []
    def visit(node, path, ancestors):
        try:
            value = request(node)
            if value is not None:
                record = dict(path=path, ancestors=ancestors, operation=node['op'],
                              attributes=dict(node['attributes']), **value)
                if value['add']:
                    try:
                        resolved = resolve(model, dict(source=value['source'], tree=value['behavior']))
                        record['callback'] = {k: resolved[k] for k in ('document', 'tree')}
                    except UnsupportedOperation as error:
                        record['error'] = str(error)
                result.append(record)
        except UnsupportedOperation as error:
            result.append(dict(path=path, ancestors=ancestors, error=str(error)))
        for i, child in enumerate(node['children']):
            visit(child, path + '/' + str(i), ancestors + [dict(op=node['op'], attributes=dict(node['attributes']))])
    visit(root, 'Root', [])
    return result
