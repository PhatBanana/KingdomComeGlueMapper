"""Lower source work requests to the unified native behavior dispatcher."""
import re
import xml.etree.ElementTree as ET

from campaign_quest_bridge import UnsupportedOperation
from quest_import import literal


def lower(source, catalog):
    # KCD1 exposes separate area/object request nodes. KCD2's CallBehavior
    # targets a smart entity. For an exclusive single behavior the request
    # has no ranking/fallback policy to reproduce, so preserve the name and
    # request flags directly; the target template registers the source name.
    from campaign_behavior import reference, quote
    op = source['op']
    field = {'SmartAreaBehaviorTag': 'smartArea', 'SmartObjectBehaviorTag': 'smartObject'}[op]
    attrs = {k: literal(v) for k, v in source['attributes'].items()}
    allowed = {field, 'preferredBehaviors', 'forbiddenBehaviors', 'preferredBehaviorsOnly',
               'stopAfterFirstFound', 'ignoreDropUnloading', 'nodeLabel'}
    if set(attrs) - allowed:
        raise UnsupportedOperation('Unknown source work-request parameters')
    name = attrs.get('preferredBehaviors', '')
    if attrs.get('preferredBehaviorsOnly') != 'true' or attrs.get('forbiddenBehaviors'):
        raise UnsupportedOperation('Ranked or excluded work requests require selection conversion')
    if not re.fullmatch(r'[A-Za-z_]\w*', name):
        raise UnsupportedOperation('Multiple or dynamic preferred jobs require selection conversion')
    target = reference(attrs.get(field, ''))
    if not target:
        raise UnsupportedOperation('Work request has no target smart entity')
    native = dict(Target=target, BehaviorName=quote(name))
    for key in ('stopAfterFirstFound', 'ignoreDropUnloading'):
        if key in attrs:
            if attrs[key] not in ('true', 'false'):
                raise UnsupportedOperation('Invalid work-request flag: ' + key)
            native[key] = attrs[key]
    if 'nodeLabel' in attrs:
        native['nodeLabel'] = attrs['nodeLabel']
    if 'CallBehavior' not in catalog['nodes'] or set(native) - set(catalog['nodes']['CallBehavior']['attributes']):
        raise UnsupportedOperation('Native work-request dispatcher contract is unavailable')
    return ET.Element('CallBehavior', native)
