"""Bounded native collections and lazy value switches, without world effects."""
import copy

from . import Unsupported
from .expressions import boolean, literal
from .pure import number, exact_integer


ARRAY_TYPES = {'wh::rpgmodule::Souls', 'wh::xgenaimodule::LinkableObjects',
               'wh::xgenaimodule::Areas', 'wh::xgenaimodule::SmartObjects',
               'wh::entitymodule::EquipmentSlotIds'}
SCALARS = {'bool', 'int', 'uint', 'float', 'string'}
KINDS = {'MakeArray', 'ContainsElement', 'Switch'}


def validate(value, typ, enums=None):
    if typ == 'bool': boolean(value)
    elif typ == 'int': exact_integer(value)
    elif typ == 'uint': exact_integer(value, True)
    elif typ == 'float': number(value)
    elif typ == 'string':
        if not isinstance(value, str): raise Unsupported('Expected string')
    elif typ in (enums or {}):
        if not isinstance(value, str) or value not in enums[typ]:
            raise Unsupported('Unknown enumeration value for ' + typ)
    else: raise Unsupported('Value type is not modeled: ' + str(typ))


def array(value):
    if not isinstance(value, list) or any(not isinstance(v, str) or not v for v in value):
        raise Unsupported('Collection requires a list of explicit nonempty identities or slot names')


def describe(element, enums):
    kind, typ = element.tag, element.get('TypeT')
    if kind not in KINDS: return None
    if kind in ('MakeArray', 'ContainsElement'):
        if typ not in ARRAY_TYPES: raise Unsupported('Collection type is not modeled: ' + str(typ))
        ports = {c.get('Name') for c in element.findall('Constant')} | {
            c.get('Name') for c in element.findall('Asset')} | {e.get('To') for e in element.findall('Edge')}
        if kind == 'ContainsElement':
            return dict(kind=kind, inputs={'Array', 'Value'}, outputs={'Result'}, enums={})
        ordered = sorted(ports)
        if ordered != list('ABCDEFGHIJKLMNOPQRSTUVWXYZ'[:len(ordered)]):
            raise Unsupported('MakeArray requires contiguous explicit A..Z inputs')
        return dict(kind=kind, inputs=ports, outputs={'Array'}, order=ordered, enums={})
    if typ not in {'bool', 'int', 'uint', 'string'} | set(enums):
        raise Unsupported('Switch selector type is not modeled: ' + str(typ))
    labels = element.get('SwitchValues', '').split()
    if len(set(labels)) != len(labels): raise ValueError('Duplicate switch case')
    cases = [(literal(label), label) for label in labels]
    for value, _ in cases: validate(value, typ, enums)
    types = element.get('ValueTypes', '').split()
    if not types or any(t not in SCALARS | set(enums) for t in types):
        raise Unsupported('Switch output types are not modeled: ' + str(types))
    outputs = {'Value' + str(i + 1) for i in range(len(types))}
    return dict(kind=kind, inputs={'Switch'} | {label + p for label in [*labels, 'Default'] for p in outputs},
                outputs=outputs, cases=cases, selector_type=typ, output_types=types, enums=enums)


def evaluate(spec, port, get):
    if port not in spec['outputs']: raise Unsupported('Unknown collection output: ' + port)
    if spec['kind'] == 'MakeArray':
        values = [get(p) for p in spec['order']]
        array(values)
        return copy.deepcopy(values)
    if spec['kind'] == 'ContainsElement':
        values, value = get('Array'), get('Value')
        array(values); array([value])
        return value in values
    selector = get('Switch')
    validate(selector, spec['selector_type'], spec['enums'])
    label = next((label for value, label in spec['cases'] if type(value) is type(selector) and value == selector), 'Default')
    # Unselected branches can contain unbound engine values; do not read them.
    value = get(label + port)
    validate(value, spec['output_types'][int(port[5:]) - 1], spec['enums'])
    return copy.deepcopy(value)
