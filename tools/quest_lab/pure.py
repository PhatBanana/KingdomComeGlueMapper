"""Bounded pure value operations observed in emitted quest graphs.

Inventory values are explicit scenario data: {item_class: nonnegative_count}.
These count-only descriptors do not model quality, ownership or item instances.
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


def descriptor(values):
    item = values['ItemClass']; amount = values['Amount']
    if not isinstance(item, str) or not item or type(amount) is not int or amount < 0:
        raise Unsupported('Invalid item-class/count descriptor')
    return dict(item_class=item, amount=amount)


def matches(values):
    target, items = values['ItemDescriptor'], values['InputItems']
    if not isinstance(target, dict) or set(target) != {'item_class','amount'}:
        raise Unsupported('Only item-class/count descriptors are modeled')
    descriptor({'ItemClass':target['item_class'], 'Amount':target['amount']})
    if not isinstance(items, dict) or any(not isinstance(k,str) or type(v) is not int or v < 0 for k,v in items.items()):
        raise Unsupported('Inventory must be an explicit map of item classes to nonnegative counts')
    return items.get(target['item_class'], 0) >= target['amount']


COMPARE = {'Equals': operator.eq, 'NotEquals': operator.ne,
           'Less': operator.lt, 'LessEquals': operator.le,
           'Greater': operator.gt, 'GreaterEquals': operator.ge}
COMPARE_TYPES = {'int', 'uint', 'float', 'bool', 'string'}


def reference_type(typ):
    return isinstance(typ, str) and typ.startswith('wh::') and typ.endswith('*')


def comparison(element):
    return (element.tag in ('Function', 'IfFunction') and
            element.get('DeclaringType') == 'Control' and
            element.get('MethodName') == 'Control::Compare' and
            (element.get('TypeT') in COMPARE_TYPES or reference_type(element.get('TypeT'))))


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
        ('ItemDescriptor', {'ItemClass','Amount'}, descriptor),
    ('MemberFunction','wh::entitymodule::ItemDescriptor','FullyMatchesItems'):
        ('bool', {'ItemDescriptor','InputItems'}, matches),
}


def operation(element):
    if element.tag == 'Function' and comparison(element):
        return ('bool', {'ValueA','ValueB','Op'}, lambda v: compare(v, element.get('TypeT')))
    return OPERATIONS.get((element.tag, element.get('DeclaringType'), element.get('MethodName')))
