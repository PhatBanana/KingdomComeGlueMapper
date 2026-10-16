"""Reuse compatible shipped human animation fragments for legacy work calls.

Only calls with verified native fragment/tag combinations and without a legacy
action handle are lowered here. Explicit object/helper alignment is preserved;
item events, context locks and tracked handles still require separate adapters.
"""
import hashlib
import re
from pathlib import Path
import xml.etree.ElementTree as ET
import zipfile

from campaign_quest_bridge import UnsupportedOperation
from quest_import import literal
from upgrade_map import read


DATABASES = ('Animations/Mannequin/ADB/kcd_male_database.adb',
             'Animations/Mannequin/ADB/wh_female_database.adb')


def fragment_catalog(game):
    available, provenance, controllers = [], [], {}
    with zipfile.ZipFile(Path(game) / 'Data/Animations.pak') as archive:
        for name in DATABASES:
            data = read(archive, name)
            root = ET.fromstring(data)
            fragments = root.find('FragmentList')
            if root.tag != 'AnimDB' or fragments is None:
                raise ValueError('Unsupported native animation database')
            # A procedural-only scope is not evidence of a body animation.
            variants = {(node.tag, tuple(sorted(filter(None, f.get('FragTags', '').split('+')))))
                        for node in fragments for f in node.findall('Fragment')
                        if not f.get('Tags', '') and f.find('AnimLayer/Animation') is not None}
            available.append(variants)
            controller = 'female' if 'female' in name else 'male'
            controller_variants = {}
            for fragment, tags in sorted(variants):
                controller_variants.setdefault(fragment, []).append(list(tags))
            controllers[controller] = controller_variants
            provenance.append(dict(path=name, sha256=hashlib.sha256(data).hexdigest()))
    shared = set.intersection(*available)
    variants = {}
    for name, tags in sorted(shared):
        variants.setdefault(name, []).append(list(tags))
    return dict(common_human_fragments=sorted(name for name,tags in shared if not tags),
                common_human_variants=variants, controller_variants=controllers, provenance=provenance)


def lower(source, catalog, controllers=None):
    from campaign_behavior import quote, reference
    attrs = {k: literal(v) for k, v in source['attributes'].items()}
    allowed = {'animation', 'tags', 'context', 'keepContext', 'InterruptSafeStart',
               'SlavedObject', 'ClearSlaveAnimOnExit', 'AnimationWUID', 'SmartObject', 'HelperID'}
    if set(attrs) - allowed or source['children']:
        raise UnsupportedOperation('Unknown legacy work animation parameters')
    for field in ('context', 'SlavedObject', 'AnimationWUID'):
        if attrs.get(field):
            raise UnsupportedOperation('Work animation requires event/context/alignment conversion: ' + field)
    if bool(attrs.get('SmartObject')) != bool(attrs.get('HelperID')):
        raise UnsupportedOperation('Work alignment requires both object and helper references')
    for field, default in (('keepContext', 'false'), ('InterruptSafeStart', 'AUTO'),
                           ('ClearSlaveAnimOnExit', 'true')):
        if attrs.get(field, default) != default:
            raise UnsupportedOperation('Unsupported work animation lifecycle: ' + field)
    fragment = attrs.get('animation', '')
    evidence = catalog.get('work_animations', {})
    tags = attrs.get('tags', '')
    if tags:
        if not re.fullmatch(r'[A-Za-z_]\w*(?:[+,][A-Za-z_]\w*)*', tags):
            raise UnsupportedOperation('Dynamic or malformed work animation tags require runtime variant conversion')
        selected = sorted(set(re.split('[+,]', tags)))
        compatible = selected in evidence.get('common_human_variants', {}).get(fragment, [])
    else:
        selected = []
        compatible = fragment in evidence.get('common_human_fragments', [])
    if controllers:
        compatible = all(selected in evidence.get('controller_variants', {}).get(controller, {}).get(fragment, [])
                         for controller in controllers)
    if not compatible:
        raise UnsupportedOperation('Work animation lacks a compatible native human fragment: ' + fragment)
    values = dict(fragment=quote(fragment), tags=quote(','.join(selected)) if selected else '', context='', keepContext='false',
                  eventReferenceObject='', alignObject='', slaveObject='', resourceOverride='')
    if attrs.get('SmartObject'):
        values['alignObject'] = reference(attrs['SmartObject'])
        values['alignHelper'] = reference(attrs['HelperID'])
    contract = catalog['nodes'].get('AnimationAction')
    if contract is None or set(values) - set(contract['attributes']):
        raise UnsupportedOperation('Native work animation action contract is unavailable')
    return ET.Element('AnimationAction', values)


def child_controllers(source, child, inherited):
    """Narrow only a proven branch about the executing actor's own gender.

    Calls into another behavior stay separately compiled; a check of the
    player, a target or another actor cannot prove this animation's controller.
    """
    attrs = {k:literal(v) for k,v in source['attributes'].items()}
    op, matched, positive = source['op'], None, True
    if op == 'HasGenderCheck' and attrs.get('SoulWUID', '') in ('', 'this.id', '$this.id'):
        matched = {'Male':'male', 'Female':'female'}.get(attrs.get('Gender'))
    elif op in ('IfCondition', 'IfElseCondition'):
        condition = re.fullmatch(r'\s*\$b_soul\.gender\s*(==|~=)\s*\$enum:humanGender\.(male|female)\s*',
                                 attrs.get('condition',''))
        if condition:
            matched, positive = condition[2], condition[1] == '=='
    if matched:
        if op == 'IfCondition':
            branch = positive
        elif child['op'] in ('Then', 'Else'):
            branch = positive if child['op'] == 'Then' else not positive
        else:
            return inherited
        selected = matched if branch else ('female' if matched == 'male' else 'male')
        # Keep unreachable contradictory branches conservative instead of
        # silently deleting source nodes or asserting a different controller.
        return (selected,) if inherited is None or selected in inherited else inherited
    if op in ('Root','Sequence','Selector','Parallel','Then','Else','Child','Behavior','OnInit',
              'IfCondition','IfElseCondition','HasGenderCheck','While','Loop','For','ForEach',
              'FuseBox','AtomicDecorator','Invertor','SuppressFailure','TryCatch','Subtree',
              'OnSuccess','OnFail','LoopUntil','LuaWrapper'):
        return inherited
    return None
