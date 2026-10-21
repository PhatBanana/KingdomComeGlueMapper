"""Lower legacy sustained combat controls to native scoped decorators.

The old controls are running leaves in parallel exercise routines. A native
decorator must therefore own an indefinite child, not a Success node: finishing
it would finish a Parallel/Any exercise before its listener or timer fires.
Only explicit, observed modes are accepted. No quest or actor names belong here.
"""
import xml.etree.ElementTree as ET

from campaign_quest_bridge import UnsupportedOperation
from quest_import import literal


OPERATIONS = frozenset(('MeleeGuardAutomation', 'MeleeDefenseAutomation',
                        'MeleeOffenseAutomation', 'WeaponAutomation'))


def observe(node, evidence):
    """Collect values from executable native nodes, never editor metadata."""
    if node.tag not in {name + 'Decorator' for name in OPERATIONS}:
        return
    for field, value in node.attrib.items():
        evidence.setdefault(node.tag, {}).setdefault(field, set()).add(value)


def lower(source, catalog):
    op = source['op']
    attrs = {k: literal(v) for k, v in source['attributes'].items()}
    if op not in OPERATIONS or source['children']:
        raise UnsupportedOperation('Combat automation requires a sustained source leaf')
    target = op + 'Decorator'
    values = {'active': 'true'}
    if op == 'MeleeGuardAutomation':
        # The source enum uses initial capitals; native runtime XML uses lower
        # camel case. Do not guess the omitted source enum's default.
        modes = {'Automate': 'automate', 'ForceEnable': 'forceEnable',
                 'FreeBlock': 'freeBlock'}
        if set(attrs) != {'GuardMode'} or attrs['GuardMode'] not in modes:
            raise UnsupportedOperation('Combat guard requires an explicit supported source mode')
        values['GuardMode'] = modes[attrs['GuardMode']]
    elif op == 'WeaponAutomation':
        # None suppresses automatic weapon changes, so noAnimation=false adds
        # no missing transition policy. Other weapon modes need their own
        # animation-transition contract; never silently discard that field.
        if attrs != {'WeaponChange': 'none', 'noAnimation': 'false'}:
            raise UnsupportedOperation('Weapon automation transition policy requires conversion')
        values['WeaponChange'] = 'none'
    elif attrs:
        raise UnsupportedOperation('Unknown sustained combat automation parameters')
    evidence = catalog.get('combat_automation', {}).get(target, {})
    contract = catalog.get('nodes', {}).get(target, {})
    if (set(values) - set(contract.get('attributes', ())) or
            any(value not in evidence.get(field, ()) for field, value in values.items())):
        raise UnsupportedOperation('Native combat automation contract is unavailable: ' + target)
    wait = dict(duration="'-1'", timeType='GameTime', doFail='false', variation='')
    if set(wait) - set(catalog.get('nodes', {}).get('Wait', {}).get('attributes', ())):
        raise UnsupportedOperation('Native sustained combat wait contract is unavailable')
    node = ET.Element(target, values)
    ET.SubElement(node, 'Wait', wait)
    return node
