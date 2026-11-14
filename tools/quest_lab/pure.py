"""Bounded pure value operations observed in emitted quest graphs.

Inventory values are explicit scenario data: {item_class: nonnegative_count}, or
{item_class: [{"amount": n, "health": h}, ...]} when a descriptor asks for a
minimum health. Ownership, stolen status and item instances are not modeled.
"""
import math
import operator
from . import Unsupported


def number(value):
    if type(value) not in (int, float) or not math.isfinite(value):
        raise Unsupported('Expected a finite numeric value')
    return value


def integer(value, unsigned=False):
    number(value)
    value = math.trunc(value)
    lo, hi = (0, 2**32 - 1) if unsigned else (-2**31, 2**31 - 1)
    if not lo <= value <= hi: raise Unsupported('Integer conversion is outside the modeled 32-bit range')
    return value


def exact_integer(value, unsigned=False):
    if type(value) is not int: raise Unsupported('Integer cast requires an integer input')
    return integer(value, unsigned)


def divide(values):
    a, b = number(values['A']), number(values['B'])
    if b == 0: raise Unsupported('Native division by zero is not modeled')
    return number(float(a / b))


def integral_round(values):
    value = number(values['Number'])
    # Every rounding mode agrees for an integral input. Native fractional and
    # halfway rounding have not been verified; do not guess Python's tie rule.
    if value != math.trunc(value): raise Unsupported('Fractional native Round semantics are not modeled')
    return float(value)


DESCRIPTOR_KEYS = {'item_class', 'amount', 'minimum_health'}


def descriptor(values):
    """Class descriptor: Amount and MinimumHealth are optional (a class-only descriptor is a filter)."""
    item, amount, health = values['ItemClass'], values.get('Amount'), values.get('MinimumHealth')
    if not isinstance(item, str) or not item or (amount is not None and (type(amount) is not int or amount < 0)):
        raise Unsupported('Invalid item-class/count descriptor')
    result = dict(item_class=item)
    if amount is not None: result['amount'] = amount
    if health is not None:
        if type(health) not in (int, float) or not 0 <= health <= 1:
            raise Unsupported('MinimumHealth must be a number from 0 to 1')
        result['minimum_health'] = float(health)
    return result


def checked_descriptor(target, counted=True):
    if not isinstance(target, dict) or not {'item_class'} <= set(target) <= DESCRIPTOR_KEYS:
        raise Unsupported('Only item-class, count and minimum-health descriptors are modeled')
    descriptor({'ItemClass': target['item_class'], 'Amount': target.get('amount'),
                'MinimumHealth': target.get('minimum_health')})
    if counted and 'amount' not in target:
        raise Unsupported('Matching needs a descriptor with an Amount')
    return target


def checked_items(items):
    valid = isinstance(items, dict)
    for key, held in (items.items() if valid else ()):
        if not isinstance(key, str) or not key: valid = False
        elif type(held) is int: valid = valid and held >= 0
        elif isinstance(held, list):
            valid = valid and all(isinstance(s, dict) and set(s) == {'amount', 'health'} and type(s['amount']) is int
                                  and s['amount'] > 0 and type(s['health']) in (int, float) and 0 <= s['health'] <= 1
                                  for s in held)
        else: valid = False
    if not valid:
        raise Unsupported('Inventory must be an explicit map of item classes to nonnegative counts or health stacks')
    return items


def matches(values):
    from .world import eligible
    target, items = checked_descriptor(values['ItemDescriptor']), checked_items(values['InputItems'])
    return eligible(items, target) >= target['amount']


def item_delivery(values):
    """CreateItemDelivery: a value. Opening, accepting and rejecting belong to ItemDeliveryHandler."""
    from .world import DELIVERY_MODES
    rows, inventory = values['DeliveryDescriptors'], values['DeliveryInventory']
    filters, labels, mode = values.get('PlayerInventoryFilters'), values.get('Labels'), values.get('DeliveryMode', 'Exactly')
    if not isinstance(rows, list) or not rows: raise Unsupported('A delivery needs descriptors')
    for row in rows: checked_descriptor(row)
    if filters is not None:
        if not isinstance(filters, list): raise Unsupported('Delivery filters must be descriptors')
        for row in filters: checked_descriptor(row, counted=False)
    if labels is not None and (not isinstance(labels, list) or len(labels) != len(rows)
                               or any(not isinstance(v, str) or not v for v in labels)):
        raise Unsupported('A delivery needs one label per descriptor')
    if not isinstance(inventory, str) or not inventory:
        raise Unsupported('A delivery needs an explicit receiving inventory')
    if mode not in DELIVERY_MODES: raise Unsupported('Unknown DeliveryMode: ' + str(mode))
    return dict(descriptors=rows, inventory=inventory, filters=filters, mode=mode, labels=labels)


COMPARE = {'Equals': operator.eq, 'NotEquals': operator.ne,
           'Less': operator.lt, 'LessEquals': operator.le,
           'Greater': operator.gt, 'GreaterEquals': operator.ge}
COMPARE_TYPES = {'int', 'uint', 'float', 'bool', 'string'}
# Native enumerations a graph compares by name (retail: IfFunction Control::Compare TypeT="DeliveryResult").
# A handler without a result yet reads None, which equals no member.
COMPARE_ENUMS = {'DeliveryResult': ('Success', 'Canceled', 'WrongItems', 'MissingItems', 'StolenMismatch',
                                    'QualityMismatch', 'PriceMismatch', 'Invalid')}


def reference_type(typ):
    return isinstance(typ, str) and typ.startswith('wh::') and typ.endswith('*')


def comparison(element):
    return (element.tag in ('Function', 'IfFunction') and
            element.get('DeclaringType') == 'Control' and
            element.get('MethodName') == 'Control::Compare' and
            (element.get('TypeT') in COMPARE_TYPES or element.get('TypeT') in COMPARE_ENUMS
             or reference_type(element.get('TypeT'))))


def compare(values, typ):
    op, a, b = values['Op'], values['ValueA'], values['ValueB']
    if op not in COMPARE: raise Unsupported('Unsupported comparison operator: ' + str(op))
    if typ in ('int', 'uint'):
        for v in (a, b):
            if type(v) is not int: raise Unsupported('Integer comparison requires integer values')
            integer(v, typ == 'uint')
    elif typ == 'float':
        number(a); number(b)
    elif typ in ('bool', 'string'):
        expected = bool if typ == 'bool' else str
        if type(a) is not expected or type(b) is not expected:
            raise Unsupported('Comparison values do not match ' + typ)
        if op not in ('Equals', 'NotEquals'):
            raise Unsupported('Only equality is modeled for ' + typ)
    elif typ in COMPARE_ENUMS:
        if any(v is not None and v not in COMPARE_ENUMS[typ] for v in (a, b)):
            raise Unsupported('Comparison value is not a member of ' + typ)
        if op not in ('Equals', 'NotEquals'):
            raise Unsupported('Only equality is modeled for ' + typ)
    elif reference_type(typ):
        if any(v is not None and (not isinstance(v, str) or not v) for v in (a, b)):
            raise Unsupported('Reference comparison requires explicit nonempty identities or null')
        if op not in ('Equals', 'NotEquals'):
            raise Unsupported('Only reference identity equality is modeled')
    else: raise Unsupported('Comparison type is not modeled: ' + str(typ))
    return COMPARE[op](a, b)


# kind, declaring type, method -> output port, argument ports, evaluator
OPERATIONS = {
    ('Function','wh::conceptmodule::math','wh::conceptmodule::math::AddFloat'):
        ('float', {'A','B'}, lambda v: number(float(number(v['A']) + number(v['B'])))),
    ('Function','wh::conceptmodule::math','wh::conceptmodule::math::MultiplyFloat'):
        ('float', {'A','B'}, lambda v: number(float(number(v['A']) * number(v['B'])))),
    ('Function','wh::conceptmodule::math','wh::conceptmodule::math::DivideFloat'):
        ('float', {'A','B'}, divide),
    ('Function','wh::conceptmodule::math','wh::conceptmodule::math::Round'):
        ('float', {'Number'}, integral_round),
    ('Function','math::conversion','math::conversion::ToInt(float)'):
        ('int', {'float'}, lambda v: integer(v['float'])),
    ('Function','math::conversion','math::conversion::ToUint(int)'):
        ('uint', {'int'}, lambda v: integer(v['int'], True)),
    ('Function','math::conversion','math::conversion::ToInt(uint)'):
        ('int', {'uint'}, lambda v: integer(exact_integer(v['uint'], True))),
    ('Function','math::conversion','math::conversion::ToFloat(int)'):
        ('float', {'int'}, lambda v: float(exact_integer(v['int']))),
    ('Function','wh::entitymodule','wh::entitymodule::CreateItemClassDescriptor'):
        ('ItemDescriptor', {'ItemClass','Amount','MinimumHealth'}, descriptor),
    ('Function','wh::entitymodule','wh::entitymodule::CreateItemDelivery'):
        ('ItemDelivery', {'DeliveryDescriptors','DeliveryInventory','PlayerInventoryFilters','DeliveryMode','Labels'},
         item_delivery),
    ('MemberFunction','wh::entitymodule::ItemDescriptor','FullyMatchesItems'):
        ('bool', {'ItemDescriptor','InputItems'}, matches),
}


def operation(element):
    if element.tag == 'Function' and comparison(element):
        return ('bool', {'ValueA','ValueB','Op'}, lambda v: compare(v, element.get('TypeT')))
    return OPERATIONS.get((element.tag, element.get('DeclaringType'), element.get('MethodName')))
