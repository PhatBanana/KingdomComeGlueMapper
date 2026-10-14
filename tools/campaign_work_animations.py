"""Reuse compatible shipped human animation fragments for legacy work calls.

Only unconstrained, untagged calls without a legacy action handle are lowered
here. Alignment, item events, context locks and tracked action handles require
their own adapters; dropping them changes work behavior.
"""
import hashlib
from pathlib import Path
import xml.etree.ElementTree as ET
import zipfile

from campaign_quest_bridge import UnsupportedOperation
from quest_import import literal
from upgrade_map import read


DATABASES = ('Animations/Mannequin/ADB/kcd_male_database.adb',
             'Animations/Mannequin/ADB/wh_female_database.adb')


def fragment_catalog(game):
    available, provenance = [], []
    with zipfile.ZipFile(Path(game) / 'Data/Animations.pak') as archive:
        for name in DATABASES:
            data = read(archive, name)
            root = ET.fromstring(data)
            fragments = root.find('FragmentList')
            if root.tag != 'AnimDB' or fragments is None:
                raise ValueError('Unsupported native animation database')
            # A procedural-only scope is not evidence of a body animation.
            names = {node.tag for node in fragments if any(
                not f.get('Tags', '') and f.find('AnimLayer/Animation') is not None
                for f in node.findall('Fragment'))}
            available.append(names)
            provenance.append(dict(path=name, sha256=hashlib.sha256(data).hexdigest()))
    return dict(common_human_fragments=sorted(set.intersection(*available)), provenance=provenance)


def lower(source, catalog):
    from campaign_behavior import quote
    attrs = {k: literal(v) for k, v in source['attributes'].items()}
    allowed = {'animation', 'tags', 'context', 'keepContext', 'InterruptSafeStart',
               'SlavedObject', 'ClearSlaveAnimOnExit', 'AnimationWUID', 'SmartObject', 'HelperID'}
    if set(attrs) - allowed or source['children']:
        raise UnsupportedOperation('Unknown legacy work animation parameters')
    for field in ('tags', 'context', 'SlavedObject', 'AnimationWUID', 'SmartObject', 'HelperID'):
        if attrs.get(field):
            raise UnsupportedOperation('Work animation requires event/context/alignment conversion: ' + field)
    for field, default in (('keepContext', 'false'), ('InterruptSafeStart', 'AUTO'),
                           ('ClearSlaveAnimOnExit', 'true')):
        if attrs.get(field, default) != default:
            raise UnsupportedOperation('Unsupported work animation lifecycle: ' + field)
    fragment = attrs.get('animation', '')
    if fragment not in catalog.get('work_animations', {}).get('common_human_fragments', []):
        raise UnsupportedOperation('Work animation lacks a compatible native human fragment: ' + fragment)
    values = dict(fragment=quote(fragment), tags='', context='', keepContext='false',
                  eventReferenceObject='', alignObject='', slaveObject='', resourceOverride='')
    contract = catalog['nodes'].get('AnimationAction')
    if contract is None or set(values) - set(contract['attributes']):
        raise UnsupportedOperation('Native work animation action contract is unavailable')
    return ET.Element('AnimationAction', values)
