"""Track behavior invocations hidden in legacy message initializers."""
import re

from campaign_quest_bridge import UnsupportedOperation
from quest_import import literal
from quest_import import behavior_path
from campaign_sources import key


MESSAGE = 'combat:stimulus:customBehaviorRequest'


def target(source):
    """Return the statically named behavior; reject unresolved dispatch fields.

    A serialized message type alone is not executable behavior registration.
    Callers must include the target tree in their dependency closure and bind
    the message to a verified native consumer before publishing it.
    """
    if source['op'] not in ('SendMessageToNPC', 'InstantSendMessageToNPC'):
        return None
    attrs = source['attributes']
    if literal(attrs.get('type', '')) != MESSAGE:
        return None
    text = literal(attrs.get('values', ''))
    fields, offset = {}, 0
    pattern = re.compile(r'\s*(\w+)\(([^()]*)\)\s*(?:,|$)')
    while offset < len(text):
        match = pattern.match(text, offset)
        if not match or match[1] in fields:
            raise UnsupportedOperation('Unresolved custom behavior request initializer')
        fields[match[1]] = match[2].strip()
        offset = match.end()
    if set(fields) != {'behaviorSource', 'behaviorName', 'entity'}:
        raise UnsupportedOperation('Unconverted custom behavior request fields')
    name = fields['behaviorName']
    if not re.fullmatch(r"(?:[A-Za-z_]\w*|'[A-Za-z_]\w*')", name):
        raise UnsupportedOperation('Dynamic custom behavior name requires dispatch conversion')
    return dict(tree=name.strip("'"), source=fields['behaviorSource'], entity=fields['entity'])


def dependencies(root):
    """Collect runtime children only, never disconnected editor branches."""
    result = []
    def visit(node, path):
        try:
            request = target(node)
            if request:
                result.append(dict(path=path, **request))
        except UnsupportedOperation as error:
            result.append(dict(path=path, error=str(error)))
        for i, child in enumerate(node['children']):
            visit(child, path + '/' + str(i))
    visit(root, 'Root')
    return result


def resolve(model, request):
    """Resolve a request's registration tag, not an assumed tree name.

    Several retail registrations deliberately give a shared tree a different
    public tag. The actor runs that tree in the requesting controller's scope.
    """
    if request['source'].lstrip('$') not in ('this.id', '__object.id'):
        raise UnsupportedOperation('External behavior source requires controller binding')
    registrations = [entry for entry in
        (model.get('controller_registration') or {}).get('entry_points', [])
        if entry.get('kind') == 'behavior_callback' and entry.get('name') == request['tree']]
    if len(registrations) != 1:
        raise UnsupportedOperation('Missing or ambiguous behavior callback registration: ' + request['tree'])
    entry = registrations[0]
    document = key(behavior_path(entry['file']))
    tree = model.get('behavior_documents', {}).get(document, {}).get('trees', {}).get(entry['tree'])
    if tree is None:
        raise UnsupportedOperation('Registered behavior tree is not imported: ' + document + ':' + entry['tree'])
    return dict(document=document, tree=entry['tree'], program=tree)
